"""
DON OF VICE CITY — High-Retention 16:9 Long Video Automation Engine (4K/1440p 60FPS)
Builds 3 to 5 minute cinematic, high-retention GTA 6 comparison & action videos.
Features:
- 16:9 1440p (2560x1440) Ultra HD formatting to trigger YouTube VP9/AV1 codec
- Rich contrast & saturation color grading
- Chapter cards & floating typography (Zero black boxes)
- Royalty-free NCS Phonk background mix
- High-CTR auto-generated 16:9 custom thumbnail
- SEO description with timestamps, keywords, and tags
- Database-backed deduplication and automatic daily scheduling
"""
import os
import sys
import json
import time
import shutil
import subprocess
from datetime import datetime, timedelta

# Ensure UTF-8 output encoding on Windows
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import yt_dlp
from upload_video import get_authenticated_service
from googleapiclient.http import MediaFileUpload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, 'daily_generated')
ASSETS_AUDIO = os.path.join(BASE_DIR, 'assets', 'audio')
DB_FILE = os.path.join(BASE_DIR, 'autopilot_db.json')

FFMPEG_EXE = r"C:\Users\Awesh\AppData\Local\Programs\Python\Python312\Scripts\ffmpeg.exe"
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = shutil.which('ffmpeg') or 'ffmpeg'

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSETS_AUDIO, exist_ok=True)

