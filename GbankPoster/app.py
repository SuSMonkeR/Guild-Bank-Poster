"""
app.py — GBank Poster
System tray application with setup wizard.

First run   → Setup Wizard (6 steps)
After setup → Sits silently in system tray, auto-posts on file change
Tray menu   → Open Settings | Post Now | Quit
"""
from __future__ import annotations

import json
import os
import sys
import queue
import tempfile
import threading
import winreg
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, scrolledtext, ttk
from datetime import datetime
from typing import Optional, Callable

import colorsys
import io as _io_module
import pystray
from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

import core

# ─── Paths ─────────────────────────────────────────────────────────────────────
_BASE  = core._base_dir()
CONFIG = os.path.join(_BASE, "gbank_config.json")
STATE  = os.path.join(_BASE, "gbank_state.json")

APP_NAME = "GBankPoster"

# --- DPI scaling ---
def _get_dpi_scale() -> float:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        import ctypes
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0

_DPI_SCALE = _get_dpi_scale()

def _scaled(size: int) -> int:
    return max(1, round(size * _DPI_SCALE))


_IMG_EXTS   = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_TYPES = [("Image files", "*.png *.jpg *.jpeg *.gif *.webp"),
               ("All files",   "*.*")]

C_BG      = "#1e1e2e"
C_PANEL   = "#252535"
C_BORDER  = "#313145"
C_ACCENT  = "#89b4fa"
C_ACCENT2 = "#cba6f7"
C_TEXT    = "#cdd6f4"
C_DIM     = "#6c7086"
C_OK      = "#a6e3a1"
C_ERR     = "#f38ba8"
C_WARN    = "#fab387"


# ═══════════════════════════════════════════════════════════════════════════════
#  TRAY ICON
# ═══════════════════════════════════════════════════════════════════════════════

def _make_tray_icon(size: int = 64) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad  = 2
    draw.ellipse([pad, pad, size - pad, size - pad],
                 fill="#c9a227", outline="#f0c040", width=2)
    draw.ellipse([4, 4, size - 4, size - 4], outline="#f0c040", width=1)
    cx, cy    = size // 2, size // 2
    font_size = max(20, size // 3)
    try:
        fnt = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        fnt = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "G", font=fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2 - 1), "G", font=fnt, fill="#1a0e00")
    return img


# ═══════════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════════

def _styled_check(parent, text: str, variable: tk.Variable, **kw) -> tk.Checkbutton:
    return tk.Checkbutton(
        parent, text=text, variable=variable,
        bg=C_BG, fg=C_TEXT,
        activebackground=C_BG, activeforeground=C_ACCENT,
        selectcolor=C_PANEL, relief=tk.FLAT, highlightthickness=0,
        cursor="hand2", font=("Segoe UI", _scaled(10)), **kw
    )


def _apply_theme(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".",
        background=C_BG, foreground=C_TEXT,
        fieldbackground=C_PANEL, bordercolor=C_BORDER,
        darkcolor=C_PANEL, lightcolor=C_PANEL,
        troughcolor=C_PANEL, selectbackground=C_ACCENT,
        selectforeground=C_BG, insertcolor=C_TEXT,
        font=("Segoe UI", _scaled(10)),
    )
    style.configure("TFrame",        background=C_BG)
    style.configure("TLabel",        background=C_BG, foreground=C_TEXT)
    style.configure("TCheckbutton",  background=C_BG, foreground=C_TEXT)
    style.configure("TEntry",        fieldbackground=C_PANEL, foreground=C_TEXT,
                                     bordercolor=C_BORDER, insertcolor=C_TEXT)
    style.map("TEntry",              fieldbackground=[("readonly", C_BORDER)])
    style.configure("TCombobox",     fieldbackground=C_PANEL, foreground=C_TEXT,
                                     arrowcolor=C_TEXT, bordercolor=C_BORDER)
    style.map("TCombobox",           fieldbackground=[("readonly", C_PANEL)])
    style.configure("TButton",
        background=C_ACCENT, foreground=C_BG,
        bordercolor=C_ACCENT, focuscolor=C_ACCENT,
        font=("Segoe UI", _scaled(9), "bold"), padding=(8, 4),
    )
    style.map("TButton",
        background=[("active", C_ACCENT2), ("disabled", C_BORDER)],
        foreground=[("disabled", C_DIM)],
    )
    style.configure("Dim.TButton",    background=C_BORDER, foreground=C_TEXT, bordercolor=C_BORDER)
    style.map("Dim.TButton",          background=[("active", C_PANEL)])
    style.configure("Danger.TButton", background=C_ERR, foreground=C_BG)
    style.map("Danger.TButton",       background=[("active", "#e06c75")])
    style.configure("OK.TButton",     background=C_OK,  foreground=C_BG)
    style.map("OK.TButton",           background=[("active", "#7ec87a")])
    style.configure("TNotebook",      background=C_BG, tabmargins=[2, 4, 0, 0])
    style.configure("TNotebook.Tab",  background=C_PANEL, foreground=C_DIM,
                                      padding=[12, 5], font=("Segoe UI", _scaled(9)))
    style.map("TNotebook.Tab",
        background=[("selected", C_BG)],
        foreground=[("selected", C_ACCENT)],
    )
    style.configure("TLabelframe",       background=C_BG,  bordercolor=C_BORDER)
    style.configure("TLabelframe.Label", background=C_BG,  foreground=C_ACCENT,
                                         font=("Segoe UI", _scaled(9), "bold"))
    style.configure("Treeview",
        background=C_PANEL, foreground=C_TEXT, fieldbackground=C_PANEL, rowheight=_scaled(26))
    style.configure("Treeview.Heading",
        background=C_BORDER, foreground=C_TEXT, font=("Segoe UI", _scaled(9), "bold"))
    style.map("Treeview",
        background=[("selected", C_ACCENT)], foreground=[("selected", C_BG)])
    style.configure("TScrollbar",    background=C_PANEL, troughcolor=C_BG, arrowcolor=C_DIM)
    style.configure("Dim.TLabel",    background=C_BG, foreground=C_DIM,  font=("Segoe UI", _scaled(9)))
    style.configure("Title.TLabel",  background=C_BG, foreground=C_TEXT, font=("Segoe UI", _scaled(15), "bold"))
    style.configure("OK.TLabel",     background=C_BG, foreground=C_OK)
    style.configure("Error.TLabel",  background=C_BG, foreground=C_ERR)
    style.configure("Warn.TLabel",   background=C_BG, foreground=C_WARN)
    return style


def _labelled_entry(parent, row: int, label: str, var: tk.Variable,
                    width: int = 50, hint: str = "") -> ttk.Entry:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 10), pady=4)
    ent = ttk.Entry(parent, textvariable=var, width=width)
    ent.grid(row=row, column=1, sticky=tk.EW, pady=4)
    if hint:
        ttk.Label(parent, text=hint, style="Dim.TLabel", wraplength=400).grid(
            row=row + 1, column=1, sticky=tk.W, pady=(0, 2))
    return ent


def _window_center(win: object, w: int, h: int):
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")


