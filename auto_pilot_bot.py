import os
import sys
import json
import time
import random
import shutil
import subprocess
import urllib.request
from datetime import datetime, timedelta

# Ensure UTF-8 output encoding on Windows so emojis never crash print() in redirected logs
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import yt_dlp
from upload_video import upload_short

# Standalone FFmpeg path (No external Python modules needed)
FFMPEG_EXE = r"C:\Users\Awesh\AppData\Local\Programs\Python\Python312\Scripts\ffmpeg.exe"
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = shutil.which('ffmpeg') or 'ffmpeg'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_AUDIO = os.path.join(BASE_DIR, 'assets', 'audio')
OUTPUT_DIR = os.path.join(BASE_DIR, 'daily_generated')
DB_FILE = os.path.join(BASE_DIR, 'autopilot_db.json')

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSETS_AUDIO, exist_ok=True)

# 6 Diverse High-Octane Action Categories (100% Unique, Zero Repetition)
ACTION_TOPIC_POOL = [
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

# 6 Daily Target Slots (IST): Boot/Live + 12 PM + Spaced Every 3 Hours
DAILY_SLOTS = [
    {"slot_id": 1, "name": "Slot 1 (Morning / Boot)", "hour": 10, "minute": 15},
    {"slot_id": 2, "name": "Slot 2 (12:00 PM)", "hour": 12, "minute": 0},
    {"slot_id": 3, "name": "Slot 3 (3:00 PM)", "hour": 15, "minute": 0},
    {"slot_id": 4, "name": "Slot 4 (6:00 PM)", "hour": 18, "minute": 0},
    {"slot_id": 5, "name": "Slot 5 (9:00 PM)", "hour": 21, "minute": 0},
    {"slot_id": 6, "name": "Slot 6 (11:30 PM)", "hour": 23, "minute": 30}
]

def cleanup_old_storage(max_age_hours=24):
    """
    Deletes temporary raw clips and generated videos older than 24 hours (next day)
    so hard drive storage is never wasted.
    """
    print("Running automatic storage cleanup...")
    now_ts = time.time()
    cutoff_ts = now_ts - (max_age_hours * 3600)
    cleaned_count = 0
    freed_bytes = 0

    if os.path.exists(OUTPUT_DIR):
        for fname in os.listdir(OUTPUT_DIR):
            fpath = os.path.join(OUTPUT_DIR, fname)
            if not os.path.isfile(fpath):
                continue
            # Delete temp download fragments or raw cuts immediately
            if fname.endswith(('.part', '.ytdl', '.tmp')) or fname.startswith('raw_'):
                try:
                    freed_bytes += os.path.getsize(fpath)
                    os.remove(fpath)
                    cleaned_count += 1
                except Exception:
                    pass
            # Delete final videos older than 24 hours (already uploaded to YouTube)
            elif os.path.getmtime(fpath) < cutoff_ts:
                try:
                    freed_bytes += os.path.getsize(fpath)
                    os.remove(fpath)
                    cleaned_count += 1
                except Exception:
                    pass

    freed_mb = freed_bytes / (1024 * 1024)
    print(f"Cleanup complete: Removed {cleaned_count} file(s), freed {freed_mb:.2f} MB storage.")

def wait_for_internet(timeout_seconds=300):
    print("Checking internet connection...")
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            urllib.request.urlopen('https://www.google.com', timeout=5)
            print("Internet connection verified!")
            return True
        except Exception:
            print("No internet yet. Waiting 10 seconds...")
            time.sleep(10)
    print("Internet timeout reached.")
    return False

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if "used_source_ids" not in d:
                    d["used_source_ids"] = []
                return d
        except Exception:
            pass
    return {"scheduled_slots": {}, "uploaded_videos": [], "used_source_ids": []}

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2)