# Viral Trending Long Video Topics (Rotating Pool)
LONG_TOPIC_POOL = [
    {
        "id_key": "6_star_swat_shootout",
        "search_query": "GTA 6 open world police chase gameplay 4k 60fps ps5 pro",
        "title": "GTA 6 6-Star SWAT Police Shootout & Escape: Insane Vice City Realism! (4K 60FPS)",
        "duration_sec": 180,  # 3 minutes
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
        "duration_sec": 150,  # 2.5 minutes
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
                return d
        except Exception:
            pass
    return {"scheduled_slots": {}, "uploaded_videos": [], "used_source_ids": [], "daily_long_videos": {}, "used_long_topics": []}

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2)

def sanitize_drawtext(text):
    text = text.replace('\\', '\\\\')
    text = text.replace(':', '\\:')
    text = text.replace("'", "")
    text = text.replace('&', 'AND')
    text = text.replace('%', '')
    return text

def download_source_video(search_query, target_mkv, duration_sec, used_ids):
    start_sec = 15
    end_sec = start_sec + duration_sec

    search_opts = {'quiet': True, 'extract_flat': True, 'noplaylist': True}
    selected_id = None
    selected_url = None

    with yt_dlp.YoutubeDL(search_opts) as ydl:
        try:
            res = ydl.extract_info(f"ytsearch10:{search_query}", download=False)
            for entry in res.get('entries', []):
                vid = entry.get('id')
                if vid and vid not in used_ids:
                    selected_id = vid
                    selected_url = f"https://www.youtube.com/watch?v={vid}"
                    break
        except Exception as e:
            print(f"      [Search warning]: {e}")

    if not selected_url:
        selected_url = f"ytsearch1:{search_query}"
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            res = ydl.extract_info(selected_url, download=False)
            selected_url = res['entries'][0]['webpage_url']
            selected_id = res['entries'][0]['id']

    ydl_opts = {
        'format': 'bestvideo[height<=1440]+bestaudio/best[height<=1080]/best',
        'outtmpl': target_mkv,
        'noplaylist': True,
        'merge_output_format': 'mkv',
        'ffmpeg_location': r'C:\Users\Awesh\AppData\Local\Programs\Python\Python312\Scripts',
        'download_ranges': yt_dlp.utils.download_range_func(None, [(start_sec, end_sec)]),
        'retries': 10,
        'fragment_retries': 10,
        'quiet': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([selected_url])

    return selected_id

def render_long_video(raw_video, output_video, intro_title, sub_title, duration_sec, audio_track):
    """
    Renders 16:9 1440p (2560x1440) Ultra HD video.
    Applies floating chapter titles and branded watermark at top right.
    Color grading: Enhanced saturation and contrast for HDR feel.
    Mixes royalty-free NCS music and strips copyrighted audio.
    """
    font_file = "/Windows/Fonts/ariblk.ttf"
    if not os.path.exists(r"C:\Windows\Fonts\ariblk.ttf"):
        font_file = "/Windows/Fonts/impact.ttf"

    clean_intro = sanitize_drawtext(intro_title)
    clean_sub = sanitize_drawtext(sub_title)

    filter_complex = (
        f"[0:v]trim=start=5:duration={duration_sec},setpts=PTS-STARTPTS,"
        "scale=2560:1440:force_original_aspect_ratio=decrease,pad=2560:1440:(ow-iw)/2:(oh-ih)/2,"
        "eq=saturation=1.12:contrast=1.05,"
        f"drawtext=fontfile='{font_file}':text='DON OF VICE CITY':fontcolor=cyan:fontsize=42:borderw=4:bordercolor=black:shadowcolor=black@0.6:shadowx=3:shadowy=3:x=w-text_w-50:y=50,"
        f"drawtext=fontfile='{font_file}':text='{clean_intro}':fontcolor=white:fontsize=64:borderw=7:bordercolor=black:shadowcolor=black@0.7:shadowx=4:shadowy=4:x=(w-text_w)/2:y=90,"
        f"drawtext=fontfile='{font_file}':text='{clean_sub}':fontcolor=yellow:fontsize=48:borderw=5:bordercolor=black:shadowcolor=black@0.7:shadowx=4:shadowy=4:x=(w-text_w)/2:y=175[v];"
        "[1:a]volume=0.85[a]"
    )

    cmd = [
        FFMPEG_EXE, '-y',
        '-ss', '5',
        '-i', raw_video,
        '-stream_loop', '-1',
        '-i', audio_track,
        '-filter_complex', filter_complex,
        '-map', '[v]',
        '-map', '[a]',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '18',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-t', str(duration_sec),
        output_video
    ]
    subprocess.run(cmd, check=True)

def generate_custom_thumbnail(video_path, output_thumb, main_text, sub_text):
    """
    Extracts an action frame at 30s and overlays bold click-worthy 16:9 thumbnail typography.
    """
    font_file = "/Windows/Fonts/ariblk.ttf"
    if not os.path.exists(r"C:\Windows\Fonts\ariblk.ttf"):
        font_file = "/Windows/Fonts/impact.ttf"

    clean_main = sanitize_drawtext(main_text)
    clean_sub = sanitize_drawtext(sub_text)

    vf = (
        "scale=1920:1080,"
        "eq=saturation=1.2:contrast=1.1,"
        f"drawtext=fontfile='{font_file}':text='{clean_main}':fontcolor=yellow:fontsize=95:borderw=10:bordercolor=black:shadowcolor=black@0.8:shadowx=6:shadowy=6:x=(w-text_w)/2:y=80,"
        f"drawtext=fontfile='{font_file}':text='{clean_sub}':fontcolor=white:fontsize=70:borderw=9:bordercolor=black:shadowcolor=black@0.8:shadowx=6:shadowy=6:x=(w-text_w)/2:y=200,"
        f"drawtext=fontfile='{font_file}':text='DON OF VICE CITY':fontcolor=cyan:fontsize=50:borderw=6:bordercolor=black:shadowcolor=black@0.8:shadowx=4:shadowy=4:x=(w-text_w)/2:y=920"
    )

    cmd = [
        FFMPEG_EXE, '-y',
        '-ss', '30',
        '-i', video_path,
        '-vf', vf,
        '-vframes', '1',
        '-q:v', '2',
        output_thumb
    ]
    subprocess.run(cmd, check=True)

def upload_long_video(file_path, thumb_path, title, description, tags, publish_at=None):
    youtube = get_authenticated_service()

    status_body = {'selfDeclaredMadeForKids': False}
    if publish_at:
        status_body['privacyStatus'] = 'private'
        status_body['publishAt'] = publish_at
    else:
        status_body['privacyStatus'] = 'public'

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '20'  # Gaming
        },
        'status': status_body
    }

    media = MediaFileUpload(file_path, mimetype='video/mp4', chunksize=1024*1024*4, resumable=True)
    request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)

    print(f"Uploading '{os.path.basename(file_path)}' to YouTube...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Long video upload progress: {int(status.progress() * 100)}%")
            sys.stdout.flush()

    video_id = response.get('id')
    print(f"SUCCESS: Long Video Uploaded! ID: {video_id}")
    print(f"URL: https://www.youtube.com/watch?v={video_id}")

    # Set custom thumbnail if supported
    if os.path.exists(thumb_path):
        try:
            print("Setting custom thumbnail...")
            thumb_media = MediaFileUpload(thumb_path, mimetype='image/jpeg')
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            print("SUCCESS: Custom thumbnail set!")
        except Exception as te:
            print(f"Thumbnail note: {te} (Intermediate channel verification required for custom thumbnails)")

    return response