# ═══════════════════════════════════════════════════════════════════════════════
#  COLOR PICKER WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
#  CUSTOM COLOR PICKER DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class ColorPickerButton(tk.Frame):
    """Color swatch button that opens the native Windows color picker.
    Shows a row of up to 8 recently-used colors that persist in config.
    """
    _NONE_BG   = "#3a3a4a"
    MAX_RECENT = 8

    def __init__(self, parent, initial_color=None,
                 custom_colors=None, on_custom_save=None, **kw):
        super().__init__(parent, bg=C_BG, **kw)
        self._color          = initial_color
        # custom_colors is a shared list of recent ints (may contain None)
        self._recent         = [c for c in (custom_colors or []) if c is not None]
        self._on_save        = on_custom_save   # callback(list[int])
        self._recent_btns    = []

        # ── Top row: current swatch + hex label + clear ──────────────────────
        top = tk.Frame(self, bg=C_BG)
        top.pack(side=tk.TOP, anchor=tk.W)
        self._swatch = tk.Label(top, width=3, relief=tk.FLAT, cursor="hand2")
        self._swatch.pack(side=tk.LEFT)
        self._swatch.bind("<Button-1>", self._pick)
        self._label = tk.Label(top, text="", bg=C_BG, fg=C_DIM,
                               font=("Consolas", _scaled(9)), cursor="hand2")
        self._label.pack(side=tk.LEFT, padx=(6, 0))
        self._label.bind("<Button-1>", self._pick)
        clear_btn = tk.Label(top, text="✕", bg=C_BG, fg=C_DIM,
                             font=("Segoe UI", _scaled(8)), cursor="hand2")
        clear_btn.pack(side=tk.LEFT, padx=(8, 0))
        clear_btn.bind("<Button-1>", self._clear)

        # ── Recent colors row ────────────────────────────────────────────────
        self._recent_row = tk.Frame(self, bg=C_BG)
        self._recent_row.pack(side=tk.TOP, anchor=tk.W, pady=(3, 0))
        self._rebuild_recent_row()
        self._refresh()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self):
        return self._color

    def set(self, value):
        self._color = value
        self._refresh()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _hex_str(self):
        return f"#{self._color:06x}" if self._color is not None else self._NONE_BG

    def _refresh(self):
        self._swatch.configure(bg=self._hex_str())
        if self._color is None:
            self._label.configure(text="No color", fg=C_DIM)
        else:
            self._label.configure(text=f"#{self._color:06X}", fg=C_TEXT)

    def _rebuild_recent_row(self):
        for w in self._recent_row.winfo_children():
            w.destroy()
        if not self._recent:
            ttk.Label(self._recent_row, text="Recent:",
                      style="Dim.TLabel").pack(side=tk.LEFT, padx=(0, 4))
            ttk.Label(self._recent_row, text="none yet — pick a color to add",
                      style="Dim.TLabel").pack(side=tk.LEFT)
            return
        ttk.Label(self._recent_row, text="Recent:",
                  style="Dim.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        for c in self._recent[:self.MAX_RECENT]:
            btn = tk.Label(self._recent_row, bg=f"#{c:06x}",
                           width=2, relief=tk.RAISED, cursor="hand2")
            btn.pack(side=tk.LEFT, padx=1, ipady=3)
            btn.bind("<Button-1>", lambda e, col=c: self._load_recent(col))
            btn.bind("<Enter>",    lambda e, col=c, b=btn: b.configure(relief=tk.SUNKEN))
            btn.bind("<Leave>",    lambda e, b=btn: b.configure(relief=tk.RAISED))

    def _load_recent(self, color):
        self._color = color
        self._refresh()

    def _add_to_recent(self, color):
        if color in self._recent:
            self._recent.remove(color)
        self._recent.insert(0, color)
        self._recent = self._recent[:self.MAX_RECENT]
        self._rebuild_recent_row()
        if self._on_save:
            self._on_save(list(self._recent))

    def _pick(self, _=None):
        initial = self._hex_str() if self._color is not None else None
        result  = colorchooser.askcolor(color=initial,
                                        title="Choose embed color", parent=self)
        if result and result[1]:
            self._color = int(result[1][1:], 16)
            self._add_to_recent(self._color)
            self._refresh()

    def _clear(self, _=None):
        self._color = None
        self._refresh()


# ═══════════════════════════════════════════════════════════════════════════════

class AvatarDropZone(tk.Canvas):
    W, H     = 340, 130
    THUMB_SZ = 84

    _IDLE_BORDER  = "#4a4a6a"
    _HOVER_BORDER = "#89b4fa"
    _IDLE_BG      = "#252535"
    _HOVER_BG     = "#2c2c48"
    _LOADED_BG    = "#1a2535"

    def __init__(self, parent,
                 on_change: Optional[Callable[[Optional[str]], None]] = None, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=self._IDLE_BG, highlightthickness=0, cursor="hand2", **kw)
        self._path:      Optional[str]                = None
        self._thumb_ref: Optional[ImageTk.PhotoImage] = None
        self._on_change  = on_change
        self._hovering   = False

        try:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>",      self._on_dnd_drop)
            self.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self.dnd_bind("<<DragLeave>>", self._on_drag_leave)
        except Exception:
            pass

        self.bind("<Button-1>",  self._on_click)
        self.bind("<Control-v>", self._on_paste)
        self.bind("<Control-V>", self._on_paste)
        self.bind("<Enter>", lambda _: self._set_hover(True))
        self.bind("<Leave>", lambda _: self._set_hover(False))
        # Grab keyboard focus on mouse enter so Ctrl+V works without clicking first
        self.bind("<Enter>", lambda _: (self._set_hover(True), self.focus_set()), add=True)
        self._redraw()

    def get_path(self) -> Optional[str]:
        return self._path

    def clear(self):
        self._path = None; self._thumb_ref = None; self._hovering = False
        self._redraw()
        if self._on_change:
            self._on_change(None)

    def _set_hover(self, state: bool):
        self._hovering = state
        if not self._path:
            self._redraw()

    def _redraw(self):
        if self._path: self._draw_loaded()
        else:          self._draw_idle()

    def _draw_idle(self):
        self.delete("all")
        bg     = self._HOVER_BG     if self._hovering else self._IDLE_BG
        border = self._HOVER_BORDER if self._hovering else self._IDLE_BORDER
        self.configure(bg=bg)
        self.create_rectangle(4, 4, self.W - 4, self.H - 4, outline=border, dash=(6, 4), width=2)
        cx = self.W // 2
        self.create_text(cx, 32,  text="⬆", font=("Segoe UI", _scaled(20)), fill=border, anchor=tk.CENTER)
        self.create_text(cx, 62,  text="Drop image here  or  click to browse",
                         font=("Segoe UI", _scaled(9)), fill=C_TEXT, anchor=tk.CENTER)
        self.create_text(cx, 82,  text="Ctrl+V to paste from clipboard",
                         font=("Segoe UI", _scaled(8)), fill=C_DIM, anchor=tk.CENTER)
        self.create_text(cx, 100, text="PNG · JPG · GIF · WEBP",
                         font=("Segoe UI", _scaled(7)), fill=C_DIM, anchor=tk.CENTER)

    def _draw_loaded(self):
        self.delete("all")
        self.configure(bg=self._LOADED_BG)
        self.create_rectangle(4, 4, self.W - 4, self.H - 4, outline=C_ACCENT, width=2)
        if self._thumb_ref:
            self.create_image(10 + self.THUMB_SZ // 2, self.H // 2,
                              image=self._thumb_ref, anchor=tk.CENTER)
        fname = os.path.basename(self._path or "")
        if len(fname) > 26: fname = fname[:23] + "…"
        x = 10 + self.THUMB_SZ + 14; cy = self.H // 2
        self.create_text(x, cy - 18, text=fname,
                         font=("Segoe UI", _scaled(9), "bold"), fill=C_TEXT, anchor=tk.W)
        self.create_text(x, cy + 2,  text="✓  Image ready",
                         font=("Segoe UI", _scaled(8)), fill=C_OK, anchor=tk.W)
        self.create_text(x, cy + 20, text="Click  ✕  to remove",
                         font=("Segoe UI", _scaled(8)), fill=C_DIM, anchor=tk.W)
        self.create_text(self.W - 14, 14, text="✕",
                         font=("Segoe UI", _scaled(10), "bold"), fill=C_DIM,
                         tags="clear_btn", anchor=tk.CENTER)
        self.tag_bind("clear_btn", "<Button-1>", lambda _: self.clear())

    def _load_file(self, path: str):
        try:
            raw = Image.open(path).convert("RGBA")
            raw.thumbnail((self.THUMB_SZ, self.THUMB_SZ), Image.LANCZOS)
            canvas = Image.new("RGBA", (self.THUMB_SZ, self.THUMB_SZ), (26, 37, 53, 255))
            off = ((self.THUMB_SZ - raw.width) // 2, (self.THUMB_SZ - raw.height) // 2)
            canvas.paste(raw, off, raw)
            self._thumb_ref = ImageTk.PhotoImage(canvas)
        except Exception:
            self._thumb_ref = None
        self._path = path
        self._redraw()
        if self._on_change:
            self._on_change(path)

    def _load_pil_image(self, img: Image.Image):
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="gbank_avatar_")
            tmp.close()
            img.save(tmp.name, format="PNG")
            self._load_file(tmp.name)
        except Exception:
            pass

    def _on_click(self, _=None):
        if self._path: return
        path = filedialog.askopenfilename(parent=self, title="Select avatar image",
                                          filetypes=IMAGE_TYPES)
        if path: self._load_file(path)

    def _on_paste(self, _=None):
        try: obj = ImageGrab.grabclipboard()
        except Exception: return
        if obj is None: return
        if isinstance(obj, list):
            for p in obj:
                if os.path.splitext(p)[1].lower() in _IMG_EXTS:
                    self._load_file(p); return
        elif isinstance(obj, Image.Image):
            self._load_pil_image(obj)

    def _on_dnd_drop(self, event):
        self._set_hover(False)
        for p in self.tk.splitlist(event.data.strip()):
            p = p.strip()
            if os.path.splitext(p)[1].lower() in _IMG_EXTS or os.path.isfile(p):
                self._load_file(p); return

    def _on_drag_enter(self, _=None): self._set_hover(True)
    def _on_drag_leave(self, _=None): self._set_hover(False)


# ═══════════════════════════════════════════════════════════════════════════════
#  AVATAR SECTION
# ═══════════════════════════════════════════════════════════════════════════════

class AvatarSection(tk.Frame):
    """Avatar picker with file/URL mode, preview, and per-mode history (last 5)."""

    MAX_HISTORY = 5

    def __init__(self, parent,
                 avatar_mode:       str  = "file",
                 avatar_image_path: str  = "",
                 avatar_url:        str  = "",
                 file_history:      Optional[list] = None,
                 url_history:       Optional[list] = None,
                 on_change:         Optional[Callable] = None,
                 **kw):
        super().__init__(parent, bg=C_BG, **kw)
        self.columnconfigure(0, weight=1)

        self._on_change         = on_change   # (mode, path, url, file_hist, url_hist)
        self._get_webhook_url:  Callable[[], str] = lambda: ""
        self._apply_status      = tk.StringVar(value="")
        self._mode_var          = tk.StringVar(value=avatar_mode)
        self._file_path         = avatar_image_path
        self._url               = avatar_url
        self._file_history      = list(file_history or [])[:self.MAX_HISTORY]
        self._url_history       = list(url_history  or [])[:self.MAX_HISTORY]
        self._url_thumb_ref     = None

        self._build()
        # Preload saved image AFTER _build so _hist_combo exists
        if self._file_path and os.path.isfile(self._file_path):
            self._drop_zone._load_file(self._file_path)
        self._switch_mode_silent()   # show correct panel without firing callback

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Mode radio buttons
        mode_f = ttk.Frame(self)
        mode_f.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        ttk.Label(mode_f, text="Source:").pack(side=tk.LEFT, padx=(0, 12))
        for val, text in [("file", "Upload local file"), ("url", "Use URL")]:
            tk.Radiobutton(
                mode_f, text=text, variable=self._mode_var, value=val,
                bg=C_BG, fg=C_TEXT, activebackground=C_BG, activeforeground=C_ACCENT,
                selectcolor=C_PANEL, font=("Segoe UI", _scaled(10)),
                command=self._switch_mode,
            ).pack(side=tk.LEFT, padx=(0, 16))

        # ── File panel ────────────────────────────────────────────────────────
        self._file_panel = ttk.Frame(self)
        self._file_panel.columnconfigure(0, weight=1)
        self._drop_zone = AvatarDropZone(self._file_panel, on_change=self._on_drop_change)
        self._drop_zone.grid(row=0, column=0, sticky=tk.EW)

        # ── URL panel ─────────────────────────────────────────────────────────
        self._url_panel = ttk.Frame(self)
        self._url_panel.columnconfigure(0, weight=1)
        ur = ttk.Frame(self._url_panel)
        ur.grid(row=0, column=0, sticky=tk.EW)
        ur.columnconfigure(0, weight=1)
        self._url_var = tk.StringVar(value=self._url)
        self._url_entry = ttk.Entry(ur, textvariable=self._url_var)
        self._url_entry.grid(row=0, column=0, sticky=tk.EW, padx=(0, 6))
        ttk.Button(ur, text="Preview", command=self._fetch_url_preview).grid(row=0, column=1)
        ttk.Label(self._url_panel,
                  text="Direct image URL. Click Preview to verify and load thumbnail.",
                  style="Dim.TLabel", wraplength=380).grid(
            row=1, column=0, sticky=tk.W, pady=(4, 0))
        self._url_thumb_lbl = tk.Label(self._url_panel, bg=C_BG)
        self._url_thumb_lbl.grid(row=2, column=0, sticky=tk.W, pady=(6, 0))

        # ── History combobox ──────────────────────────────────────────────────
        hf = ttk.Frame(self)
        hf.grid(row=3, column=0, sticky=tk.EW, pady=(8, 0))
        hf.columnconfigure(1, weight=1)
        ttk.Label(hf, text="History:", style="Dim.TLabel").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8))
        self._hist_var   = tk.StringVar()
        self._hist_combo = ttk.Combobox(hf, textvariable=self._hist_var,
                                         state="readonly", width=36)
        self._hist_combo.grid(row=0, column=1, sticky=tk.EW)
        self._hist_combo.bind("<<ComboboxSelected>>", self._on_history_select)

        # ── Status ────────────────────────────────────────────────────────────
        ttk.Label(self,
                  text="File mode: image uploaded to webhook permanently.  "
                       "URL mode: URL embedded in each post.",
                  style="Dim.TLabel", wraplength=420).grid(
            row=4, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Label(self, textvariable=self._apply_status,
                  style="Dim.TLabel", wraplength=420).grid(
            row=5, column=0, sticky=tk.W, pady=(2, 0))

    # ── Panel switching ───────────────────────────────────────────────────────

    def _switch_mode_silent(self):
        """Switch panels without firing the change callback (used during init)."""
        mode = self._mode_var.get()
        self._file_panel.grid_remove()
        self._url_panel.grid_remove()
        if mode == "file":
            self._file_panel.grid(row=1, column=0, sticky=tk.EW, pady=(0, 4))
        else:
            self._url_panel.grid(row=1, column=0, sticky=tk.EW, pady=(0, 4))
        self._update_history_combo()

    def _switch_mode(self):
        self._switch_mode_silent()
        self._fire_change()

    def _update_history_combo(self):
        mode = self._mode_var.get()
        hist = self._file_history if mode == "file" else self._url_history
        self._hist_combo["values"] = hist
        self._hist_var.set("")

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_drop_change(self, path: Optional[str]):
        if path:
            self._file_path = path
            if path in self._file_history:
                self._file_history.remove(path)
            self._file_history.insert(0, path)
            self._file_history = self._file_history[:self.MAX_HISTORY]
            self._update_history_combo()
        self._fire_change()

    def _fetch_url_preview(self):
        url = self._url_var.get().strip()
        if not url:
            return
        self._url = url
        if url in self._url_history:
            self._url_history.remove(url)
        self._url_history.insert(0, url)
        self._url_history = self._url_history[:self.MAX_HISTORY]
        self._update_history_combo()
        self._apply_status.set("Fetching preview…")
        def _run():
            try:
                import urllib.request as _ur
                req = _ur.Request(url, headers={"User-Agent": "GBankPoster/2.0"})
                with _ur.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                from PIL import Image as _Img, ImageTk as _ITk
                img = _Img.open(_io_module.BytesIO(data)).convert("RGBA")
                img.thumbnail((84, 84), _Img.LANCZOS)
                ref = _ITk.PhotoImage(img)
                def _show():
                    self._url_thumb_ref = ref
                    self._url_thumb_lbl.configure(image=ref, text="")
                    self._apply_status.set("✓  Preview loaded")
                self.after(0, _show)
            except Exception as exc:
                self.after(0, lambda: self._apply_status.set(f"✗  {exc}"))
        threading.Thread(target=_run, daemon=True).start()
        self._fire_change()

    def _on_history_select(self, _=None):
        val = self._hist_var.get()
        if not val:
            return
        mode = self._mode_var.get()
        if mode == "file":
            if os.path.isfile(val):
                self._drop_zone._load_file(val)
        else:
            self._url_var.set(val)
            self._url = val
            self._fetch_url_preview()
        self._hist_combo.selection_clear()

    def _fire_change(self):
        if self._on_change:
            self._on_change(
                self._mode_var.get(),
                self._drop_zone.get_path() or "",
                self._url_var.get().strip(),
                list(self._file_history),
                list(self._url_history),
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def get_mode(self) -> str:
        return self._mode_var.get()

    def get_url(self) -> str:
        return self._url_var.get().strip()

    def get_image_path(self) -> str:
        return self._drop_zone.get_path() or ""

    def set_webhook_url_provider(self, provider: Callable[[], str]):
        self._get_webhook_url = provider

    def apply_if_needed(self, on_done: Callable[[bool], None] = lambda ok: None):
        """Upload local file to webhook (file mode only). URL mode needs no upload."""
        mode = self._mode_var.get()
        if mode == "url":
            on_done(True); return
        path = self._drop_zone.get_path()
        if not path or not os.path.isfile(path):
            on_done(True); return
        webhook_url = self._get_webhook_url()
        if not webhook_url:
            on_done(True); return
        self._apply_status.set("Uploading avatar…")
        def _run():
            try:
                core.patch_webhook_avatar(webhook_url, path)
                self.after(0, lambda: self._apply_status.set("✓  Avatar uploaded!"))
                self.after(0, lambda: on_done(True))
            except Exception as exc:
                self.after(0, lambda: self._apply_status.set(f"✗  {exc}"))
                self.after(0, lambda: on_done(False))
        threading.Thread(target=_run, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
#  WINDOWS STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

def _startup_key():
    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_ALL_ACCESS,
    )


def get_startup_enabled() -> bool:
    try:
        with _startup_key() as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def set_startup_enabled(enable: bool) -> None:
    try:
        with _startup_key() as k:
            if enable:
                exe = sys.executable if not getattr(sys, "frozen", False) \
                    else os.path.abspath(sys.argv[0])
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception as exc:
        print(f"Could not modify startup registry: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
#  SETUP WIZARD
# ═══════════════════════════════════════════════════════════════════════════════

class SetupWizard(tk.Toplevel):
    STEPS = ["Welcome", "Install Addon", "Webhook", "Avatar", "Preferences", "Done"]

    def __init__(self, parent: tk.Tk, config: dict,
                 on_complete: Callable[[dict], None]):
        super().__init__(parent)
        self.withdraw()
        self.title("GBank Poster — Setup")
        self.configure(bg=C_BG)
        self.resizable(True, True)
        self.minsize(600, 520)
        _apply_theme(self)
        _window_center(self, 660, 580)

        self._config          = config
        self._original_config = json.loads(json.dumps(config))  # snapshot for cancel
        self._on_complete     = on_complete
        self._page_idx        = 0

        self._sv_path_var    = tk.StringVar(value=config.get("savedvariables_path", ""))
        self._addon_path_var = tk.StringVar()
        self._wh_url_var     = tk.StringVar(value=config.get("webhook_url", ""))
        self._startup_var    = tk.BooleanVar(value=get_startup_enabled())
        self._notify_var     = tk.BooleanVar(value=config.get("notifications", True))
        self._addon_status   = tk.StringVar(value="")
        self._wh_status      = tk.StringVar(value="")
        self._avatar_status  = tk.StringVar(value="")
        self._avatar_drop:   Optional[AvatarDropZone] = None

        self._build_chrome()
        self._show_page(0)
        self.deiconify()
        self.lift()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_chrome(self):
        banner = tk.Frame(self, bg=C_PANEL, height=72)
        banner.pack(fill=tk.X)
        banner.pack_propagate(False)
        tk.Label(banner, text="⚔  GBank Poster Setup",
                 bg=C_PANEL, fg=C_TEXT,
                 font=("Segoe UI", _scaled(14), "bold")).pack(side=tk.LEFT, padx=20, pady=16)
        self._step_lbl = tk.Label(banner, text="", bg=C_PANEL, fg=C_DIM,
                                  font=("Segoe UI", _scaled(9)))
        self._step_lbl.pack(side=tk.RIGHT, padx=20)

        bar = tk.Frame(self, bg=C_BORDER, height=3)
        bar.pack(fill=tk.X)
        self._progress_bar = tk.Frame(bar, bg=C_ACCENT, height=3)
        self._progress_bar.place(x=0, y=0, relheight=1.0, relwidth=0.0)

        self._content = tk.Frame(self, bg=C_BG)
        self._content.pack(fill=tk.BOTH, expand=True, padx=28, pady=20)

        foot = tk.Frame(self, bg=C_BG)
        foot.pack(fill=tk.X, padx=28, pady=(0, 16))
        self._back_btn = ttk.Button(foot, text="← Back", style="Dim.TButton",
                                    command=self._prev_page)
        self._back_btn.pack(side=tk.LEFT)
        self._next_btn = ttk.Button(foot, text="Next →", command=self._next_page)
        self._next_btn.pack(side=tk.RIGHT)
        self._skip_btn = ttk.Button(foot, text="Skip", style="Dim.TButton",
                                    command=self._skip)
        self._skip_btn.pack(side=tk.RIGHT, padx=(0, 8))

    def _show_page(self, idx: int):
        self._page_idx = idx
        for w in self._content.winfo_children():
            w.destroy()
        total = len(self.STEPS)
        self._step_lbl.configure(text=f"Step {idx + 1} of {total}")
        self._progress_bar.place(relwidth=(idx + 1) / total)
        self._back_btn.configure(state=tk.NORMAL if idx > 0 else tk.DISABLED)
        if idx in (0, total - 1):
            self._skip_btn.pack_forget()
        else:
            self._skip_btn.pack(side=tk.RIGHT, padx=(0, 8))
        if idx == total - 1:
            self._next_btn.configure(text="Finish ✓", style="OK.TButton")
        else:
            self._next_btn.configure(text="Next →", style="TButton")
        [self._page_welcome, self._page_addon, self._page_webhook,
         self._page_avatar,  self._page_prefs, self._page_done][idx]()

    def _prev_page(self):
        if self._page_idx > 0:
            self._show_page(self._page_idx - 1)

    def _next_page(self):
        if not self._validate_current(): return
        if self._page_idx == 1:
            self._run_install_on_next(); return
        if self._page_idx == 3:
            self._run_avatar_on_next(); return
        if self._page_idx < len(self.STEPS) - 1:
            self._show_page(self._page_idx + 1)
        else:
            self._finish()

    def _skip(self):
        if self._page_idx < len(self.STEPS) - 1:
            self._show_page(self._page_idx + 1)

    def _validate_current(self) -> bool:
        if self._page_idx == 2:
            url = self._wh_url_var.get().strip()
            if not url:
                self._wh_status.set("⚠  Webhook URL is required."); return False
            if not url.startswith("https://discord.com/api/webhooks/"):
                self._wh_status.set("⚠  That doesn't look like a Discord webhook URL."); return False
        return True

    def _on_close(self):
        # User closed without finishing — restore original config so wizard
        # shows again next launch and no partial state is saved
        core.save_config(CONFIG, self._original_config)
        self.destroy()
        self._on_complete(self._original_config)

    def _run_install_on_next(self):
        path = self._addon_path_var.get().strip()
        if not path:
            self._show_page(self._page_idx + 1); return
        self._addon_status.set("Installing…")
        self._next_btn.configure(state=tk.DISABLED)
        self.update()
        def _run():
            ok, msg = core.install_addon(path)
            def _done():
                self._next_btn.configure(state=tk.NORMAL)
                if ok:
                    self._derive_sv_path(path, silent=True)
                    self._show_page(self._page_idx + 1)
                else:
                    self._addon_status.set(f"✗  {msg}  (use Browse to locate folder, or Skip)")
            self.after(0, _done)
        threading.Thread(target=_run, daemon=True).start()

    def _run_avatar_on_next(self):
        path = self._avatar_drop.get_path() if self._avatar_drop else None
        url  = self._wh_url_var.get().strip()
        if not path or not url:
            self._show_page(self._page_idx + 1); return
        self._avatar_status.set("Applying avatar…")
        self._next_btn.configure(state=tk.DISABLED)
        self.update()
        def _run():
            try:
                core.patch_webhook_avatar(url, path)
                def _ok():
                    self._next_btn.configure(state=tk.NORMAL)
                    self._avatar_status.set("")
                    self._show_page(self._page_idx + 1)
                self.after(0, _ok)
            except Exception as exc:
                def _err():
                    self._next_btn.configure(state=tk.NORMAL)
                    self._avatar_status.set(f"✗  {exc}  — click Next again to skip")
                self.after(0, _err)
        threading.Thread(target=_run, daemon=True).start()

    def _page_welcome(self):
        f = self._content
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text="Welcome!", style="Title.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 12))
        txt = tk.Text(f, bg=C_BG, fg=C_TEXT, font=("Segoe UI", _scaled(10)),
                      wrap=tk.WORD, relief=tk.FLAT, height=10,
                      borderwidth=0, state=tk.NORMAL, cursor="arrow")
        txt.insert("1.0",
            "GBank Poster runs quietly in your system tray and automatically posts "
            "your WoW Classic inventory & bank to Discord whenever you run "
            "/gbankexport reload in-game.\n\n"
            "This wizard takes about 2 minutes. You'll need:\n"
            "  •  The WoW addon installed (we handle this for you)\n"
            "  •  A Discord Webhook URL for the channel you want to post to\n\n"
            "That's it — the app figures out everything else automatically.\n\n"
            "You can adjust any settings later by right-clicking the tray icon "
            "and choosing Open Settings.")
        txt.configure(state=tk.DISABLED)
        txt.grid(row=1, column=0, sticky=tk.EW)

    def _page_addon(self):
        f = self._content
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text="Install the WoW Addon", style="Title.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 8))
        ttk.Label(f, wraplength=560, text=(
            "The GBankExporter addon needs to be in your WoW AddOns folder. "
            "Select the path below, then click Next to install automatically. "
            "Or skip if you've already installed it."
        ), style="Dim.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(0, 14))

        lf = ttk.LabelFrame(f, text="WoW AddOns Folder", padding=10)
        lf.grid(row=2, column=0, sticky=tk.EW, pady=(0, 10))
        lf.columnconfigure(0, weight=1)
        ttk.Entry(lf, textvariable=self._addon_path_var, state="readonly").grid(
            row=0, column=0, sticky=tk.EW, padx=(0, 6))
        br = ttk.Frame(lf)
        br.grid(row=0, column=1)
        ttk.Button(br, text="Auto-Detect",
                   command=self._addon_auto_detect).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(br, text="Browse", command=self._addon_browse).pack(side=tk.LEFT)

        ttk.Label(f, textvariable=self._addon_status,
                  style="Dim.TLabel", wraplength=560).grid(row=3, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Label(f, text="Click Next → to install automatically.",
                  style="Dim.TLabel").grid(row=4, column=0, sticky=tk.W, pady=(2, 0))
        self._addon_auto_detect(silent=True)

    def _addon_auto_detect(self, silent: bool = False):
        if not silent:
            self._addon_status.set("Searching…")
            self.update()
        paths = core.find_addon_install_paths()
        if not paths:
            if not silent:
                self._addon_status.set("⚠  No WoW AddOns folder found. Browse manually.")
            return
        if len(paths) == 1:
            self._set_addon_path(paths[0], silent=silent)
        else:
            self._show_list_picker(paths, "Select AddOns Folder",
                                   callback=lambda p: self._set_addon_path(p))

    def _set_addon_path(self, path: str, silent: bool = False):
        self._addon_path_var.set(path)
        self._derive_sv_path(path, silent=silent)

    def _derive_sv_path(self, addons_path: str, silent: bool = False):
        candidates = core.derive_savedvariables_from_addons_path(addons_path)
        if not candidates:
            if not silent:
                self._addon_status.set(
                    "✓  Addon folder found. Launch WoW and log in at least once, "
                    "then the SavedVariables path will be detected automatically.")
            return
        existing = [p for p in candidates if os.path.isfile(p)]
        chosen   = existing[0] if existing else candidates[0]
        self._sv_path_var.set(chosen)
        if not silent:
            if os.path.isfile(chosen):
                self._addon_status.set("✓  Addon installed — SavedVariables path detected.")
            else:
                self._addon_status.set(
                    "✓  Addon installed — SavedVariables path ready. "
                    "It will appear after your first /gbankexport reload in WoW.")

    def _addon_browse(self):
        path = filedialog.askdirectory(parent=self, title="Select WoW Interface\\AddOns folder")
        if path: self._set_addon_path(path)

    def _page_webhook(self):
        f = self._content
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text="Discord Webhook", style="Title.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 4))
        ttk.Label(f, wraplength=560, text=(
            "In Discord: Server Settings → Integrations → Webhooks → New Webhook → Copy URL."
        ), style="Dim.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(0, 12))

        lf = ttk.LabelFrame(f, text="Webhook Settings", padding=12)
        lf.grid(row=2, column=0, sticky=tk.EW)
        lf.columnconfigure(1, weight=1)
        _labelled_entry(lf, 0, "Webhook URL *", self._wh_url_var)

        br = ttk.Frame(f)
        br.grid(row=3, column=0, sticky=tk.E, pady=(8, 0))
        ttk.Button(br, text="Send Test Message",
                   command=self._test_webhook).pack(side=tk.LEFT)
        ttk.Label(br, textvariable=self._wh_status,
                  style="Dim.TLabel").pack(side=tk.LEFT, padx=(10, 0))

    def _test_webhook(self):
        url = self._wh_url_var.get().strip()
        if not url:
            self._wh_status.set("Enter a URL first."); return
        self._wh_status.set("Sending…")
        self.update()
        def _run():
            try:
                core._post(url, {
                    "username": "Guild Bank",
                    "embeds": [{"title": "GBank Poster — Connection Test",
                                "description": "✅  Webhook is working correctly!",
                                "color": 0x89b4fa,
                                "footer": {"text": "Sent from GBank Poster Setup Wizard"}}],
                })
                self.after(0, lambda: self._wh_status.set("✓  Test message sent!"))
            except Exception as exc:
                self.after(0, lambda: self._wh_status.set(f"✗  {exc}"))
        threading.Thread(target=_run, daemon=True).start()

    def _page_avatar(self):
        f = self._content
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text="Webhook Avatar", style="Title.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 4))
        ttk.Label(f, wraplength=560, text=(
            "Optional: set an image for your Discord webhook. "
            "Drop a file below, click to browse, or press Ctrl+V to paste. "
            "Click Next to upload it — or Skip if you want to do this later."
        ), style="Dim.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(0, 12))

        lf = ttk.LabelFrame(f, text="Avatar Image  (resized to 512×512 before upload)", padding=12)
        lf.grid(row=2, column=0, sticky=tk.EW)
        lf.columnconfigure(0, weight=1)
        self._avatar_drop = AvatarDropZone(lf)
        self._avatar_drop.grid(row=0, column=0, sticky=tk.EW)

        ttk.Label(f, textvariable=self._avatar_status,
                  style="Dim.TLabel", wraplength=560).grid(row=3, column=0, sticky=tk.W, pady=(8, 0))

    def _page_prefs(self):
        f = self._content
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text="Preferences", style="Title.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 16))
        lf = ttk.LabelFrame(f, text="Startup & Notifications", padding=12)
        lf.grid(row=1, column=0, sticky=tk.EW)
        _styled_check(lf, text="Start GBank Poster automatically with Windows",
                      variable=self._startup_var).grid(row=0, column=0, sticky=tk.W, pady=(0, 2))
        ttk.Label(lf, text="Adds an entry to your Windows startup registry.",
                  style="Dim.TLabel").grid(row=1, column=0, sticky=tk.W, padx=(22, 0), pady=(0, 10))
        _styled_check(lf, text="Show a tray notification when a post succeeds",
                      variable=self._notify_var).grid(row=2, column=0, sticky=tk.W, pady=(0, 2))
        ttk.Label(lf, text="A small balloon popup in the taskbar corner.",
                  style="Dim.TLabel").grid(row=3, column=0, sticky=tk.W, padx=(22, 0))

    def _page_done(self):
        f = self._content
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text="All set! 🎉", style="Title.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 12))
        ttk.Label(f, wraplength=560, text=(
            "GBank Poster is running in your system tray. "
            "Go into WoW, open your bank, and run the command below."
        )).grid(row=1, column=0, sticky=tk.W, pady=(0, 10))

        cmd_frame = ttk.LabelFrame(f, text="In-Game Command  (select all and copy)", padding=10)
        cmd_frame.grid(row=2, column=0, sticky=tk.EW, pady=(0, 12))
        cmd_frame.columnconfigure(0, weight=1)
        cmd_box = tk.Text(cmd_frame, height=1, bg=C_PANEL, fg=C_ACCENT,
                          font=("Consolas", _scaled(13), "bold"), relief=tk.FLAT, borderwidth=0,
                          insertbackground=C_ACCENT,
                          selectbackground=C_ACCENT, selectforeground=C_BG)
        cmd_box.insert("1.0", "/gbankexport reload")
        cmd_box.configure(state=tk.NORMAL)
        cmd_box.grid(row=0, column=0, sticky=tk.EW)
        ttk.Label(cmd_frame, text="Ctrl+A to select all, Ctrl+C to copy, then paste into WoW chat.",
                  style="Dim.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))

        ttk.Label(f, wraplength=560, text=(
            "The app detects the file the moment WoW writes it and posts to Discord automatically. "
            "Right-click the tray icon → Open Settings to customise per-character "
            "embed titles, colors, and avatars."
        ), style="Dim.TLabel").grid(row=3, column=0, sticky=tk.W)

    def _show_list_picker(self, items: list[str], title: str,
                          callback: Optional[Callable[[str], None]] = None,
                          target: Optional[tk.StringVar] = None):
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=C_BG)
        _window_center(win, 640, 210)
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        ttk.Label(win, text="Multiple options found — select one:").pack(
            padx=16, pady=(12, 4), anchor=tk.W)
        lb = tk.Listbox(win, bg=C_PANEL, fg=C_TEXT,
                        selectbackground=C_ACCENT, selectforeground=C_BG,
                        font=("Consolas", _scaled(9)), relief=tk.FLAT, height=5)
        lb.pack(padx=16, fill=tk.X)
        for p in items: lb.insert(tk.END, p)
        lb.selection_set(0)
        def _ok():
            sel = lb.curselection()
            if sel:
                chosen = items[sel[0]]
                if target:   target.set(chosen)
                if callback: callback(chosen)
            win.destroy()
        ttk.Button(win, text="Select", command=_ok).pack(pady=8)

    def _finish(self, cancelled: bool = False):
        if not cancelled:
            self._config["savedvariables_path"] = self._sv_path_var.get().strip()
            self._config["webhook_url"]          = self._wh_url_var.get().strip()
            self._config["notifications"]        = self._notify_var.get()
            self._config["setup_complete"]       = True
            set_startup_enabled(self._startup_var.get())
            core.save_config(CONFIG, self._config)
        self.destroy()
        self._on_complete(self._config)


# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Tk, config: dict, state: dict,
                 on_save: Callable[[dict], None]):
        super().__init__(parent)
        self.withdraw()
        self.title("GBank Poster — Settings")
        self.configure(bg=C_BG)
        self.resizable(True, True)
        self.minsize(640, 500)
        _apply_theme(self)
        _window_center(self, 720, 600)

        self._config  = config
        self._state   = state
        self._on_save = on_save

        self._sv_path_var    = tk.StringVar(value=config.get("savedvariables_path", ""))
        self._wh_url_var     = tk.StringVar(value=config.get("webhook_url", ""))
        self._startup_var    = tk.BooleanVar(value=get_startup_enabled())
        self._notify_var     = tk.BooleanVar(value=config.get("notifications", True))
        self._addon_status   = tk.StringVar(value="")
        self._addon_path_var = tk.StringVar()

        self._wh_tab_selection:  Optional[str]               = config.get("last_webhook_tab")
        self._wh_avatar_section: Optional[AvatarSection]     = None
        self._wh_char_color:     Optional[ColorPickerButton] = None
        # Shared custom color slots for the color picker (10 slots, persisted in config)
        self._custom_colors: list = list(config.get("custom_colors", [None] * 10))
        while len(self._custom_colors) < 10:
            self._custom_colors.append(None)

        self._build()
        self.deiconify()
        self.lift()
        self.focus_force()
        self.bind("<Control-v>", self._on_window_paste)
        self.bind("<Control-V>", self._on_window_paste)

    def _build(self):
        hdr = tk.Frame(self, bg=C_PANEL, height=50)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚔  GBank Poster Settings",
                 bg=C_PANEL, fg=C_TEXT,
                 font=("Segoe UI", _scaled(12), "bold")).pack(side=tk.LEFT, padx=16, pady=10)

        # Footer packed FIRST so it's never squeezed out when the window shrinks
        foot = ttk.Frame(self)
        foot.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(0, 12))
        ttk.Button(foot, text="Save & Apply", command=self._save).pack(side=tk.RIGHT)
        ttk.Button(foot, text="Close", style="Dim.TButton",
                   command=self.destroy).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Sizegrip(self).place(relx=1.0, rely=1.0, anchor=tk.SE)

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self._build_general(nb)
        self._build_webhooks(nb)
        self._build_log(nb)
        self._build_help(nb)

    # ── General tab ───────────────────────────────────────────────────────────

    def _build_general(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text="  General  ")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, bg=C_BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky=tk.NSEW)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        vsb.grid(row=0, column=1, sticky=tk.NS)
        canvas.configure(yscrollcommand=vsb.set)

        inner = ttk.Frame(canvas, padding=16)
        inner.columnconfigure(0, weight=1)
        win_id = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        def _on_inner_configure(_):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(event):
            canvas.itemconfig(win_id, width=event.width)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _bind_mw(_):   canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_mw(_): canvas.unbind_all("<MouseWheel>")
        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<Enter>", _bind_mw)
        canvas.bind("<Leave>", _unbind_mw)
        inner.bind("<Enter>", _bind_mw)
        inner.bind("<Leave>", _unbind_mw)

        tab = inner

        lf = ttk.LabelFrame(tab, text="SavedVariables File", padding=10)
        lf.grid(row=0, column=0, sticky=tk.EW, pady=(0, 12))
        lf.columnconfigure(0, weight=1)
        ttk.Entry(lf, textvariable=self._sv_path_var,
                  state="readonly").grid(row=0, column=0, sticky=tk.EW, padx=(0, 6))
        br = ttk.Frame(lf)
        br.grid(row=0, column=1)
        ttk.Button(br, text="Re-Detect",
                   command=self._sv_re_detect).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(br, text="Browse",
                   command=self._sv_browse).pack(side=tk.LEFT)
        ttk.Label(lf, text="Set automatically from the AddOns folder below.",
                  style="Dim.TLabel").grid(row=1, column=0, columnspan=2,
                                           sticky=tk.W, pady=(4, 0))

        af = ttk.LabelFrame(tab, text="WoW Addon", padding=10)
        af.grid(row=1, column=0, sticky=tk.EW, pady=(0, 12))
        af.columnconfigure(0, weight=1)
        ttk.Entry(af, textvariable=self._addon_path_var,
                  state="readonly").grid(row=0, column=0, sticky=tk.EW, padx=(0, 6))
        abr = ttk.Frame(af)
        abr.grid(row=0, column=1)
        ttk.Button(abr, text="Auto-Detect",
                   command=self._addon_auto_detect).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(abr, text="Browse",
                   command=self._addon_browse).pack(side=tk.LEFT)
        ttk.Button(af, text="Install / Reinstall Addon",
                   command=self._do_install_addon).grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Label(af, textvariable=self._addon_status,
                  style="Dim.TLabel").grid(row=2, column=0, columnspan=2,
                                           sticky=tk.W, pady=(4, 0))
        self._addon_auto_detect(silent=True)

        wf = ttk.LabelFrame(tab, text="Webhook", padding=10)
        wf.grid(row=2, column=0, sticky=tk.EW, pady=(0, 12))
        wf.columnconfigure(1, weight=1)
        _labelled_entry(wf, 0, "Webhook URL:", self._wh_url_var,
                        hint="Shared URL used by all characters. "
                             "Individual characters can override this in the Webhooks tab.")

        pf = ttk.LabelFrame(tab, text="Preferences", padding=10)
        pf.grid(row=3, column=0, sticky=tk.EW)
        _styled_check(pf, text="Start GBank Poster automatically with Windows",
                      variable=self._startup_var).pack(anchor=tk.W, pady=4)
        _styled_check(pf, text="Show tray notification when a post succeeds",
                      variable=self._notify_var).pack(anchor=tk.W, pady=4)

    def _sv_re_detect(self):
        addons = self._addon_path_var.get().strip()
        if addons:
            candidates = core.derive_savedvariables_from_addons_path(addons)
            if candidates:
                existing = [p for p in candidates if os.path.isfile(p)]
                self._sv_path_var.set(existing[0] if existing else candidates[0])
                return
        paths = core.find_savedvariables_paths()
        if paths:
            self._sv_path_var.set(paths[0])
        else:
            messagebox.showinfo("Not Found",
                "SavedVariables file not found yet.\n\n"
                "Run  /gbankexport reload  in WoW, then click Re-Detect.",
                parent=self)

    def _sv_browse(self):
        path = filedialog.askopenfilename(
            parent=self, title="Select GBankExporter.lua",
            filetypes=[("Lua Files", "*.lua"), ("All Files", "*.*")])
        if path: self._sv_path_var.set(path)

    def _addon_auto_detect(self, silent: bool = False):
        paths = core.find_addon_install_paths()
        if not paths:
            if not silent:
                self._addon_status.set("⚠  No WoW AddOns folder found. Browse manually.")
            return
        if silent:
            preferred = next((p for p in paths if "_classic_era_" in p), paths[0])
            self._addon_path_var.set(preferred)
            return
        if len(paths) == 1:
            self._addon_path_var.set(paths[0])
            self._addon_status.set(
                f"✓  {'Already installed at' if core.is_addon_installed(paths[0]) else 'Found:'} "
                f"{paths[0]}")
        else:
            self._show_picker(paths, self._addon_path_var)

    def _addon_browse(self):
        path = filedialog.askdirectory(parent=self, title="Select WoW Interface\\AddOns folder")
        if path: self._addon_path_var.set(path)

    def _do_install_addon(self):
        path = self._addon_path_var.get().strip()
        if not path:
            self._addon_status.set("⚠  Select an AddOns folder first."); return
        self._addon_status.set("Installing…")
        self.update()
        ok, msg = core.install_addon(path)
        if ok:
            candidates = core.derive_savedvariables_from_addons_path(path)
            if candidates:
                existing = [p for p in candidates if os.path.isfile(p)]
                self._sv_path_var.set(existing[0] if existing else candidates[0])
        self._addon_status.set(("✓  " if ok else "✗  ") + msg)

    # ── Webhooks tab ──────────────────────────────────────────────────────────

    def _build_webhooks(self, nb):
        tab = ttk.Frame(nb, padding=16)
        nb.add(tab, text="  Webhooks  ")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        sel_row = ttk.Frame(tab)
        sel_row.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))
        sel_row.columnconfigure(1, weight=1)
        ttk.Label(sel_row, text="Character:",
                  font=("Segoe UI", _scaled(10), "bold")).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 10))
        self._wh_dropdown_var = tk.StringVar()
        self._wh_dropdown = ttk.Combobox(sel_row, textvariable=self._wh_dropdown_var,
                                         state="readonly", width=36)
        self._wh_dropdown.grid(row=0, column=1, sticky=tk.W)
        self._wh_dropdown.bind("<<ComboboxSelected>>", self._on_wh_select)

        tk.Frame(tab, bg=C_BORDER, height=1).grid(row=0, column=0, sticky=tk.EW, pady=(38, 0))

        canvas = tk.Canvas(tab, bg=C_BG, highlightthickness=0)
        canvas.grid(row=1, column=0, sticky=tk.NSEW)
        vsb = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        vsb.grid(row=1, column=1, sticky=tk.NS)
        canvas.configure(yscrollcommand=vsb.set)

        self._wh_inner = tk.Frame(canvas, bg=C_BG)
        self._wh_inner.columnconfigure(0, weight=1)
        self._wh_canvas_window = canvas.create_window((0, 0), window=self._wh_inner, anchor=tk.NW)

        def _on_inner_configure(_):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(event):
            canvas.itemconfig(self._wh_canvas_window, width=event.width)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _bind_mw(_):   canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_mw(_): canvas.unbind_all("<MouseWheel>")

        self._wh_inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<Enter>", _bind_mw)
        canvas.bind("<Leave>", _unbind_mw)
        self._wh_inner.bind("<Enter>", _bind_mw)
        self._wh_inner.bind("<Leave>", _unbind_mw)

        self._wh_refresh_dropdown()

    def _wh_refresh_dropdown(self):
        entries    = []
        entry_keys = []

        sv = self._sv_path_var.get().strip()
        if sv and os.path.isfile(sv):
            try:
                for key in core.parse_savedvariables(sv):
                    entries.append(key)
                    entry_keys.append(key)
            except Exception:
                pass

        for key in self._config.get("characters", {}):
            if key not in entry_keys:
                entries.append(f"{key}  (not in file)")
                entry_keys.append(key)

        self._wh_dropdown["values"] = entries
        self._wh_dropdown_keys      = entry_keys

        if not entry_keys:
            self._wh_tab_selection = None
            for w in self._wh_inner.winfo_children():
                w.destroy()
            ttk.Label(self._wh_inner,
                      text="No characters found yet.\n\nRun /gbankexport reload in WoW, "
                           "then re-open Settings.",
                      style="Dim.TLabel", wraplength=400).pack(padx=16, pady=20)
            return

        cur = self._wh_tab_selection
        idx = entry_keys.index(cur) if cur in entry_keys else 0
        self._wh_dropdown.current(idx)
        self._wh_tab_selection = entry_keys[idx]
        self._render_wh_panel()

    def _on_wh_select(self, _=None):
        idx = self._wh_dropdown.current()
        if idx >= 0:
            self._wh_tab_selection = self._wh_dropdown_keys[idx]
            self._render_wh_panel()
            self._wh_dropdown.selection_clear()

    def _render_wh_panel(self):
        for w in self._wh_inner.winfo_children():
            w.destroy()
        self._wh_avatar_section = None
        self._wh_char_color     = None

        key = self._wh_tab_selection
        if not key: return
        f = self._wh_inner
        f.columnconfigure(1, weight=1)
        row = self._render_character_section(f, key, 0)

        tk.Frame(f, bg=C_BORDER, height=1).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=(12, 8))
        row += 1

        save_row = ttk.Frame(f)
        save_row.grid(row=row, column=0, columnspan=2, sticky=tk.EW)
        self._wh_save_status = tk.StringVar(value="")
        ttk.Button(save_row, text="Save",
                   command=self._save_wh_panel).pack(side=tk.LEFT)
        ttk.Label(save_row, textvariable=self._wh_save_status,
                  style="Dim.TLabel").pack(side=tk.LEFT, padx=(12, 0))

    def _render_character_section(self, f, key, row):
        cfg       = core.get_char_config(self._config, key)
        char_name = core.char_name_from_key(key)

        idf = ttk.LabelFrame(f, text="Identity", padding=12)
        idf.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=(4, 12))
        idf.columnconfigure(1, weight=1)
        self._char_enabled_var = tk.BooleanVar(value=cfg["enabled"])
        self._char_wh_name_var = tk.StringVar(value=cfg.get("username") or char_name)
        self._char_title_var   = tk.StringVar(value=cfg.get("embed_title") or char_name)
        self._char_wh_url_var  = tk.StringVar(value=cfg.get("webhook_url", ""))
        _styled_check(idf,
            text="Enabled — post this character's inventory to Discord",
            variable=self._char_enabled_var,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))
        _labelled_entry(idf, 1, "Display Name:", self._char_wh_name_var,
                        hint="Name shown in Discord above this character's post.")
        _labelled_entry(idf, 3, "Embed Title:",  self._char_title_var,
                        hint="Title of the embed.")
        _labelled_entry(idf, 5, "Webhook URL:",  self._char_wh_url_var,
                        hint="Leave blank to use the shared URL from Settings → General.")
        row += 1

        af = ttk.LabelFrame(f, text="Appearance", padding=12)
        af.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=(0, 12))
        af.columnconfigure(1, weight=1)
        ttk.Label(af, text="Embed Color:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10), pady=4)
        self._wh_char_color = ColorPickerButton(
            af, initial_color=cfg.get("embed_color"),
            custom_colors=self._custom_colors,
            on_custom_save=self._on_custom_colors_changed)
        self._wh_char_color.grid(row=0, column=1, sticky=tk.W, pady=4)
        ttk.Label(af, text="Avatar:",
                  font=("Segoe UI", _scaled(9), "bold")).grid(
            row=1, column=0, columnspan=2, sticky=tk.W, pady=(8, 4))
        char_key_ref = key
        def _on_avatar_change(mode, path, url, fhist, uhist):
            self._config.setdefault("characters", {}).setdefault(char_key_ref, {}).update({
                "avatar_mode":         mode,
                "avatar_image_path":   path,
                "avatar_url":          url,
                "avatar_file_history": fhist,
                "avatar_url_history":  uhist,
            })
            core.save_config(CONFIG, self._config)
        self._wh_avatar_section = AvatarSection(
            af,
            avatar_mode=cfg.get("avatar_mode", "file"),
            avatar_image_path=cfg.get("avatar_image_path", ""),
            avatar_url=cfg.get("avatar_url", ""),
            file_history=cfg.get("avatar_file_history", []),
            url_history=cfg.get("avatar_url_history", []),
            on_change=_on_avatar_change)
        self._wh_avatar_section.grid(row=2, column=0, columnspan=2, sticky=tk.EW)
        self._wh_avatar_section.set_webhook_url_provider(
            lambda: (self._char_wh_url_var.get().strip()
                     or self._config.get("webhook_url", "").strip()))
        row += 1
        return row

    def _save_wh_panel(self):
        key = self._wh_tab_selection
        if not key: return
        char_name = core.char_name_from_key(key)
        av = self._wh_avatar_section
        self._config.setdefault("characters", {})[key] = {
            "enabled":             self._char_enabled_var.get(),
            "username":            self._char_wh_name_var.get().strip() or char_name,
            "embed_title":         self._char_title_var.get().strip()   or char_name,
            "webhook_url":         self._char_wh_url_var.get().strip(),
            "embed_color":         self._wh_char_color.get() if self._wh_char_color else None,
            "avatar_mode":         av.get_mode()          if av else "file",
            "avatar_url":          av.get_url()           if av else "",
            "avatar_image_path":   av.get_image_path()    if av else "",
            "avatar_file_history": av._file_history       if av else [],
            "avatar_url_history":  av._url_history        if av else [],
        }
        self._config["last_webhook_tab"] = self._wh_tab_selection
        core.save_config(CONFIG, self._config)
        if self._wh_avatar_section:
            def _after_upload(ok):
                self._wh_save_status.set("✓  Saved" if ok else "✓  Saved (avatar upload failed)")
                self.after(3000, lambda: self._wh_save_status.set(""))
            self._wh_avatar_section.apply_if_needed(_after_upload)
        else:
            self._wh_save_status.set("✓  Saved")
            self.after(2000, lambda: self._wh_save_status.set(""))

    # ── Log tab ───────────────────────────────────────────────────────────────

    def _build_log(self, nb):
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="  Log  ")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self._log_box = scrolledtext.ScrolledText(
            tab, state=tk.DISABLED, wrap=tk.WORD,
            bg=C_PANEL, fg=C_TEXT, font=("Consolas", _scaled(9)),
            relief=tk.FLAT, borderwidth=0, padx=8, pady=6)
        self._log_box.grid(row=0, column=0, sticky=tk.NSEW)
        ttk.Button(tab, text="Clear", command=self._clear_log).grid(
            row=1, column=0, sticky=tk.E, pady=(6, 0))

    def append_log(self, msg: str):
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_box.configure(state=tk.NORMAL)
            self._log_box.insert(tk.END, f"[{ts}] {msg}\n")
            self._log_box.see(tk.END)
            self._log_box.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _clear_log(self):
        self._log_box.configure(state=tk.NORMAL)
        self._log_box.delete("1.0", tk.END)
        self._log_box.configure(state=tk.DISABLED)

    # ── Help tab ──────────────────────────────────────────────────────────────

    def _build_help(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text="  Help  ")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, bg=C_BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky=tk.NSEW)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        vsb.grid(row=0, column=1, sticky=tk.NS)
        canvas.configure(yscrollcommand=vsb.set)

        inner = tk.Frame(canvas, bg=C_BG)
        inner.columnconfigure(0, weight=1)
        win_id = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        def _on_cfg(_): canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_resize(e): canvas.itemconfig(win_id, width=e.width)
        def _on_mw(e): canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        def _bind_mw(_):   canvas.bind_all("<MouseWheel>", _on_mw)
        def _unbind_mw(_): canvas.unbind_all("<MouseWheel>")
        inner.bind("<Configure>", _on_cfg)
        canvas.bind("<Configure>", _on_resize)
        canvas.bind("<Enter>", _bind_mw)
        canvas.bind("<Leave>", _unbind_mw)
        inner.bind("<Enter>", _bind_mw)
        inner.bind("<Leave>", _unbind_mw)

        PAD = 18   # left/right page margin

        def hero():
            """Full-width hero banner at the top."""
            banner = tk.Frame(inner, bg=C_PANEL)
            banner.pack(fill=tk.X)
            tk.Frame(banner, bg=C_ACCENT, width=4).pack(side=tk.LEFT, fill=tk.Y)
            content = tk.Frame(banner, bg=C_PANEL)
            content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=16)
            tk.Label(content, text="⚔  GBank Poster", bg=C_PANEL, fg=C_TEXT,
                     font=("Segoe UI", _scaled(15), "bold")).pack(anchor=tk.W)
            tk.Label(content,
                     text="Watches your WoW SavedVariables and automatically posts your "
                          "guild bank inventory to Discord whenever you export in-game. "
                          "Runs silently in the system tray — set it up once and forget it.",
                     bg=C_PANEL, fg=C_DIM, font=("Segoe UI", _scaled(9)),
                     wraplength=520, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 0))

        def section(icon, title):
            """Section header with icon, bold title, and full-width rule."""
            wrapper = tk.Frame(inner, bg=C_BG)
            wrapper.pack(fill=tk.X, padx=PAD, pady=(20, 6))
            tk.Label(wrapper, text=f"{icon}  {title}", bg=C_BG, fg=C_ACCENT,
                     font=("Segoe UI", _scaled(10), "bold")).pack(side=tk.LEFT)
            tk.Frame(wrapper, bg=C_BORDER, height=1).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0), pady=1)

        def para(text):
            tk.Label(inner, text=text, bg=C_BG, fg=C_DIM,
                     font=("Segoe UI", _scaled(9)),
                     wraplength=600, justify=tk.LEFT).pack(
                anchor=tk.W, padx=PAD, pady=(0, 6))

        def cards(items):
            """Render a list of (label, desc) as a grid of cards with accent left bar."""
            grid = tk.Frame(inner, bg=C_BG)
            grid.pack(fill=tk.X, padx=PAD, pady=(0, 4))
            grid.columnconfigure(1, weight=1)
            for i, (label, desc) in enumerate(items):
                card = tk.Frame(grid, bg=C_PANEL)
                card.grid(row=i, column=0, columnspan=2, sticky=tk.EW,
                          pady=(0, 3))
                card.columnconfigure(1, weight=1)
                # Left accent bar
                tk.Frame(card, bg=C_ACCENT, width=3).grid(
                    row=0, column=0, sticky=tk.NS, rowspan=1)
                # Label
                tk.Label(card, text=label, bg=C_PANEL, fg=C_TEXT,
                         font=("Segoe UI", _scaled(9), "bold"),
                         anchor=tk.W, width=20).grid(
                    row=0, column=1, sticky=tk.W, padx=(10, 4), pady=7)
                # Description
                tk.Label(card, text=desc, bg=C_PANEL, fg=C_DIM,
                         font=("Segoe UI", _scaled(9)),
                         anchor=tk.W, justify=tk.LEFT, wraplength=440).grid(
                    row=0, column=2, sticky=tk.EW, padx=(0, 12), pady=7)

        def alert_cards(items):
            """Troubleshooting cards with warning-colored accent bar."""
            grid = tk.Frame(inner, bg=C_BG)
            grid.pack(fill=tk.X, padx=PAD, pady=(0, 4))
            grid.columnconfigure(1, weight=1)
            for i, (label, desc) in enumerate(items):
                card = tk.Frame(grid, bg=C_PANEL)
                card.grid(row=i, column=0, columnspan=2, sticky=tk.EW,
                          pady=(0, 3))
                card.columnconfigure(1, weight=1)
                tk.Frame(card, bg=C_WARN, width=3).grid(
                    row=0, column=0, sticky=tk.NS)
                tk.Label(card, text=label, bg=C_PANEL, fg=C_WARN,
                         font=("Segoe UI", _scaled(9), "bold"),
                         anchor=tk.W, width=22).grid(
                    row=0, column=1, sticky=tk.W, padx=(10, 4), pady=7)
                tk.Label(card, text=desc, bg=C_PANEL, fg=C_DIM,
                         font=("Segoe UI", _scaled(9)),
                         anchor=tk.W, justify=tk.LEFT, wraplength=420).grid(
                    row=0, column=2, sticky=tk.EW, padx=(0, 12), pady=7)

        # ── Hero ──────────────────────────────────────────────────────────────
        hero()

        # ── In-Game Usage ─────────────────────────────────────────────────────
        section("🎮", "In-Game Usage")
        para("Open your bank window in WoW first, then run this command in chat:")

        cmd_outer = tk.Frame(inner, bg=C_PANEL)
        cmd_outer.pack(fill=tk.X, padx=PAD, pady=(0, 6))
        tk.Frame(cmd_outer, bg=C_OK, width=3).pack(side=tk.LEFT, fill=tk.Y)
        cmd_inner = tk.Frame(cmd_outer, bg=C_PANEL)
        cmd_inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10)
        cmd_inner.columnconfigure(0, weight=1)
        tk.Label(cmd_inner, text="In-Game Command  —  Ctrl+A then Ctrl+C to copy",
                 bg=C_PANEL, fg=C_DIM,
                 font=("Segoe UI", _scaled(8))).grid(row=0, column=0, sticky=tk.W)
        cmd_box = tk.Text(cmd_inner, height=1, bg=C_PANEL, fg=C_ACCENT,
                          font=("Consolas", _scaled(13), "bold"),
                          relief=tk.FLAT, borderwidth=0,
                          insertbackground=C_ACCENT,
                          selectbackground=C_ACCENT, selectforeground=C_BG)
        cmd_box.insert("1.0", "/gbankexport reload")
        cmd_box.configure(state=tk.NORMAL)
        cmd_box.grid(row=1, column=0, sticky=tk.EW, pady=(4, 0))

        para("The bank window must be open — WoW only loads bank contents into memory "
             "while the bank UI is visible. After the reload, GBank Poster detects the "
             "file change and posts to Discord automatically within a few seconds.")

        # ── General Tab ───────────────────────────────────────────────────────
        section("⚙", "General Tab")
        cards([
            ("SavedVariables File",
             "The file WoW writes your exported inventory to. Lives deep inside your WoW "
             "folder under WTF/Account/.../SavedVariables/. GBank Poster watches this file "
             "and triggers a post the moment WoW updates it. Auto-detected on install — "
             "click Re-Detect if it goes missing after moving WoW."),
            ("WoW Addon",
             "Path to your WoW AddOns folder. Use Install / Reinstall Addon to copy the "
             "bundled addon into WoW. Required before your first export."),
            ("Webhook URL",
             "A Discord webhook lets external apps post to a specific channel. To get one: "
             "right-click your channel → Edit Channel → Integrations → Webhooks → New Webhook "
             "→ Copy Webhook URL. Each webhook is unique to one channel. This shared URL "
             "applies to all characters unless overridden in the Webhooks tab."),
            ("Start with Windows",
             "Adds GBank Poster to Windows startup so it runs automatically at login."),
            ("Show Notifications",
             "Shows a Windows tray notification after each successful Discord post."),
        ])

        # ── Webhooks Tab ──────────────────────────────────────────────────────
        section("🔗", "Webhooks Tab")
        para("Each character detected in your SavedVariables file gets its own panel. "
             "Select a character from the dropdown to configure it.")
        cards([
            ("Enabled",
             "If unchecked, this character is skipped entirely when posting."),
            ("Display Name",
             "The name shown above the Discord post. Defaults to the character name."),
            ("Embed Title",
             "The title of the Discord embed card. Defaults to the character name."),
            ("Webhook URL",
             "Per-character override. Leave blank to use the shared URL from General."),
            ("Embed Color",
             "The colored stripe on the left of the Discord embed. Click the swatch to open "
             "the Windows color picker. Recent colors appear as swatches — click any to reuse."),
            ("Avatar — File mode",
             "Upload a local image. GBank Poster patches the Discord webhook's permanent avatar "
             "(resized to 512×512). Drop a file, click to browse, or Ctrl+V to paste from clipboard."),
            ("Avatar — URL mode",
             "Paste a direct image URL. Embedded in each post payload — does not modify the "
             "webhook's permanent avatar. Click Preview to verify and load a thumbnail."),
            ("History",
             "Last 5 files or URLs per mode are saved. Use the dropdown to reload a previous avatar."),
            ("Save button",
             "Saves this character's settings and uploads the avatar if in file mode. "
             "Use Save & Apply at the bottom to commit all settings globally."),
        ])

        # ── How Posting Works ─────────────────────────────────────────────────
        section("📡", "How Posting Works")
        para("GBank Poster polls your SavedVariables file every 2 seconds. When it detects "
             "a change, it compares timestamps to find which characters have new data and only "
             "reposts those — other characters are untouched.")
        para("Each character's Discord post is independent. Old messages are deleted before "
             "new ones are sent, keeping the channel clean. If your inventory exceeds one "
             "embed's character limit, multiple messages are posted in sequence.")
        para("Every item links directly to Wowhead, so guild members can hover in Discord "
             "to see item tooltips (requires the Wowhead Discord bot or browser extension).")

        # ── Tray Icon ─────────────────────────────────────────────────────────
        section("🖥", "Tray Icon")
        para("GBank Poster lives in the Windows system tray — bottom-right corner near the clock. "
             "Right-click the icon for:")
        cards([
            ("Open Settings",  "Opens this window. Double-clicking the icon does the same."),
            ("Post Now",       "Manually triggers a post for all enabled characters immediately."),
            ("Quit",           "Stops the app and removes it from the tray."),
        ])

        # ── Troubleshooting ───────────────────────────────────────────────────
        section("⚠", "Troubleshooting")
        alert_cards([
            ("Nothing posts",
             "Check the Log tab for errors. Verify the SavedVariables path, the webhook URL, "
             "and that the character is enabled in the Webhooks tab."),
            ("Bank not included",
             "Open the bank window in WoW before running /gbankexport reload. The addon can "
             "only read bank contents while the bank UI is open."),
            ("Posts keep repeating",
             "Each export updates the timestamp, so a new post fires. "
             "GBank Poster only skips a post if the timestamp hasn't changed since last time."),
            ("Avatar not updating",
             "File mode patches the webhook permanently — Discord may cache the old image "
             "briefly. URL mode takes effect immediately on the next post."),
            ("Notifications missing",
             "Check Windows Settings → System → Notifications and ensure notifications "
             "are not blocked for this app."),
        ])

        # Bottom padding
        tk.Frame(inner, bg=C_BG, height=20).pack()

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _show_picker(self, paths: list[str], target: tk.StringVar):
        win = tk.Toplevel(self)
        win.title("Select")
        win.configure(bg=C_BG)
        _window_center(win, 640, 210)
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        ttk.Label(win, text="Multiple options found — select one:").pack(
            padx=16, pady=(12, 4), anchor=tk.W)
        lb = tk.Listbox(win, bg=C_PANEL, fg=C_TEXT,
                        selectbackground=C_ACCENT, selectforeground=C_BG,
                        font=("Consolas", _scaled(9)), relief=tk.FLAT, height=5)
        lb.pack(padx=16, fill=tk.X)
        for p in paths: lb.insert(tk.END, p)
        lb.selection_set(0)
        def _ok():
            sel = lb.curselection()
            if sel: target.set(paths[sel[0]])
            win.destroy()
        ttk.Button(win, text="Select", command=_ok).pack(pady=8)

    def _on_custom_colors_changed(self, colors: list):
        """Called whenever a custom color slot is saved in the picker."""
        self._custom_colors = list(colors)
        self._config["custom_colors"] = self._custom_colors
        core.save_config(CONFIG, self._config)

    def _on_window_paste(self, event=None):
        """Forward Ctrl+V to the active avatar drop zone regardless of focus."""
        if self._wh_avatar_section:
            self._wh_avatar_section._drop_zone._on_paste()

    def _save(self):
        self._config["savedvariables_path"] = self._sv_path_var.get().strip()
        self._config["webhook_url"]          = self._wh_url_var.get().strip()
        self._config["notifications"]        = self._notify_var.get()
        self._config["custom_colors"]        = self._custom_colors
        if self._wh_tab_selection:
            self._config["last_webhook_tab"] = self._wh_tab_selection
        set_startup_enabled(self._startup_var.get())
        self._save_wh_panel()
        core.save_config(CONFIG, self._config)
        self._on_save(self._config)