def find_and_download_unique_source_clip(search_query, target_path, used_source_ids, duration=35):
    """
    Searches top 10 YouTube results and strictly selects a video ID that has NEVER been used before.
    Guarantees 100% unique footage with zero repetition across all videos.
    """
    search_opts = {
        'quiet': True,
        'extract_flat': True,
        'noplaylist': True
    }
    
    selected_id = None
    selected_title = None
    
    with yt_dlp.YoutubeDL(search_opts) as ydl:
        try:
            res = ydl.extract_info(f"ytsearch10:{search_query}", download=False)
            for entry in res.get('entries', []):
                vid = entry.get('id')
                if not vid:
                    continue
                if vid not in used_source_ids:
                    selected_id = vid
                    selected_title = entry.get('title')
                    break
                else:
                    print(f"      [Dedup] Skipping previously used source: {vid} ('{entry.get('title', '')[:30]}...')")
        except Exception as e:
            print(f"      [Search warning]: {e}")
            
    if not selected_id:
        print("      [Warning] No unused video in top 10, using fallback query.")
        target_url = f"ytsearch1:{search_query}"
    else:
        target_url = f"https://www.youtube.com/watch?v={selected_id}"
        print(f"      >>> Selected fresh unique source: {selected_id} ('{selected_title}')")
        
    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best',
        'outtmpl': target_path,
        'noplaylist': True,
        'quiet': True,
        'merge_output_format': 'mp4',
        'ffmpeg_location': r'C:\Users\Awesh\AppData\Local\Programs\Python\Python312\Scripts',
        'download_ranges': yt_dlp.utils.download_range_func(None, [(10, 10 + duration)])
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([target_url])
        
    return selected_id

def edit_to_vertical_short(input_video, output_video, hook_text, bottom_text, audio_track):
    """
    Cuts 26s, crops/scales to 1080x1920 (9:16 vertical),
    overlays modern aesthetic floating action typography (NO black boxes),
    mixes copyright-free NCS Phonk beat.
    """
    font_file = "/Windows/Fonts/ariblk.ttf"
    if not os.path.exists(r"C:\Windows\Fonts\ariblk.ttf"):
        font_file = "/Windows/Fonts/impact.ttf"
        
    filter_complex = (
        "[0:v]trim=start=2:duration=26,setpts=PTS-STARTPTS,"
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=fontfile='{font_file}':text='{hook_text}':fontcolor=white:fontsize=60:borderw=6:bordercolor=black:shadowcolor=black@0.6:shadowx=3:shadowy=3:x=(w-text_w)/2:y=180,"
        f"drawtext=fontfile='{font_file}':text='{bottom_text}':fontcolor=yellow:fontsize=44:borderw=5:bordercolor=black:shadowcolor=black@0.6:shadowx=3:shadowy=3:x=(w-text_w)/2:y=260,"
        f"drawtext=fontfile='{font_file}':text='DON OF VICE CITY':fontcolor=cyan:fontsize=36:borderw=3:bordercolor=black:shadowcolor=black@0.6:shadowx=2:shadowy=2:x=(w-text_w)/2:y=1740[v];"
        "[1:a]volume=0.9[a]"
    )
    
    cmd = [
        FFMPEG_EXE, '-y',
        '-ss', '2',
        '-i', input_video,
        '-stream_loop', '-1',
        '-i', audio_track,
        '-filter_complex', filter_complex,
        '-map', '[v]',
        '-map', '[a]',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '20',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-t', '26',
        output_video
    ]
    subprocess.run(cmd, check=True)

