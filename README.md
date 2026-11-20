# 🎬 YouTube Shorts Automation Pipeline

An automated, zero-touch YouTube Shorts publishing engine designed for high-engagement gaming content (GTA 6 / GTA 5), complete with intelligent clip deduplication, 9:16 vertical action formatting, modern floating typography, and automated advance scheduling.

---

## ✨ Features

- **🎯 Zero Repetition Deduplication Engine (`used_source_ids`):**
  - Tracks every used YouTube clip ID in a persistent local database.
  - Automatically queries fresh search results and skips any previously downloaded footage.
  - Guarantees 100% unique visual footage for every single video published.

- **✂️ FFmpeg 9:16 Vertical Action Short Formatter:**
  - Dynamic scaling, aspect ratio correction, and center-cropping to `1080x1920` (9:16 vertical full screen).
  - High frame rate (60 FPS) and pristine video bitrate.
  - Precise 26-second duration optimized for YouTube Shorts algorithm completion rates.

- **🔤 Modern Floating Typography (Zero Black Boxes):**
  - Clean floating Arial Black typography with high-contrast black border stroke (`borderw=6`).
  - White primary action hook + vibrant yellow punchline sub-hook.
  - Neon cyan watermark branding (`DON OF VICE CITY`) anchored at the bottom.

- **🎵 Dynamic Audio & Copyright-Free Beats:**
  - Integrated high-energy Phonk background music (NoCopyrightSounds / royalty-free).
  - Strips copyrighted radio/in-game audio while preserving immersion.

- **⏰ Smart Schedule Batching & Daily Quota Optimization:**
  - 5 daily target slots:
    - **Slot 1 (1:30 PM):** Afternoon lunch peak
    - **Slot 2 (4:00 PM):** Evening tea break
    - **Slot 3 (6:30 PM):** Transit & casual scroll
    - **Slot 4 (9:00 PM):** Prime time viewership peak
    - **Slot 5 (11:30 PM):** Late night gaming & binge scroll
  - **Dynamic Schedule:** If the machine boots at 1:00 PM (or anytime), all remaining slots for the day are computed, uploaded, and scheduled in advance on YouTube in a single batch.

- **🧹 Automatic Storage Management:**
  - Deletes raw downloaded clips immediately after video editing.
  - Auto-cleans processed videos older than 24 hours to prevent disk bloating.

---

## 📁 Repository Structure

```
YoutubeAutomation/
├── assets/
│   └── audio/
│       └── phonk_1.mp3          # Copyright-free Phonk background music
├── auto_pilot_bot.py            # Main automation engine & scheduler
├── upload_video.py              # YouTube Data API v3 upload & scheduling module
├── setup_auth.py                # OAuth 2.0 authorization server & token generator
├── run_daily.bat                # Windows batch launcher
├── launch_silent.vbs            # Silent VBScript wrapper (no popup windows)
├── requirements.txt             # Python dependencies
├── client_secret.json.example   # OAuth credentials format template
├── autopilot_db.json.example    # Database structure template
├── .gitignore                   # Excludes tokens, secrets, media & cache
└── README.md                    # Documentation
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.10+
- FFmpeg installed and accessible in system `PATH`
- A Google Cloud Platform (GCP) project with the **YouTube Data API v3** enabled

### 2. Clone the Repository
```bash
git clone https://github.com/Jhaavesh/YoutubeAutomation.git
cd YoutubeAutomation
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Google Cloud OAuth Credentials
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **YouTube Data API v3**.
3. Create an **OAuth 2.0 Client ID** (Application type: *Desktop App*).
4. Download the JSON credential file, rename it to `client_secret.json`, and place it in the project root directory.

### 5. Authenticate Your YouTube Channel
Run the interactive authentication server:
```bash
python setup_auth.py
```
This will open your default browser. Sign in with your YouTube channel's Google account and grant permissions. A `token.pickle` file will be generated locally for permanent refreshable access.

### 6. Run the Pipeline
```bash
python auto_pilot_bot.py
```

---

## 🖥️ Automated Hands-Off Setup (Windows)

To run the pipeline silently whenever your computer starts:
1. Press `Win + R`, type `shell:startup`, and press Enter.
2. Place a shortcut to `launch_silent.vbs` inside the Startup folder.
3. The script will run automatically in the background on startup, schedule all daily videos, and clean up after itself without requiring any user intervention.

---

## 🔒 Security Notice

Credentials (`client_secret.json` and `token.pickle`) and generated video media (`daily_generated/`) are strictly ignored via `.gitignore` and should never be committed or published.

---

## 📄 License
MIT License. Feel free to use and modify for your own automated YouTube workflows.
