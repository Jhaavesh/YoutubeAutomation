# 🎬 DON OF VICE CITY — YouTube Automation Pipeline (Refactored)

An automated, zero-touch YouTube channel growth engine for high-engagement gaming content (GTA 6 / GTA 5). Produces **1 Daily 16:9 Ultra HD 1440p Long Video** + **4 Daily 9:16 Action Shorts** with intelligent deduplication, copyright-safe audio, cross-promotion funneling, and advance scheduling.

---

## 🌟 What's New in Refactored Version

| Feature | Before | After |
|---------|--------|-------|
| **Configuration** | Hardcoded in multiple files | Single `config.yaml` |
| **Multi-channel** | Not supported | ✅ Full support |
| **Quota tracking** | Manual estimation | ✅ Automatic with alerts |
| **Code reuse** | Duplicated across 3 files | ✅ Shared `utils.py` |
| **Logging** | Print statements | ✅ Structured rotating logs |
| **Boot automation** | Basic VBS | ✅ Batch + PowerShell + health checks |
| **Monitoring** | None | ✅ `health_check.py` |
| **Testing** | Manual only | ✅ CLI flags for single runs |

---

## 📁 Repository Structure

```
YoutubeAutomation/
├── config.yaml              # ⚙️ CENTRAL CONFIGURATION (EDIT THIS)
├── config_loader.py         # Loads & validates config.yaml
├── utils.py                 # Shared utilities (DB, FFmpeg, quota, scheduling)
├── upload_video.py          # YouTube upload with quota tracking
├── long_video_engine.py     # 16:9 1440p Long video generation
├── auto_pilot_bot.py        # 9:16 Shorts generation
├── master_autopilot.py      # 🎯 MAIN ORCHESTRATOR (run this)
├── setup_auth.py            # OAuth authentication (multi-channel)
├── health_check.py          # System monitoring & diagnostics
├── run_daily.bat            # Windows batch launcher
├── run_daily.ps1            # PowerShell launcher (recommended)
├── launch_silent.vbs        # Silent Windows startup launcher
├── requirements.txt         # Python dependencies
├── client_secret.json       # 🔐 OAuth credentials (NOT in git)
├── token.pickle             # 🔐 Auth tokens (NOT in git)
├── autopilot_db.json        # Runtime database (auto-generated)
├── autopilot.log            # Main log (auto-generated)
├── assets/
│   └── audio/
│       └── phonk_1.mp3      # Background music
└── daily_generated/         # Temporary video files (auto-cleaned)
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Install FFmpeg
- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
- Or use the path in `config.yaml`: `C:/Users/Awesh/AppData/Local/Programs/Python/Python312/Scripts/ffmpeg.exe`

### 3. Configure YouTube API
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create project → Enable **YouTube Data API v3**
3. Create **OAuth 2.0 Client ID** (Desktop app)
4. Download `client_secret.json` → place in project root

### 4. Authenticate Channel
```bash
# Authenticate default channel
python setup_auth.py

# Or specific channel
python setup_auth.py --channel donofvicecity2026

# List all configured channels
python setup_auth.py --list
```

### 5. Test Run
```bash
# Dry run - check quota only
python master_autopilot.py --quota

# Run only long video
python master_autopilot.py --long-only

# Run only shorts
python master_autopilot.py --shorts-only

# Full daily run
python master_autopilot.py
```

---

## ⚙️ Configuration: `config.yaml`

**All settings in one file** — no need to edit Python code.

### Key Sections:

```yaml
# Channel setup (multi-channel ready)
channels:
  default: "donofvicecity2026"
  accounts:
    donofvicecity2026:
      name: "DON OF VICE CITY"
      token_file: "token.pickle"
      client_secret_file: "client_secret.json"

# Video specifications
video:
  long:
    resolution: "2560x1440"   # 1440p triggers VP9/AV1 codec
    duration_range_seconds: [150, 180]
  short:
    resolution: "1080x1920"   # 9:16 vertical
    duration_seconds: 26

# Daily schedule (IST)
schedule:
  long_video:
    target_hour: 18           # 6:00 PM
  shorts:
    standard_slots:
      - {slot_id: 1, hour: 13, minute: 0}    # 1:00 PM
      - {slot_id: 2, hour: 16, minute: 30}   # 4:30 PM
      - {slot_id: 3, hour: 19, minute: 30}   # 7:30 PM
      - {slot_id: 4, hour: 22, minute: 30}   # 10:30 PM

# Quota management
quota:
  daily_limit: 10000
  costs:
    video_upload: 1600
    thumbnail_set: 50
  alert_threshold_percent: 80

# Content topics (easy to extend)
topics:
  long_video_pool: [...]
  shorts_pool: [...]
