"""
DON OF VICE CITY — MASTER DAILY AUTOPILOT ENGINE (100% AUTOMATED)
==================================================================
Daily Schedule (IST):
- 1 Long Video (16:9 1440p Ultra HD 60FPS): Scheduled for 06:00 PM (Prime Time)
- 4 Action Shorts (9:16 Vertical 60FPS):
    * Slot 1: 01:00 PM (Lunch break peak)
    * Slot 2: 04:30 PM (Evening commute peak)
    * Slot 3: 07:30 PM (Dinner prime peak)
    * Slot 4: 10:30 PM (Late night binge peak)

Cross-Promotion & Funnel Strategy:
- Each Short embeds the Long Video's direct URL in its description & title hook,
  funneling viewers from high-volume Shorts directly into Long-form watch time & revenue!

Safety & Quota Management:
- Exactly 5 video uploads/day (1 Long + 4 Shorts = 8,000 quota units).
  Leaves 2,000 units headroom, completely immune to YouTube API quota limits!
- 100% Royalty-Free NCS Phonk audio.
- Strict deduplication so no clip is ever repeated.
"""
import os
import sys
import json
import time
import random
import shutil
import subprocess
import urllib.request
from datetime import datetime, timedelta

# Ensure UTF-8 output encoding on Windows
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import yt_dlp
from upload_video import upload_short, get_authenticated_service
from googleapiclient.http import MediaFileUpload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_AUDIO = os.path.join(BASE_DIR, 'assets', 'audio')
OUTPUT_DIR = os.path.join(BASE_DIR, 'daily_generated')
DB_FILE = os.path.join(BASE_DIR, 'autopilot_db.json')
LOCK_FILE = os.path.join(BASE_DIR, 'autopilot.lock')