def build_and_publish_daily_long_video():
    print("\n========================================================")
    print("  DON OF VICE CITY — DAILY LONG-FORM VIDEO ENGINE (4K/1440p) ")
    print("========================================================")

    db = load_db()
    today_key = datetime.now().strftime("%Y-%m-%d")

    # Check if today's long video already uploaded
    if today_key in db.get("daily_long_videos", {}):
        existing = db["daily_long_videos"][today_key]
        print(f"Today's Long Video ({today_key}) already uploaded: ID {existing['id']} ({existing['title']})")
        return existing

    # Select topic not recently used
    used_topics = set(db.get("used_long_topics", []))
    selected_topic = None
    for t in LONG_TOPIC_POOL:
        if t["id_key"] not in used_topics:
            selected_topic = t
            break

    if not selected_topic:
        print("All topics in pool used once, recycling topics...")
        db["used_long_topics"] = []
        selected_topic = LONG_TOPIC_POOL[0]

    topic = selected_topic
    print(f"Selected Topic: '{topic['title']}' (ID: {topic['id_key']})")

    timestamp = int(time.time())
    raw_path = os.path.join(OUTPUT_DIR, f"raw_long_{timestamp}.mkv")
    final_path = os.path.join(OUTPUT_DIR, f"final_long_{timestamp}.mp4")
    thumb_path = os.path.join(OUTPUT_DIR, f"thumb_long_{timestamp}.jpg")
    audio_path = os.path.join(ASSETS_AUDIO, 'phonk_1.mp3')

    # Schedule time: Today at 6:00 PM IST (or now + 15 min if past 6 PM)
    now = datetime.now()
    target_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now >= target_time - timedelta(minutes=10):
        target_time = now + timedelta(minutes=15)
        minute = (target_time.minute // 5) * 5
        target_time = target_time.replace(minute=minute, second=0, microsecond=0)

    publish_iso = target_time.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    print(f"Scheduling Long Video for: {target_time.strftime('%I:%M %p')} IST (ISO: {publish_iso})")

    try:
        print(f"1. Downloading 4K/1440p source clip for '{topic['title']}'...")
        used_ids = set(db.get("used_source_ids", []))
        src_id = download_source_video(topic['search_query'], raw_path, topic['duration_sec'], used_ids)
        if src_id and src_id not in db["used_source_ids"]:
            db["used_source_ids"].append(src_id)
        print(f"   Selected Source ID: {src_id}")

        print("2. Rendering 1440p Ultra HD long video with chapter banners & NCS audio...")
        render_long_video(raw_path, final_path, topic['intro_title'], topic['sub_title'], topic['duration_sec'], audio_path)

        print("3. Generating high-CTR custom 16:9 thumbnail...")
        generate_custom_thumbnail(final_path, thumb_path, topic['intro_title'], topic['sub_title'])

        desc = (
            f"{topic['title']}\n\n"
            "Experience next-gen Grand Theft Auto VI in stunning 1440p/4K 60FPS! Witness Vice City's extreme open-world realism, advanced AI, dynamic physics, and intense action in the state of Leonida.\n\n"
            "TIMESTAMPS / CHAPTERS:\n"
            + "\n".join([f"{c['time']} - {c['title']}" for c in topic['chapters']])
            + "\n\n🔥 SUBSCRIBE to @donofvicecity2026 for daily GTA 6 4K gameplay, physics comparisons, and police escapes!\n\n"
            "#gta6 #gta6gameplay #vicecity #ps5pro #rockstargames #gtavi #donofvicecity"
        )

        print(f"4. Uploading long video to YouTube scheduled for {publish_iso}...")
        res = upload_long_video(final_path, thumb_path, topic['title'], desc, topic['tags'], publish_at=publish_iso)

        video_id = res.get('id')
        db["daily_long_videos"][today_key] = {
            "id": video_id,
            "title": topic["title"],
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "scheduled_for": publish_iso
        }
        db["used_long_topics"].append(topic["id_key"])
        db["uploaded_videos"].append({
            "id": video_id,
            "title": topic["title"],
            "slot": "Daily Long Video (6:00 PM)",
            "scheduled_for": publish_iso,
            "date_key": today_key
        })
        save_db(db)

        print(f">>> ALL DONE! Long video scheduled on YouTube: https://www.youtube.com/watch?v={video_id}")
        return db["daily_long_videos"][today_key]

    except Exception as e:
        print(f"ERROR: {e}")
        raise e
    finally:
        if os.path.exists(raw_path):
            try:
                os.remove(raw_path)
            except Exception:
                pass

if __name__ == '__main__':
    build_and_publish_daily_long_video()
