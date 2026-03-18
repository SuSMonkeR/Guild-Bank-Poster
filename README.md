# ⚔ GBank Poster

**Automatically post your WoW Classic guild bank inventory to Discord — with Wowhead links for every item.**

Runs silently in your system tray. Export from WoW, and within seconds your Discord channel has a clean, up-to-date snapshot.

---

## 🔒 Is this safe?

Yes — and you can verify it yourself.

**Every release is built automatically by GitHub Actions** directly from the source code in this repository. No one touches the EXE manually. You can inspect every build step in the [Actions tab](../../actions) — it's all public.

**To verify your download matches what GitHub built**, open PowerShell and run:
```powershell
Get-FileHash GBankPoster.exe -Algorithm SHA256
```
Then compare the hash to the one published in the [release notes](../../releases/latest). If they match, the file is byte-for-byte identical to what GitHub compiled from this source code.

**Want to go further?** Read the source — `app.py` and `core.py` are the entire application. Nothing is hidden.

---

## 📥 Download

Download the latest `GBankPoster.exe` from the [Releases page](../../releases/latest).

Double-click to run. No installation required. First launch opens the setup wizard.

---

## ⚙️ How it works

```
In WoW:  /gbankexport reload
              │
              ▼
    WoW writes SavedVariables\GBankExporter.lua
              │
              ▼
    GBankPoster detects the file change
              │
              ▼
    Formats inventory as Discord embeds
    with clickable Wowhead item links
              │
              ▼
    Posts to your Discord channel ✓
```

Old messages are deleted before new ones are posted — no duplicates, no clutter.

---

## 🚀 Quick Start

1. **Download** `GBankPoster.exe` from [Releases](../../releases/latest)
2. **Double-click** to launch — the setup wizard opens automatically
3. **Install the addon** — the wizard does this for you from inside the app
4. **Paste your Discord webhook URL** — see below if you don't have one
5. **In WoW**, open your bank then type `/gbankexport reload`
6. **Done** — GBank Poster detects the export and posts to Discord automatically

---

## 🔗 Getting a Discord Webhook URL

1. Open Discord and go to the channel you want to post to
2. Right-click the channel → **Edit Channel**
3. Go to **Integrations → Webhooks → New Webhook**
4. Give it a name, then click **Copy Webhook URL**
5. Paste it into GBank Poster's General tab

> Each webhook is unique to one channel. You need a separate webhook for each channel you want to post to.

---

## 👥 Multiple Characters

Every character you export is stored separately. Each can have its own:
- Discord webhook (post to different channels per character)
- Display name and embed title
- Embed color
- Avatar image

Configure per-character settings in the **Webhooks tab** inside the app.

---

## 🔧 Running from Source

Requires Python 3.11+.

```bash
git clone https://github.com/YOUR_USERNAME/gbank-poster.git
cd gbank-poster/GbankPoster
pip install pillow pystray tkinterdnd2
python app.py
```

To build the EXE yourself:
```bash
pip install pyinstaller
pyinstaller GBankPoster.spec
# Output: dist\GBankPoster.exe
```

---

## 📁 What gets installed

| Item | Location | Notes |
|------|----------|-------|
| `GBankPoster.exe` | Wherever you put it | Single self-contained file |
| `GBankExporter` addon | `WoW/Interface/AddOns/` | Installed by the setup wizard |
| Config & state | `%APPDATA%\GBankPoster\` | Created on first run, never in WoW folder |

**To uninstall:** Delete the EXE, delete `%APPDATA%\GBankPoster\`, and delete the `GBankExporter` folder from your WoW AddOns directory.

---

## ❓ Troubleshooting

| Problem | Fix |
|---------|-----|
| Nothing posts to Discord | Check the Log tab in settings for error details |
| Bank contents missing | Open the bank window in WoW *before* running `/gbankexport reload` |
| SavedVariables not found | Click Re-Detect in the General tab, or use Browse |
| Windows SmartScreen warning | Click "More info" → "Run anyway" — this happens with unsigned EXEs. See the verification steps above to confirm the file is safe. |
| Notifications not appearing | Check Windows Settings → System → Notifications |

---

## 📄 License

MIT — do whatever you want with it.
