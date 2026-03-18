# GBank Poster

Post your WoW Classic character's inventory & bank snapshot to a Discord channel — automatically, with Wowhead links for every item.

---

## How it works

```
WoW In-Game
  └─ /gbankexport reload       ← Lua addon scans bags/bank & saves data
        │
        ▼
  SavedVariables\GBankExporter.lua
        │
        ▼
  GBankPoster.exe              ← Reads file, formats embeds, posts to Discord
        │
        ▼
  Discord channel              ← Clean embed with clickable Wowhead links
```

Multiple characters are all stored in the same SavedVariables file and can each be posted to the same or different Discord webhooks.

---

## Part 1 — Install the WoW Addon

1. Open your WoW AddOns folder:
   ```
   World of Warcraft\_classic_era_\Interface\AddOns\
   ```

2. Create a new folder called `GBankExporter`.

3. Copy both files into it:
   - `GBankExporter.toc`
   - `GBankExporterAddon.lua`

4. Launch WoW (or `/reload` in-game) and make sure **GBankExporter** appears in your AddOn list.

---

## Part 2 — Set up the Discord Webhook

1. In Discord, open the channel you want to post to.
2. Go to **Edit Channel → Integrations → Webhooks → New Webhook**.
3. Set a name and optional avatar, then click **Copy Webhook URL**.
4. Keep this URL — you'll paste it into GBank Poster.

---

## Part 3 — Run GBank Poster

### Quick start (EXE)

Double-click `GBankPoster.exe`. No installation required.

### From source (Python 3.11+)

```bash
pip install pyinstaller   # only needed for building the EXE
python app.py
```

### First-time setup

1. **Settings tab** → paste your Discord Webhook URL → Save Settings.
   - Optionally set a Display Name, Avatar URL, and Embed Title.

2. **Dashboard tab** → click **Auto-Detect** to find your SavedVariables file automatically.
   - If it's not found, click **Browse** and navigate to:
     ```
     World of Warcraft\_classic_era_\WTF\Account\<YourAccountName>\SavedVariables\GBankExporter.lua
     ```

---

## Part 4 — Export from WoW

1. Log into the character whose inventory/bank you want to post.
2. **Open the bank** (walk up to a banker and open your bank window).
3. Type the chat command:
   ```
   /gbankexport reload
   ```
   The UI will reload and the data will be saved to disk automatically.

4. Back in GBank Poster, the character will appear in the Dashboard.

> **Tip — Watch Mode:** Click **Start Watch** before doing your `/gbankexport reload`. The app will detect the file change and post to Discord automatically the moment WoW writes the data.

---

## Multiple Characters

You can export as many characters as you want — each `/gbankexport reload` on a different character adds to the same file without overwriting previous characters.

To manage them individually:
- **Characters tab** — enable/disable each character, and optionally give each their own webhook URL, display name, avatar, and embed title.

---

## Building the EXE

If you're distributing to others, build a standalone EXE:

```bat
cd GbankPoster
build.bat
```

Output: `dist\GBankPoster.exe`

Requirements: Python 3.11+ and internet access for `pip install pyinstaller`.

The EXE is fully self-contained. Copy it anywhere — `gbank_config.json` and `gbank_state.json` will be created next to it on first run.

---

## Config files (reference)

`gbank_config.json` — settings, auto-created on first save.

```json
{
  "savedvariables_path": "C:\\...\\SavedVariables\\GBankExporter.lua",
  "default_webhook": {
    "url": "https://discord.com/api/webhooks/...",
    "username": "Guild Bank",
    "avatar_url": "",
    "embed_title": "Guild Bank Snapshot",
    "embed_color": null
  },
  "characters": {
    "Dadmonker-Doomhowl": {
      "enabled": true,
      "use_default_webhook": true,
      "webhook_url": "",
      "webhook_username": "",
      "webhook_avatar_url": "",
      "embed_title": "",
      "embed_color": null
    }
  }
}
```

`gbank_state.json` — tracks Discord message IDs so old messages can be replaced rather than duplicated. Do not edit manually.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Character doesn't appear in Dashboard | Make sure you opened the bank **before** running `/gbankexport reload` |
| "No webhook URL" in Log | Go to Settings, enter the webhook URL, and click Save |
| Old Discord messages not deleted | The state file may have stale IDs — delete `gbank_state.json` and re-post |
| Auto-Detect finds nothing | WoW might be installed in a non-standard directory — use Browse |
| EXE build fails | Make sure Python 3.11+ is in PATH and pip works; run `pip install pyinstaller` manually |
