# 🎬 DON OF VICE CITY — YouTube Automation Pipeline

An automated, zero-touch YouTube channel growth engine designed for high-engagement gaming content (GTA 6 / GTA 5). Combines **1 Daily 16:9 Ultra HD 1440p Long Video** with **4 High-Retention 9:16 Action Shorts** every day, featuring intelligent clip deduplication, floating typography, copyright-safe audio, cross-promotion funneling, and advance scheduling.

---

## 🌟 Channel Strategy & Daily Schedule

To maximize both **Channel Watch Time (AdSense monetization)** and **Viral Subscriber Growth**, the system runs an automated hybrid funnel:

1. **🎬 1 Daily 16:9 1440p Ultra HD Long Video (3–5 min):**
   * **Scheduled Time:** Every day at **06:00 PM IST** (Gaming Prime Time).
   * **Resolution:** `2560x1440` (1440p 60FPS) to trigger YouTube's premium **VP9 / AV1** codec instead of low-bitrate H.264.
   * **Features:** Automatic chapter markers with timestamps, floating section titles, high-contrast custom 16:9 thumbnail, and copyright-free NCS soundtrack.

2. **⚡ 4 Daily 9:16 Action Shorts (26s High Retention):**
   * **Slot 1 (01:00 PM):** Afternoon lunch break scroll
   * **Slot 2 (04:30 PM):** Evening commute peak
   * **Slot 3 (07:30 PM):** Dinner prime time peak
   * **Slot 4 (10:30 PM):** Late night binge scroll
   * **Features:** Bold floating action hooks (yellow & white with black outline stroke), Neon cyan watermark (`DON OF VICE CITY`), center-cropped vertical action, zero black letterboxing.

3. **🔗 Cross-Promotion Funneling:**
   * Every Short automatically embeds the direct link of the day's Long Video in the top line of its description:
     `🔥 WATCH FULL 4K VIDEO HERE: https://www.youtube.com/watch?v=...`
   * Funnels thousands of Shorts viewers directly into the Long Video, dramatically boosting watch time and revenue.

---

## ✨ Core Technical Highlights

- **🎯 Zero Repetition Deduplication Engine (`used_source_ids`):**
  Persistent JSON database tracks every used video ID. Fresh YouTube searches automatically filter out previously used clips, guaranteeing 100% unique footage.
- **🛡️ 100% Copyright Claim Immunity:**
  Original in-game audio and radio tracks are automatically stripped via FFmpeg. Replaced with royalty-free, high-energy Phonk/EDM beats (NoCopyrightSounds).
- **🔒 YouTube API Quota Optimization:**
  YouTube limits free Data API usage to 10,000 units/day. Each upload costs 1,600 units.
  With 1 Long Video + 4 Shorts = **5 uploads/day = 8,000 units**, keeping daily usage safely below quota limits.
- **⏰ Hands-Free Boot Automation:**
  Launches silently upon Windows login via `DonOfViceCity_Daily.vbs` without any visible popup or terminal window.

---

## 📁 Repository Structure

```
YoutubeAutomation/
├── assets/
│   └── audio/
│       └── phonk_1.mp3          # Copyright-free Phonk background music
├── master_autopilot.py          # Unified Master Orchestrator (1 Long + 4 Shorts / day)
├── long_video_engine.py         # 16:9 1440p Long Video Automation Engine
├── auto_pilot_bot.py            # 9:16 Action Shorts Engine
├── upload_video.py              # YouTube Data API v3 upload & scheduling module
├── setup_auth.py                # OAuth 2.0 authorization server & token generator
├── run_daily.bat                # Windows batch launcher (runs master_autopilot.py)
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
- FFmpeg installed in system PATH or Python scripts directory
- YouTube channel authenticated via `setup_auth.py`

### 2. Run Manually
```bash
python master_autopilot.py
```

### 3. Windows Boot Automation
Place a shortcut to `DonOfViceCity_Daily.vbs` in the Windows Startup folder:
`shell:startup`
Whenever the PC boots and connects to the internet, all remaining daily videos are produced and scheduled on YouTube in advance.
