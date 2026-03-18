"""
core.py — GBank Poster backend
All parsing, formatting, Discord posting, and addon installation logic.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime
from typing import Callable, Optional

# ─── Constants ─────────────────────────────────────────────────────────────────
EMBED_DESCRIPTION_LIMIT = 4096
TITLE_LIMIT              = 256
FOOTER_LIMIT             = 2048
SAFETY_MARGIN            = 250
USABLE_LIMIT             = EMBED_DESCRIPTION_LIMIT - SAFETY_MARGIN

ADDON_NAME  = "GBankExporter"
ADDON_FILES = ["GBankExporter.toc", "GBankExporterAddon.lua"]

CATEGORY_ORDER = [
    "Consumables", "Containers", "Weapons", "Armor",
    "Reagents", "Trade Goods", "Recipes", "Miscellaneous",
]

# ─── Default structures ─────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "savedvariables_path": "",
    "webhook_url":         "",   # shared URL used by all characters
    "characters":          {},
}

# Per-character settings.  All fields optional — blanks/None fall back to defaults.
DEFAULT_CHAR_CONFIG = {
    "enabled":             True,
    "username":            "",    # blank → character name from key
    "embed_title":         "",    # blank → character name from key
    "embed_color":         None,
    "avatar_mode":         "file", # "file" = upload local; "url" = embed URL
    "avatar_image_path":   "",
    "avatar_url":          "",
    "avatar_file_history": [],
    "avatar_url_history":  [],
    "webhook_url":         "",    # blank → use top-level webhook_url
}

# ─── Paths ─────────────────────────────────────────────────────────────────────
def _base_dir() -> str:
    """Returns the directory used for config/state files.
    - Frozen (EXE): %APPDATA%\GBankPoster\ so config survives the EXE being moved.
    - Dev (python app.py): next to the script, same as before.
    """
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        path = os.path.join(appdata, "GBankPoster")
        os.makedirs(path, exist_ok=True)
        return path
    return os.path.dirname(os.path.abspath(__file__))


def get_bundled_addon_dir() -> str:
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks bundled data to sys._MEIPASS, not next to the EXE
        return os.path.join(sys._MEIPASS, "addon_files")
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "Addons"))


# ─── JSON helpers ───────────────────────────────────────────────────────────────
def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_config(path: str) -> dict:
    raw = load_json(path)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))

    # Migrate old "default_webhook" structure → flat webhook_url
    if "default_webhook" in raw and "webhook_url" not in raw:
        raw["webhook_url"] = raw["default_webhook"].get("url", "")

    cfg.update({k: v for k, v in raw.items()})

    # Migrate old per-character keys
    for ck, cv in cfg.get("characters", {}).items():
        if "webhook_username" in cv:
            cv.setdefault("username", cv.pop("webhook_username"))
        if "webhook_avatar_url" in cv:
            cv.setdefault("avatar_url", cv.pop("webhook_avatar_url"))
        if "webhook_avatar_image" in cv:
            cv.setdefault("avatar_image_path", cv.pop("webhook_avatar_image"))
        cv.pop("use_default_webhook", None)

    return cfg


def save_config(path: str, config: dict) -> None:
    save_json(path, config)


def char_name_from_key(char_key: str) -> str:
    """Extract character name from 'CharName-Realm' key."""
    return char_key.split("-")[0] if "-" in char_key else char_key


def get_char_config(config: dict, char_key: str) -> dict:
    merged = dict(DEFAULT_CHAR_CONFIG)
    merged.update(config.get("characters", {}).get(char_key, {}))
    return merged


# ─── Addon installation ─────────────────────────────────────────────────────────
def find_addon_install_paths() -> list:
    era_dirs = ["_classic_era_", "_classic_", "_retail_", ""]
    found = []
    for drive in "CDEFG":
        for sub in [
            f"{drive}:\\World of Warcraft",
            f"{drive}:\\Program Files\\World of Warcraft",
            f"{drive}:\\Program Files (x86)\\World of Warcraft",
            f"{drive}:\\Games\\World of Warcraft",
        ]:
            if not os.path.isdir(sub):
                continue
            for era in era_dirs:
                addons_path = os.path.join(sub, era, "Interface", "AddOns") if era \
                    else os.path.join(sub, "Interface", "AddOns")
                if os.path.isdir(addons_path) and addons_path not in found:
                    found.append(addons_path)
    return found


def is_addon_installed(addons_path: str) -> bool:
    return os.path.isfile(os.path.join(addons_path, ADDON_NAME, "GBankExporter.toc"))


def install_addon(addons_path: str):
    src_dir  = get_bundled_addon_dir()
    dest_dir = os.path.join(addons_path, ADDON_NAME)
    missing  = [f for f in ADDON_FILES
                if not os.path.isfile(os.path.join(src_dir, f))]
    if missing:
        return False, f"Bundled addon files not found: {', '.join(missing)}"
    try:
        os.makedirs(dest_dir, exist_ok=True)
        for fname in ADDON_FILES:
            shutil.copy2(os.path.join(src_dir, fname),
                         os.path.join(dest_dir, fname))
        return True, f"Installed to {dest_dir}"
    except Exception as exc:
        return False, str(exc)


def derive_savedvariables_from_addons_path(addons_path: str) -> list:
    wow_root = os.path.dirname(os.path.dirname(os.path.abspath(addons_path)))
    wtf_acct = os.path.join(wow_root, "WTF", "Account")

    found = []
    if not os.path.isdir(wtf_acct):
        return found

    try:
        for entry in os.listdir(wtf_acct):
            acct_dir = os.path.join(wtf_acct, entry)
            if not os.path.isdir(acct_dir):
                continue
            sv = os.path.join(acct_dir, "SavedVariables", "GBankExporter.lua")
            if sv not in found:
                found.append(sv)
    except PermissionError:
        pass

    return found


# ─── SavedVariables detection (global scan) ────────────────────────────────────
def find_savedvariables_paths() -> list:
    """Scan all known WoW installation locations for GBankExporter.lua."""
    era_dirs = ["_classic_era_", "_classic_", "_retail_", ""]
    found = []
    for drive in "CDEFG":
        for sub in [
            f"{drive}:\\World of Warcraft",
            f"{drive}:\\Program Files\\World of Warcraft",
            f"{drive}:\\Program Files (x86)\\World of Warcraft",
            f"{drive}:\\Games\\World of Warcraft",
        ]:
            if not os.path.isdir(sub):
                continue
            for era in era_dirs:
                wtf_acct = os.path.join(sub, era, "WTF", "Account") if era \
                    else os.path.join(sub, "WTF", "Account")
                if not os.path.isdir(wtf_acct):
                    continue
                try:
                    for acct in os.listdir(wtf_acct):
                        sv = os.path.join(wtf_acct, acct,
                                          "SavedVariables", "GBankExporter.lua")
                        if os.path.isfile(sv) and sv not in found:
                            found.append(sv)
                except PermissionError:
                    pass
    return found


# ─── SavedVariables parsing ────────────────────────────────────────────────────
def _extract_string(content, pos):
    buf = []
    while pos < len(content):
        ch = content[pos]
        if ch == "\\":
            pos += 1
            if pos < len(content):
                esc = content[pos]
                if   esc == "n":  buf.append("\n")
                elif esc == "t":  buf.append("\t")
                elif esc == "\\": buf.append("\\")
                elif esc == '"':  buf.append('"')
                else:             buf.append(esc)
        elif ch == '"':
            return "".join(buf), pos + 1
        else:
            buf.append(ch)
        pos += 1
    return "".join(buf), pos


def _parse_char_fields(block):
    result = {}
    for field in ("updated_at", "character", "realm", "blob"):
        # Try quoted string value first (character, realm, blob)
        pat_str = r'\["' + field + r'"\]\s*=\s*"((?:\\.|[^"\\])*)"'
        m = re.search(pat_str, block)
        if m:
            raw = m.group(1)
            try:
                result[field] = bytes(raw, "utf-8").decode("unicode_escape")
            except Exception:
                result[field] = raw
            continue
        # Try unquoted numeric value (updated_at is written as a bare integer)
        pat_num = r'\["' + field + r'"\]\s*=\s*(\d+)'
        m = re.search(pat_num, block)
        if m:
            result[field] = m.group(1)
    return result


def parse_savedvariables(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    results = {}
    db_pos    = content.find("GBankExporterDB")
    if db_pos == -1:
        return results
    brace_pos = content.find("{", db_pos)
    if brace_pos == -1:
        return results

    pos = brace_pos + 1
    while pos < len(content):
        while pos < len(content) and content[pos] in " \t\n\r":
            pos += 1
        if pos >= len(content):
            break
        ch = content[pos]
        if ch == "}":
            break
        if ch == "[":
            pos += 1
            if pos < len(content) and content[pos] == '"':
                pos += 1
                key, pos = _extract_string(content, pos)
                while pos < len(content) and content[pos] in "] \t\n\r=":
                    pos += 1
                if pos < len(content) and content[pos] == "{":
                    depth = 1
                    inner_start = pos + 1
                    scan = inner_start
                    while scan < len(content) and depth > 0:
                        c = content[scan]
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        elif c == '"':
                            scan += 1
                            while scan < len(content):
                                if content[scan] == "\\":
                                    scan += 2
                                    continue
                                if content[scan] == '"':
                                    break
                                scan += 1
                        scan += 1
                    inner = content[inner_start:scan]
                    pos   = scan + 1
                    if "-" in key:
                        data = _parse_char_fields(inner)
                        if data.get("blob"):
                            results[key] = data
                elif pos < len(content) and content[pos] == '"':
                    pos += 1
                    _, pos = _extract_string(content, pos)
                else:
                    pos += 1
            else:
                pos += 1
        else:
            pos += 1

    if not results:
        data = _parse_char_fields(content)
        if data.get("blob"):
            char  = data.get("character", "Unknown")
            realm = data.get("realm",     "Unknown")
            results[f"{char}-{realm}"] = data

    return results


# ─── Blob → snapshot ───────────────────────────────────────────────────────────
def parse_blob(blob, updated_at=""):
    """
    Parse the blob format written by GBankExporterAddon.lua:
        ##CATEGORY:CategoryName
        itemID|ItemName|count
    """
    cats = {name: [] for name in CATEGORY_ORDER}
    current = None
    for raw in blob.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("##CATEGORY:"):
            current = line[len("##CATEGORY:"):].strip()
            if current not in cats:
                cats[current] = []
            continue
        if current is None:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            item_id = int(parts[0].strip())
            count   = int(parts[2].strip())
        except ValueError:
            continue
        name = parts[1].strip()
        if name:
            cats[current].append({"item_id": item_id, "name": name, "count": count})
    return {
        "updated_at": updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "categories": cats,
    }


# ─── Discord embed building ────────────────────────────────────────────────────
def item_to_line(item):
    url = f"https://www.wowhead.com/classic/item={item['item_id']}"
    return f"{item['count']}x [{item['name']}]({url})"


def _split_category(cat, items):
    lines = [item_to_line(i) for i in items]
    full  = f"**{cat}**\n" + "\n".join(lines)
    if len(full) <= USABLE_LIMIT:
        return [full]
    hdr_len = len(f"**{cat} (999/999)**\n")
    chunks = []
    cur = []
    cur_len = 0
    for line in lines:
        projected = hdr_len + cur_len + len(line) + (1 if cur else 0)
        if cur and projected > USABLE_LIMIT:
            chunks.append(cur)
            cur, cur_len = [line], len(line)
        else:
            cur_len += (1 + len(line)) if cur else len(line)
            cur.append(line)
    if cur:
        chunks.append(cur)
    total = len(chunks)
    return [f"**{cat} ({i + 1}/{total})**\n" + "\n".join(c)
            for i, c in enumerate(chunks)]


def build_blocks(snapshot):
    blocks = []
    for cat in CATEGORY_ORDER:
        items = snapshot["categories"].get(cat, [])
        if not items:
            continue
        for text in _split_category(cat, items):
            blocks.append({"label": cat, "text": text, "length": len(text)})
    return blocks


def pack_blocks(blocks):
    if not blocks:
        return ["*Guild bank is currently empty.*"]
    blocks = sorted(blocks, key=lambda b: b["length"], reverse=True)
    msgs    = []
    lengths = []
    for block in blocks:
        best_i = best_rem = None
        for i, cur in enumerate(lengths):
            sep  = 2 if msgs[i] else 0
            proj = cur + sep + block["length"]
            if proj <= USABLE_LIMIT:
                rem = USABLE_LIMIT - proj
                if best_rem is None or rem < best_rem:
                    best_rem, best_i = rem, i
        if best_i is not None:
            if msgs[best_i]:
                msgs[best_i].append("")
                lengths[best_i] += 2
            msgs[best_i].append(block["text"])
            lengths[best_i] += block["length"]
        else:
            msgs.append([block["text"]])
            lengths.append(block["length"])
    return ["\n".join(parts) for parts in msgs]


def build_payloads(bodies, updated_at, title_template, username,
                   avatar_url, embed_color=None):
    total    = len(bodies)
    payloads = []
    for idx, body in enumerate(bodies, start=1):
        title = title_template if total == 1 else f"{title_template} ({idx}/{total})"
        embed = {
            "title":       title[:TITLE_LIMIT],
            "description": body[:EMBED_DESCRIPTION_LIMIT],
            "footer":      {"text": f"Last updated: {updated_at}"[:FOOTER_LIMIT]},
        }
        if embed_color is not None:
            embed["color"] = embed_color
        payload = {"embeds": [embed]}
        if username:
            payload["username"] = username[:80]
        if avatar_url:
            payload["avatar_url"] = avatar_url
        payloads.append(payload)
    return payloads


# ─── HTTP helpers ───────────────────────────────────────────────────────────────
_HEADERS = {"User-Agent": "GBankPoster/2.0 (Windows)"}


def _post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url + "?wait=true", data=data,
        headers={**_HEADERS, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {body}") from e


def _delete(webhook_url, message_id):
    req = urllib.request.Request(
        f"{webhook_url}/messages/{message_id}",
        headers=_HEADERS, method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise


# ─── Webhook avatar PATCH ─────────────────────────────────────────────────────
def patch_webhook_avatar(webhook_url, image_path, max_size=512):
    """
    Set the webhook's permanent default avatar by PATCHing Discord with a
    base64-encoded local image.  Resizes to max_size x max_size before upload.
    No image hosting required.
    """
    from PIL import Image as _Image
    import io as _io

    patch_url = webhook_url.split("?")[0].rstrip("/")

    img = _Image.open(image_path).convert("RGBA")
    img.thumbnail((max_size, max_size), _Image.LANCZOS)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    payload = {"avatar": f"data:image/png;base64,{img_b64}"}
    data    = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        patch_url, data=data,
        headers={**_HEADERS, "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {body}") from e


# ─── Post pipeline ──────────────────────────────────────────────────────────────
def _effective_webhook(config, char_key):
    char_cfg  = get_char_config(config, char_key)
    char_name = char_name_from_key(char_key)
    # avatar_mode "file" = webhook has permanent avatar (no per-post URL)
    # avatar_mode "url"  = pass URL directly in each embed payload
    avatar_mode = char_cfg.get("avatar_mode", "file")
    avatar_url  = char_cfg.get("avatar_url", "") if avatar_mode == "url" else ""
    return {
        "url":         (char_cfg.get("webhook_url") or config.get("webhook_url", "")).strip(),
        "username":    (char_cfg.get("username")    or char_name).strip(),
        "embed_title": (char_cfg.get("embed_title") or char_name).strip(),
        "embed_color": char_cfg.get("embed_color"),
        "avatar_url":  avatar_url,
    }


def post_character(char_key, char_data, config, state, log=print):
    wh  = _effective_webhook(config, char_key)
    url = wh.get("url", "").strip()
    if not url:
        log(f"[{char_key}] No webhook URL — skipping.")
        return False

    # updated_at from the Lua is a Unix timestamp integer; convert to readable string
    raw_ts = char_data.get("updated_at", "")
    try:
        updated_str = datetime.fromtimestamp(int(raw_ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        updated_str = str(raw_ts)
    snapshot  = parse_blob(char_data["blob"], updated_str)
    blocks    = build_blocks(snapshot)
    bodies    = pack_blocks(blocks)
    char_name = char_name_from_key(char_key)
    payloads  = build_payloads(
        bodies,
        updated_at     = snapshot["updated_at"],
        title_template = wh.get("embed_title") or char_name,
        username       = wh.get("username")    or char_name,
        avatar_url     = wh.get("avatar_url", "") or "",
        embed_color    = wh.get("embed_color"),
    )

    old_ids = state.get(char_key, {}).get("message_ids", [])
    for mid in old_ids:
        try:
            _delete(url, mid)
            log(f"[{char_key}] Deleted old message {mid}")
        except Exception as exc:
            log(f"[{char_key}] Warning — could not delete {mid}: {exc}")

    new_ids = []
    for i, payload in enumerate(payloads, start=1):
        try:
            created = _post(url, payload)
            new_ids.append(created["id"])
            log(f"[{char_key}] Posted {i}/{len(payloads)}: {created['id']}")
        except Exception as exc:
            log(f"[{char_key}] Error on message {i}: {exc}")
            state.setdefault(char_key, {})["message_ids"] = new_ids
            state[char_key]["last_posted"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return False

    state.setdefault(char_key, {})["message_ids"]   = new_ids
    state[char_key]["last_posted"]     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state[char_key]["last_updated_at"] = str(char_data.get("updated_at", ""))
    log(f"[{char_key}] Done — {len(payloads)} message(s) posted.")
    return True


def post_all_enabled(config, state, log=print):
    sv_path = config.get("savedvariables_path", "").strip()
    if not sv_path or not os.path.exists(sv_path):
        log("SavedVariables file not found yet — waiting for first /gbankexport reload.")
        return False
    try:
        all_chars = parse_savedvariables(sv_path)
    except Exception as exc:
        log(f"ERROR reading SavedVariables: {exc}")
        return False
    if not all_chars:
        log("No character data found in SavedVariables.")
        return False

    success = True
    for char_key, char_data in all_chars.items():
        char_cfg = get_char_config(config, char_key)
        if not char_cfg["enabled"]:
            log(f"[{char_key}] Skipping (disabled).")
            continue

        # Only post this character if their data actually changed since last post
        current_ts = str(char_data.get("updated_at", ""))
        last_ts    = state.get(char_key, {}).get("last_updated_at", "")
        if current_ts and current_ts == last_ts:
            log(f"[{char_key}] Data unchanged since last post — skipping.")
            continue

        if not post_character(char_key, char_data, config, state, log):
            success = False
    return success


# ─── File watcher ───────────────────────────────────────────────────────────────
def watch_savedvariables(path, on_change, stop_event, poll_interval=2.0):
    """
    Poll *path* every *poll_interval* seconds and call *on_change* when it changes.
    Handles the file not existing yet — just keeps polling until it appears.
    """
    last_mtime = None
    while not stop_event.is_set():
        try:
            if os.path.exists(path):
                mtime = os.path.getmtime(path)
                if last_mtime is None:
                    last_mtime = mtime
                elif mtime != last_mtime:
                    last_mtime = mtime
                    on_change()
        except Exception:
            pass
        stop_event.wait(poll_interval)