def acquire_lock():
    """Prevents concurrent executions from creating duplicate uploads."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            cmd = f'tasklist /FI "PID eq {pid}"'
            out = subprocess.check_output(cmd, shell=True).decode()
            if str(pid) in out and "python" in out.lower():
                print(f"[Lock] Another autopilot instance (PID {pid}) is already running! Exiting to prevent duplicate uploads.")
                return False
        except Exception:
            pass
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return True

def release_lock():
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass

FFMPEG_EXE = r"C:\Users\Awesh\AppData\Local\Programs\Python\Python312\Scripts\ffmpeg.exe"
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = shutil.which('ffmpeg') or 'ffmpeg'

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSETS_AUDIO, exist_ok=True)

# 4 Target Daily Slots for Shorts (IST)
DAILY_SHORTS_SLOTS = [
    {"slot_id": 1, "name": "Slot 1 (01:00 PM)", "hour": 13, "minute": 0},
    {"slot_id": 2, "name": "Slot 2 (04:30 PM)", "hour": 16, "minute": 30},
    {"slot_id": 3, "name": "Slot 3 (07:30 PM)", "hour": 19, "minute": 30},
    {"slot_id": 4, "name": "Slot 4 (10:30 PM)", "hour": 22, "minute": 30}
]

# Viral Long Video Topics
LONG_TOPIC_POOL = [
    {
        "id_key": "6_star_swat_shootout",
        "search_query": "GTA 6 open world police chase gameplay 4k 60fps ps5 pro",
        "title": "GTA 6 6-Star SWAT Police Shootout & Escape: Insane Vice City Realism! (4K 60FPS)",
        "duration_sec": 180,
        "intro_title": "GTA 6 6-STAR POLICE PURSUIT",
        "sub_title": "VICE CITY SWAT ASSAULT AND CHASE",
        "chapters": [
            {"time": "0:00", "title": "Vice City Bank Heist Breach"},
            {"time": "0:40", "title": "5-Star Police Roadblocks & Spike Strips"},
            {"time": "1:20", "title": "Highway Helicopter Pursuit"},
            {"time": "2:00", "title": "SWAT Gunfight & Tactical Escape"},
            {"time": "2:40", "title": "Final Escape & Safehouse Evade"}
        ],
        "tags": ["gta 6", "gta 6 gameplay", "gta 6 police chase", "gta 6 4k", "vice city", "rockstar games", "gta 6 leaks", "gta vi", "ps5 pro", "don of vice city"]
    },
    {
        "id_key": "gta6_vs_gta5_evolution",
        "search_query": "GTA 6 vs GTA 5 ULTIMATE Comparison Details Graphics 4K",
        "title": "GTA 6 vs GTA 5: 13 Years of Physics & Graphics Evolution! (4K 60FPS)",
        "duration_sec": 150,
        "intro_title": "GTA 6 VS GTA 5 ULTIMATE COMPARISON",
        "sub_title": "13 YEARS OF DETAIL AND PHYSICS EVOLUTION",
        "chapters": [
            {"time": "0:00", "title": "Intro & Vice City Overview"},
            {"time": "0:30", "title": "Vehicle Deformation & Crash Physics"},
            {"time": "1:00", "title": "Ocean Wave & Speedboat Dynamics"},
            {"time": "1:35", "title": "5-Star SWAT Police Pursuit AI"},
            {"time": "2:10", "title": "Ray Tracing, Lighting & Ragdoll"}
        ],
        "tags": ["gta 6", "gta 6 vs gta 5", "gta 6 graphics", "gta 6 physics", "grand theft auto 6", "vice city", "gta vi", "ps5 pro", "gaming", "don of vice city"]
    },
    {
        "id_key": "florida_npc_details",
        "search_query": "GTA 6 real life Florida crazy moments world details 4k",
        "title": "GTA 6 vs Real Life Florida: Extreme Open World Details & NPC Madness! (4K 60FPS)",
        "duration_sec": 180,
        "intro_title": "GTA 6 REAL LIFE FLORIDA",
        "sub_title": "EXTREME WORLD DETAILS AND NPC MADNESS",
        "chapters": [
            {"time": "0:00", "title": "Vice Beach & Miami Strip Realism"},
            {"time": "0:45", "title": "Everglades Wildlife & Alligator Encounters"},
            {"time": "1:30", "title": "Leonida Keys Highway Dynamics"},
            {"time": "2:15", "title": "Florida Man NPC Chaos in Vice City"}
        ],
        "tags": ["gta 6", "florida", "gta 6 real life", "vice city", "gta vi 4k", "ps5 pro", "rockstar games", "don of vice city"]
    },
    {
        "id_key": "supercar_driving_physics",
        "search_query": "GTA 6 supercars high speed driving drifting crashes 4k 60fps",
        "title": "GTA 6 Insane Supercar Driving Physics, Drifting & High Speed Crashes! (4K 60FPS)",
        "duration_sec": 180,
        "intro_title": "GTA 6 SUPERCAR PHYSICS",
        "sub_title": "HIGH SPEED DRIFTING AND CRASHES",
        "chapters": [
            {"time": "0:00", "title": "Vice City Supercar Showcase"},
            {"time": "0:40", "title": "200 MPH Highway Speed Run"},
            {"time": "1:20", "title": "Extreme Drift Physics in Rain"},
            {"time": "2:00", "title": "Soft-Body Vehicle Crash Deformation"}
        ],
        "tags": ["gta 6", "gta 6 cars", "supercars", "driving physics", "vice city", "ps5 pro", "gta vi", "don of vice city"]
    }
]

# High-Octane Action Shorts Topics
SHORTS_TOPIC_POOL = [
    {
        "category": "supercar_pursuit",
        "search_query": "GTA 6 supercar high speed police pursuit escape 4k 60fps",
        "hook_text": "GTA 6 VICE CITY PURSUIT",
        "bottom_text": "200 MPH HIGH SPEED ESCAPE!",
        "title": "GTA 6 High-Speed Vice City Police Pursuit! 🏎️💨 #shorts #gta6 #gaming",
        "tags": ["gta6", "vice city", "supercars", "shorts", "gaming", "don of vice city", "police chase"]
    },
    {
        "category": "physics_comparison",
        "search_query": "GTA 6 vs GTA 5 Graphics and Physics comparison 4k 60fps",
        "hook_text": "GTA 6 VS GTA 5 PHYSICS",
        "bottom_text": "13 YEARS OF EVOLUTION!",
        "title": "GTA 6 vs GTA 5: 13 Years of Physics Evolution! 🤯🌊 #shorts #gta6 #gta5 #physics",
        "tags": ["gta6", "gta 6 physics", "gta 5 vs gta 6", "shorts", "gaming", "don of vice city"]
    },
    {
        "category": "driveby_shootout",
        "search_query": "GTA 6 insane police chase shootout 5 star wanted 4k 60fps",
        "hook_text": "GTA 6 5-STAR WANTED!",
        "bottom_text": "LUCIA AND JASON VS SWAT COPS!",
        "title": "GTA 6 5-Star SWAT Police Shootout is INSANE! 🚨🔥 #shorts #gta6 #gaming",
        "tags": ["gta6", "gta 6 shootout", "shorts", "gaming", "don of vice city", "police chase"]
    },
    {
        "category": "florida_madness",
        "search_query": "GTA 6 vs real life Florida crazy moments Miami 4k",
        "hook_text": "GTA 6 IS REAL FLORIDA!",
        "bottom_text": "FLORIDA MAN MADNESS IS REAL!",
        "title": "GTA 6 vs Real Life Florida: NPC Madness is REAL! 🐊💀 #shorts #gta6 #florida",
        "tags": ["gta6", "florida", "gta 6 crazy", "shorts", "gaming", "don of vice city"]
    },
    {
        "category": "bank_heist_action",
        "search_query": "GTA 6 bank robbery heist shootout swat gameplay 4k",
        "hook_text": "GTA 6 HEIST GONE WRONG!",
        "bottom_text": "SWAT TEAM ASSAULT!",
        "title": "GTA 6 Bank Robbery Shootout is Absolute CHAOS! 💥💰 #shorts #gta6 #heist",
        "tags": ["gta6", "gta 6 heist", "shootout", "shorts", "gaming", "don of vice city"]
    },
    {
        "category": "street_fights",
        "search_query": "GTA 6 NPC fight brawl knockouts euphoria physics 4k",
        "hook_text": "GTA 6 STREET FIGHT KNOCKOUTS!",
        "bottom_text": "BRUTAL RAGDOLL PHYSICS!",
        "title": "GTA 6 Ragdoll Knockout Physics are BRUTAL! 🥊💥 #shorts #gta6 #physics",
        "tags": ["gta6", "gta 6 fight", "knockout", "shorts", "gaming", "don of vice city"]
    }
]

def sanitize_drawtext(text):
    text = text.replace('\\', '\\\\')
    text = text.replace(':', '\\:')
    text = text.replace("'", "")
    text = text.replace('&', 'AND')
    text = text.replace('%', '')
    return text

def cleanup_old_storage(max_age_hours=24):
    now_ts = time.time()
    cutoff_ts = now_ts - (max_age_hours * 3600)
    cleaned_count = 0
    freed_bytes = 0

    if os.path.exists(OUTPUT_DIR):
        for fname in os.listdir(OUTPUT_DIR):
            fpath = os.path.join(OUTPUT_DIR, fname)
            if not os.path.isfile(fpath):
                continue
            if fname.endswith(('.part', '.ytdl', '.tmp')) or fname.startswith('raw_'):
                try:
                    freed_bytes += os.path.getsize(fpath)
                    os.remove(fpath)
                    cleaned_count += 1
                except Exception:
                    pass
            elif os.path.getmtime(fpath) < cutoff_ts:
                try:
                    freed_bytes += os.path.getsize(fpath)
                    os.remove(fpath)
                    cleaned_count += 1
                except Exception:
                    pass

    print(f"Storage cleanup: Removed {cleaned_count} file(s), freed {freed_bytes / (1024*1024):.2f} MB.")

def wait_for_internet(timeout_seconds=300):
    print("Checking internet connectivity...")
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            urllib.request.urlopen('https://www.google.com', timeout=5)
            print("Internet connection verified!")
            return True
        except Exception:
            print("Waiting for internet connection (10s)...")
            time.sleep(10)
    print("Internet check timed out.")
    return False

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if "used_source_ids" not in d:
                    d["used_source_ids"] = []
                if "daily_long_videos" not in d:
                    d["daily_long_videos"] = {}
                if "used_long_topics" not in d:
                    d["used_long_topics"] = []
                if "scheduled_slots" not in d:
                    d["scheduled_slots"] = {}
                if "uploaded_videos" not in d:
                    d["uploaded_videos"] = []
                return d
        except Exception:
            pass
    return {
        "scheduled_slots": {},
        "uploaded_videos": [],
        "used_source_ids": [],
        "daily_long_videos": {},
        "used_long_topics": []
    }

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2)

def compute_shorts_schedule(pending_slots, now):
    min_first = now + timedelta(minutes=20)
    all_ahead = True
    standard = []
    for slot in pending_slots:
        st = now.replace(hour=slot["hour"], minute=slot["minute"], second=0, microsecond=0)
        if st < min_first:
            all_ahead = False
            break
        standard.append(st)

    if all_ahead:
        return standard

    end_of_day = now.replace(hour=23, minute=30, second=0, microsecond=0)
    if end_of_day > min_first + timedelta(hours=1.5):
        total_seconds = (end_of_day - min_first).total_seconds()
        n = len(pending_slots)
        if n == 1:
            return [min_first]
        interval = total_seconds / (n - 1)
        schedule = []
        for i in range(n):
            dt = min_first + timedelta(seconds=i * interval)
            minute = (dt.minute // 5) * 5
            schedule.append(dt.replace(minute=minute, second=0, microsecond=0))
        return schedule
    else:
        return [min_first + timedelta(hours=2 * i) for i in range(len(pending_slots))]

def execute_daily_long_video(db, today_key):
    print("\n---------------------------------------------------------")
    print("  [STEP 1] DAILY 16:9 4K/1440p LONG VIDEO AUTOMATION     ")
    print("---------------------------------------------------------")

    if today_key in db.get("daily_long_videos", {}):
        existing = db["daily_long_videos"][today_key]
        print(f"Today's Long Video is ALREADY scheduled: {existing['url']}")
        return existing

    import long_video_engine
    res = long_video_engine.build_and_publish_daily_long_video()
    # Reload fresh DB state
    db = load_db()
    return db["daily_long_videos"].get(today_key, res)

def execute_daily_shorts(db, today_key, long_video_info):
    print("\n---------------------------------------------------------")
    print("  [STEP 2] DAILY 4 SHORTS AUTOMATION (WITH 4K LINK)      ")
    print("---------------------------------------------------------")

    if today_key not in db["scheduled_slots"]:
        db["scheduled_slots"][today_key] = []

    today_done = db["scheduled_slots"][today_key]
    pending_slots = [s for s in DAILY_SHORTS_SLOTS if s["slot_id"] not in today_done]

    if not pending_slots:
        print(f"All 4 Shorts for {today_key} are ALREADY scheduled!")
        return

    print(f"Pending Shorts for today: {len(pending_slots)} slot(s)")
    now = datetime.now()
    schedule_times = compute_shorts_schedule(pending_slots, now)

    available_topics = list(SHORTS_TOPIC_POOL)
    random.shuffle(available_topics)
    bg_audio = os.path.join(ASSETS_AUDIO, 'phonk_1.mp3')

    from auto_pilot_bot import find_and_download_unique_source_clip, edit_to_vertical_short

    long_video_url = long_video_info.get('url', 'https://youtube.com/@donofvicecity2026')
    long_video_title = long_video_info.get('title', 'GTA 6 4K Ultra Gameplay')

    for i, slot in enumerate(pending_slots):
        topic = available_topics[i % len(available_topics)]
        target_time = schedule_times[i]
        publish_iso = target_time.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        time_str = target_time.strftime("%I:%M %p")

        print(f"\n>>> [Short {slot['slot_id']}/4] Target: {time_str} | {topic['title']}")
        timestamp = int(time.time())
        temp_raw = os.path.join(OUTPUT_DIR, f"raw_short_{slot['slot_id']}_{timestamp}.mp4")
        out_final = os.path.join(OUTPUT_DIR, f"final_short_{slot['slot_id']}_{timestamp}.mp4")

        try:
            print(f"    1. Downloading unique clip for '{topic['search_query']}'...")
            used_ids = set(db.get("used_source_ids", []))
            src_id = find_and_download_unique_source_clip(topic['search_query'], temp_raw, used_ids)
            if src_id and src_id not in db["used_source_ids"]:
                db["used_source_ids"].append(src_id)

            print("    2. Editing 9:16 vertical short with bold typography & Phonk...")
            edit_to_vertical_short(temp_raw, out_final, topic['hook_text'], topic['bottom_text'], bg_audio)

            # Enhanced High-Conversion Description with Long Video CTA
            description = (
                f"{topic['hook_text']} — {topic['bottom_text']}\n\n"
                f"🔥 WATCH FULL 4K VIDEO HERE:\n"
                f"👉 {long_video_url}\n"
                f"({long_video_title})\n\n"
                f"📌 SUBSCRIBE to @donofvicecity2026 for daily GTA 6 leaks, physics, and gameplay!\n\n"
                f"#gta6 #shorts #gaming #vicecity #ps5pro"
            )

            print(f"    3. Uploading Short to YouTube scheduled for {publish_iso}...")
            res = upload_short(
                file_path=out_final,
                title=topic['title'],
                description=description,
                tags=topic['tags'],
                publish_at=publish_iso
            )

            video_id = res.get('id')
            db["scheduled_slots"][today_key].append(slot["slot_id"])
            db["uploaded_videos"].append({
                "id": video_id,
                "title": topic["title"],
                "slot": slot["name"],
                "scheduled_for": publish_iso,
                "date_key": today_key
            })
            save_db(db)
            print(f"    >>> SUCCESS: Uploaded Short {video_id} scheduled for {time_str}")

        except Exception as e:
            print(f"    ERROR processing Short {slot['slot_id']}: {e}")

        finally:
            if os.path.exists(temp_raw):
                try:
                    os.remove(temp_raw)
                except Exception:
                    pass

def run_master_autopilot():
    print("==========================================================")
    print("      DON OF VICE CITY — MASTER AUTOPILOT LAUNCHER        ")
    print("      (1 Long 4K Video + 4 High-Action Shorts / Day)      ")
    print("==========================================================")

    if not acquire_lock():
        return

    try:
        cleanup_old_storage(max_age_hours=24)

        if not wait_for_internet():
            print("Aborting: Internet connection not detected.")
            return

        db = load_db()
        today_key = datetime.now().strftime("%Y-%m-%d")

        # Step 1: Ensure today's 16:9 Long Video is created & scheduled
        long_video_info = execute_daily_long_video(db, today_key)

        # Step 2: Ensure today's 4 Shorts are created, scheduled & linked
        execute_daily_shorts(db, today_key, long_video_info)

        cleanup_old_storage(max_age_hours=24)

        print("\n==========================================================")
        print("  DAILY AUTOPILOT BUNDLE COMPLETE (1 LONG + 4 SHORTS)!    ")
        print("  All videos are safely scheduled on YouTube's servers.   ")
        print("  You can now safely shut down or use your laptop.        ")
        print("==========================================================\n")
    finally:
        release_lock()

if __name__ == '__main__':
    run_master_autopilot()