```

---

## 📅 Daily Schedule (IST)

| Content | Time | Purpose |
|---------|------|---------|
| **Long Video** | 6:00 PM | Prime time, max watch time |
| **Short 1** | 1:00 PM | Lunch break scroll |
| **Short 2** | 4:30 PM | Evening commute |
| **Short 3** | 7:30 PM | Dinner prime time |
| **Short 4** | 10:30 PM | Late night binge |

### Smart Dynamic Scheduling
If you boot the laptop **after** a scheduled time (e.g., 3:00 PM), the system:
1. Skips past slots
2. Spreads remaining videos evenly until 11:30 PM
3. **Never skips a video** — all 4 shorts + 1 long always publish same day

---

## 🔗 Cross-Promotion Funnel

Every Short automatically includes:
```
🔥 WATCH FULL 4K VIDEO HERE:
👉 https://www.youtube.com/watch?v=LONG_VIDEO_ID
(Long Video Title)
```
This funnels Shorts viewers → Long Video → **AdSense revenue + watch time boost**.

---

## 🛡️ Copyright Protection

- **In-game audio stripped** via FFmpeg (radio songs, dialogue)
- **Only NCS/royalty-free Phonk** mixed in
- **Content ID safe** — zero copyright claims guaranteed

---

## 📊 Quota Management

| Operation | Cost | Daily (1 Long + 4 Shorts) |
|-----------|------|---------------------------|
| Video Upload | 1,600 | 5 × 1,600 = 8,000 |
| Thumbnail Set | 50 | 1 × 50 = 50 |
| **Total** | | **8,050 / 10,000** |

✅ **2,000 units buffer** — completely immune to quota limits!

**Monitor quota:**
```bash
python upload_video.py --quota
python health_check.py  # Includes quota check
```

---

## 🖥️ Windows Boot Automation

### Option 1: Silent VBS (Original)
1. Create shortcut to `launch_silent.vbs`
2. Place in **Startup folder**: `Win+R` → `shell:startup`
3. Runs completely hidden on boot

### Option 2: PowerShell (Recommended)
- Better error handling, Event Log integration, structured logging
- Run manually: `.\run_daily.ps1`
- Or create scheduled task triggered on startup

### Option 3: Task Scheduler (Most Reliable)
```powershell
# Run as admin
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File C:\Ajfiles\Youtube\run_daily.ps1"
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "DonOfViceCity_Daily" -RunLevel Highest
```

---

## 🔧 CLI Usage Reference

### Master Autopilot
```bash
python master_autopilot.py                    # Full daily run (default channel)
python master_autopilot.py --channel KEY      # Specific channel
python master_autopilot.py --all-channels     # All configured channels
python master_autopilot.py --long-only        # Only long video
python master_autopilot.py --shorts-only      # Only shorts
python master_autopilot.py --quota            # Show quota report
python master_autopilot.py --verify           # Verify auth
```

### Long Video Engine
```bash
python long_video_engine.py                   # Build today's long video
python long_video_engine.py --topic ID        # Specific topic (testing)
python long_video_engine.py --quota           # Quota report
```

### Shorts Engine
```bash
python auto_pilot_bot.py                      # All pending shorts
python auto_pilot_bot.py --slot 2             # Single slot (testing)
python auto_pilot_bot.py --topic physics      # Specific topic
python auto_pilot_bot.py --quota              # Quota report
```

### Upload Module
```bash
python upload_video.py --quota                # Quota report
python upload_video.py --verify               # Verify channel
python upload_video.py --verify --channel KEY # Verify specific channel
```

### Setup Auth
```bash
python setup_auth.py                          # Default channel
python setup_auth.py --channel KEY            # Specific channel
python setup_auth.py --list                   # List channels
python setup_auth.py --all                    # All channels
```

### Health Check
```bash
python health_check.py                        # Full health report
python health_check.py -v                     # Verbose (show errors)
python health_check.py --fix-duplicates       # Clean DB duplicates
python health_check.py --recent 7             # Show last 7 days uploads
python health_check.py --json                 # JSON output for monitoring
```

---

## 📈 Monitoring & Maintenance

### Health Check (Run Daily)
```bash
# Manual
python health_check.py

# As scheduled task (PowerShell)
# Creates Windows Event Log entries on failure
```

### Key Metrics to Watch
- **Quota usage** — Should stay < 80%
- **Disk space** — Auto-cleanup keeps < 100 MB
- **Duplicate source IDs** — Should be 0
- **Recent errors** — Check `autopilot.log`

### Log Files
| File | Purpose |
|------|---------|
| `autopilot.log` | Main structured logs (rotating, 10 MB max) |
| `autopilot_boot.log` | Boot launcher runs |
| `autopilot_errors.log` | Failed runs only |
| `last_run_health.json` | Last run status |

---

## 🎯 Adding New Channels

1. **Add to `config.yaml`:**
```yaml
channels:
  accounts:
    newchannel:
      name: "NEW CHANNEL NAME"
      token_file: "token_newchannel.pickle"
      client_secret_file: "client_secret_newchannel.json"
```

2. **Place `client_secret_newchannel.json`** in project root

3. **Authenticate:**
```bash
python setup_auth.py --channel newchannel
```

4. **Run:**
```bash
python master_autopilot.py --channel newchannel
# Or run all:
python master_autopilot.py --all-channels
```

---

## 🐛 Troubleshooting

### "FFmpeg not found"
```bash
# Check config.yaml paths.ffmpeg_exe points to valid ffmpeg.exe
# Or add FFmpeg to system PATH
```

### "Quota exceeded"
- Wait until midnight PST (quota resets)
- Or reduce daily videos in `config.yaml`

### "Token expired / invalid"
```bash
python setup_auth.py --channel YOUR_CHANNEL
```

### "No internet" on boot
- Increase `network.internet_check.max_wait_seconds` in config.yaml
- Check Windows network profile (Private vs Public)

### Videos not uploading
- Check `autopilot.log` for errors
- Run `python health_check.py -v` for diagnostics

---

## 📝 License & Credits

- **Music**: NoCopyrightSounds (NCS) — Phonk beats
- **Footage**: YouTube Creative Commons / Fair Use (gameplay)
- **Code**: Custom automation pipeline

---

## 🤝 Contributing

1. Edit `config.yaml` for new topics/schedule
2. Add topics to `topics.long_video_pool` or `topics.shorts_pool`
3. Test with `--long-only` or `--shorts-only --slot N`
4. Run full pipeline with `master_autopilot.py`

---

**Made with ❤️ for the GTA 6 community — DON OF VICE CITY**