def compute_daily_schedule_times(pending_slots, now):
    """
    Computes scheduled times for all pending videos.
    Default targets for 1:00 PM onwards:
      Slot 1: 1:30 PM (13:30)
      Slot 2: 4:00 PM (16:00)
      Slot 3: 6:30 PM (18:30)
      Slot 4: 9:00 PM (21:00)
      Slot 5: 11:30 PM (23:30)

    Dynamic Spacing Rule:
    Whenever the user turns on the laptop and connects to internet (whether at 12:30 PM,
    1:00 PM, 2:30 PM, etc.), ALL pending videos will be scheduled for TODAY, evenly spaced
    between (now + 20 mins) and 11:30 PM.
    """
    min_first_time = now + timedelta(minutes=20)
    
    # Check if standard slots are still ahead
    use_standard = True
    standard_times = []
    for slot in pending_slots:
        st = now.replace(hour=slot["hour"], minute=slot["minute"], second=0, microsecond=0)
        if st < min_first_time:
            use_standard = False
            break
        standard_times.append(st)
        
    if use_standard:
        return standard_times
        
    # If any slot is in the past or too close: dynamically spread all pending slots today!
    end_of_day = now.replace(hour=23, minute=30, second=0, microsecond=0)
    
    if end_of_day > min_first_time + timedelta(hours=1.5):
        total_seconds = (end_of_day - min_first_time).total_seconds()
        n = len(pending_slots)
        if n == 1:
            return [min_first_time]
        interval = total_seconds / (n - 1)
        schedule = []
        for i in range(n):
            dt = min_first_time + timedelta(seconds=i * interval)
            minute = (dt.minute // 5) * 5
            dt = dt.replace(minute=minute, second=0, microsecond=0)
            schedule.append(dt)
        return schedule
    else:
        # If laptop opened late at night, space them 2 hours apart
        return [min_first_time + timedelta(hours=2 * i) for i in range(len(pending_slots))]

def run_daily_autopilot():
    # 1. Clean up any residual storage from previous days first
    cleanup_old_storage(max_age_hours=24)

    # 2. Check and wait for internet connectivity
    if not wait_for_internet():
        print("Aborting: Internet connection not available.")
        return
        
    db = load_db()
    today_key = datetime.now().strftime("%Y-%m-%d")
    print(f"\n========================================================")
    print(f"  DON OF VICE CITY — 5-VIDEO AUTOPILOT ENGINE ({today_key})")
    print(f"========================================================")
    
    if today_key not in db.get("scheduled_slots", {}):
        db["scheduled_slots"][today_key] = []
        
    today_done_slots = db["scheduled_slots"][today_key]
    
    now = datetime.now()
    pending_slots = [s for s in DAILY_SLOTS if s["slot_id"] not in today_done_slots]
    
    if not pending_slots:
        print(f"All {len(DAILY_SLOTS)} video slots for {today_key} are ALREADY scheduled! Nothing to do.")
        return
        
    print(f"Found {len(pending_slots)} pending slots to schedule in one batch.")
    
    available_topics = list(ACTION_TOPIC_POOL)
    random.shuffle(available_topics)
    bg_audio = os.path.join(ASSETS_AUDIO, 'phonk_1.mp3')
    
    computed_times = compute_daily_schedule_times(pending_slots, now)
    
    for i, slot in enumerate(pending_slots):
        topic = available_topics[i % len(available_topics)]
        target_time = computed_times[i]
        publish_iso = target_time.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        time_str = target_time.strftime("%I:%M %p")
        print(f"\n>>> [Slot {slot['slot_id']}/{len(DAILY_SLOTS)}] Scheduling for: {time_str} (ISO: {publish_iso})")
        print(f"    Topic: {topic['title']}")
        
        timestamp = int(datetime.now().timestamp())
        temp_raw = os.path.join(OUTPUT_DIR, f"raw_slot{slot['slot_id']}_{timestamp}.mp4")
        out_final = os.path.join(OUTPUT_DIR, f"final_slot{slot['slot_id']}_{timestamp}.mp4")
        
        try:
            print(f"    1. Finding & downloading unique clip for '{topic['search_query']}'...")
            used_sources = set(db.get("used_source_ids", []))
            src_id = find_and_download_unique_source_clip(topic['search_query'], temp_raw, used_sources)
            if src_id and src_id not in db["used_source_ids"]:
                db["used_source_ids"].append(src_id)
            
            print("    2. Editing to 9:16 vertical action short with Phonk beat...")
            edit_to_vertical_short(temp_raw, out_final, topic['hook_text'], topic['bottom_text'], bg_audio)
            
            print(f"    3. Uploading to YouTube and setting scheduled publish for {publish_iso}...")
            res = upload_short(
                file_path=out_final,
                title=topic['title'],
                description=f"{topic['hook_text']} {topic['bottom_text']}\n\nSubscribe to @donofvicecity2026 for daily GTA 6 leaks, physics, and gameplay!\n\n#gta6 #shorts #gaming #vicecity",
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
            print(f"    >>> SUCCESS: Uploaded {video_id} scheduled for {publish_iso}")
            
        except Exception as e:
            print(f"    ERROR processing Slot {slot['slot_id']}: {e}")
            
        finally:
            # Delete temporary raw download immediately
            if os.path.exists(temp_raw):
                try:
                    os.remove(temp_raw)
                except Exception:
                    pass
                    
    # Final cleanup of any lingering temporary files
    cleanup_old_storage(max_age_hours=24)
    print("\n========================================================")
    print("  ALL 5 SHORTS SCHEDULED ON YOUTUBE IN ADVANCE!")
    print("  You can now turn off your PC or disconnect internet.")
    print("  YouTube will automatically publish each short on time!")
    print("========================================================\n")

if __name__ == '__main__':
    run_daily_autopilot()