# ═══════════════════════════════════════════════════════════════════════════════
#  TRAY APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

class TrayApp:
    def __init__(self):
        self.config: dict = core.load_config(CONFIG)
        self.state:  dict = core.load_json(STATE)

        self.root = TkinterDnD.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        self._ui_queue:     queue.Queue                = queue.Queue()
        self._settings_win: Optional[SettingsWindow]   = None
        self._stop_event:   Optional[threading.Event]  = None
        self._watch_thread: Optional[threading.Thread] = None
        self._log_lines:    list[str]                  = []
        self._icon_img      = _make_tray_icon(64)
        self._tray_icon:    Optional[pystray.Icon]     = None

        self._poll_ui_queue()

    def log(self, msg: str):
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        self._log_lines.append(line)
        if len(self._log_lines) > 500:
            self._log_lines.pop(0)
        if self._settings_win and self._settings_win.winfo_exists():
            self.root.after(0, lambda m=msg: self._settings_win.append_log(m))

    def _poll_ui_queue(self):
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui_queue)

    def _schedule(self, fn):
        self._ui_queue.put(fn)

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Open Settings", self._on_open_settings, default=True),
            pystray.MenuItem("Post Now",      self._on_post_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",          self._on_quit),
        )

    def _notify(self, title: str, message: str):
        """Queue notification onto the main thread via the UI queue (thread-safe)."""
        if self.config.get("notifications", True) and self._tray_icon:
            self._schedule(lambda t=title, m=message: self._show_notification(t, m))

    def _show_notification(self, title: str, message: str):
        if not self._tray_icon:
            return
        try:
            self._tray_icon.notify(message, title)
        except Exception as e:
            self.log(f"Notification error: {e}")

    def _start_watch(self):
        sv = self.config.get("savedvariables_path", "").strip()
        if not sv:
            self.log("Watch: no SavedVariables path configured yet.")
            return
        self._stop_event   = threading.Event()
        self._watch_thread = threading.Thread(
            target=core.watch_savedvariables,
            args=(sv, self._on_file_changed, self._stop_event),
            daemon=True,
        )
        self._watch_thread.start()
        if os.path.isfile(sv):
            self.log(f"Watch started → {sv}")
        else:
            self.log(f"Watch armed → {sv}  (waiting for first export)")

    def _stop_watch(self):
        if self._stop_event:
            self._stop_event.set()
        self._watch_thread = None
        self._stop_event   = None

    def _restart_watch(self):
        self._stop_watch()
        self._start_watch()

    def _on_file_changed(self):
        self.log("File change detected — posting…")
        self._do_post_all()

    def _do_post_all(self):
        def _run():
            ok = core.post_all_enabled(self.config, self.state, self.log)
            if ok:
                core.save_json(STATE, self.state)
                self._notify("GBank Poster", "Guild bank posted to Discord ✓")
            else:
                self._notify("GBank Poster", "Post had errors — check the log.")
        threading.Thread(target=_run, daemon=True).start()

    def _on_open_settings(self, icon=None, item=None):
        self._schedule(self._open_settings)

    def _on_post_now(self, icon=None, item=None):
        self.log("Manual post triggered.")
        self._do_post_all()

    def _on_quit(self, icon=None, item=None):
        self._schedule(self._quit)

    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return
        self._settings_win = SettingsWindow(
            self.root, self.config, self.state,
            on_save=self._on_settings_saved)
        for line in self._log_lines[-200:]:
            stripped = line[line.find("]") + 2:] if "]" in line else line
            self._settings_win.append_log(stripped)

    def _on_settings_saved(self, new_config: dict):
        self.config = new_config
        self._restart_watch()
        self.log("Settings saved — watch restarted.")

    def _quit(self):
        self._stop_watch()
        if self._tray_icon:
            self._tray_icon.stop()
        self.root.quit()
        self.root.destroy()

    def _show_wizard(self):
        SetupWizard(self.root, self.config, on_complete=self._on_wizard_done)

    def _on_wizard_done(self, config: dict):
        self.config = config
        self._start_watch()
        self.log("Setup complete.")

    def run(self):
        self._tray_icon = pystray.Icon(
            APP_NAME, self._icon_img, "GBank Poster", self._build_menu())
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

        needs_setup = (
            not self.config.get("setup_complete")
            or not self.config.get("webhook_url", "").strip()
        )
        if needs_setup:
            self.root.after(200, self._show_wizard)
        else:
            self._start_watch()

        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    TrayApp().run()