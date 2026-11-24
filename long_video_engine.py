"""
DON OF VICE CITY — Long Video Engine (Refactored)
Generates 16:9 1440p Ultra HD long-form videos with chapters, watermarks, and NCS audio.
"""
import os
import sys
import time
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import yt_dlp

# Local imports
from config_loader import get_config, ConfigLoader
from utils import (
    load_db, save_db, get_ffmpeg_exe, run_ffmpeg, sanitize_drawtext,
    wait_for_internet, format_iso_ist, get_timestamp, get_date_key,
    get_audio_track, ensure_output_dirs, cleanup_old_files
)
from upload_video import upload_long_video, get_quota_report

log = logging.getLogger("long_video_engine")


# ============================================================================
# VIDEO DOWNLOAD
# ============================================================================
def download_source_video(
    search_query: str,
    target_path: str,
    duration_sec: int,
    used_ids: set,
    start_offset: int = 5
) -> Optional[str]:
    """
    Search YouTube and download a unique source clip.

    Args:
        search_query: YouTube search query
        target_path: Output file path
        duration_sec: Duration to download
        used_ids: Set of already used video IDs
        start_offset: Seconds to skip from start

    Returns:
        Selected video ID or None if failed
    """
    cfg = get_config()
    download_cfg = cfg.download

    # Search for fresh video
    search_opts = {
        'quiet': True,
        'extract_flat': True,
        'noplaylist': True
    }

    selected_id = None
    selected_url = None

    with yt_dlp.YoutubeDL(search_opts) as ydl:
        try:
            res = ydl.extract_info(f"ytsearch{download_cfg['search']['max_results']}:{search_query}", download=False)
            for entry in res.get('entries', []):
                vid = entry.get('id')
                if vid and vid not in used_ids:
                    selected_id = vid
                    selected_url = f"https://www.youtube.com/watch?v={vid}"
                    log.info(f"Selected fresh source: {vid} ('{entry.get('title', '')[:50]}')")
                    break
                else:
                    log.debug(f"Skipping used source: {vid}")
        except Exception as e:
            log.warning(f"Search warning: {e}")

    # Fallback if no fresh video found
    if not selected_url:
        log.warning("No unused video in search results, using fallback query")
        selected_url = f"ytsearch1:{search_query}"
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            res = ydl.extract_info(selected_url, download=False)
            selected_id = res['entries'][0]['id']
            selected_url = res['entries'][0]['webpage_url']

    # Download with trimming
    end_sec = start_offset + duration_sec

    ydl_opts = {
        'format': download_cfg['format']['long'],
        'outtmpl': target_path,
        'noplaylist': True,
        'merge_output_format': download_cfg['merge_output_format']['long'],
        'ffmpeg_location': os.path.dirname(get_ffmpeg_exe()),
        'download_ranges': yt_dlp.utils.download_range_func(None, [(start_offset, end_sec)]),
        'retries': download_cfg['retries'],
        'fragment_retries': download_cfg['fragment_retries'],
        'quiet': True
    }

    log.info(f"Downloading {duration_sec}s clip from {selected_url} (offset {start_offset}s)...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([selected_url])

    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Download failed: {target_path} not created")

    log.info(f"Downloaded: {os.path.getsize(target_path) / 1024 / 1024:.1f} MB")
    return selected_id


# ============================================================================
# VIDEO RENDERING
# ============================================================================
def render_long_video(
    raw_video: str,
    output_video: str,
    intro_title: str,
    sub_title: str,
    duration_sec: int,
    audio_track: str
) -> None:
    """
    Render 16:9 1440p Ultra HD video with:
    - Color grading (saturation/contrast boost)
    - Floating chapter titles (no black boxes)
    - Branded watermark
    - Royalty-free audio mix
    """
    cfg = get_config()
    video_cfg = cfg.video
    font_file = video_cfg.font_primary
    if not os.path.exists(font_file):
        font_file = video_cfg.font_fallback

    # Sanitize texts
    clean_intro = sanitize_drawtext(intro_title)
    clean_sub = sanitize_drawtext(sub_title)
    watermark = video_cfg.long_watermark

    # Build filter complex
    filter_parts = [
        # Video processing chain
        f"[0:v]trim=start=5:duration={duration_sec},setpts=PTS-STARTPTS,"
        f"scale={video_cfg.long_resolution}:force_original_aspect_ratio=decrease,"
        f"pad={video_cfg.long_resolution}:(ow-iw)/2:(oh-ih)/2,"
        f"eq=saturation={video_cfg.long_saturation}:contrast={video_cfg.long_contrast},"
    ]

    # Watermark (top right)
    wm_text = watermark.get('text', 'DON OF VICE CITY')
    wm_color = watermark.get('color', 'cyan')
    wm_size = watermark.get('font_size', 42)
    wm_margin = watermark.get('margin', 50)

    filter_parts.append(
        f"drawtext=fontfile='{font_file}':"
        f"text='{sanitize_drawtext(wm_text)}':"
        f"fontcolor={wm_color}:fontsize={wm_size}:"
        f"borderw=4:bordercolor=black:"
        f"shadowcolor=black@0.6:shadowx=3:shadowy=3:"
        f"x=w-text_w-{wm_margin}:y={wm_margin},"
    )

    # Intro title (center top)
    filter_parts.append(
        f"drawtext=fontfile='{font_file}':"
        f"text='{clean_intro}':"
        f"fontcolor=white:fontsize=64:"
        f"borderw=7:bordercolor=black:"
        f"shadowcolor=black@0.7:shadowx=4:shadowy=4:"
        f"x=(w-text_w)/2:y=90,"
    )

    # Sub title (below intro)
    filter_parts.append(
        f"drawtext=fontfile='{font_file}':"
        f"text='{clean_sub}':"
        f"fontcolor=yellow:fontsize=48:"
        f"borderw=5:bordercolor=black:"
        f"shadowcolor=black@0.7:shadowx=4:shadowy=4:"
        f"x=(w-text_w)/2:y=175[v];"
    )

    # Audio mix
    filter_parts.append(f"[1:a]volume={video_cfg.long_audio_volume}[a]")

    filter_complex = "".join(filter_parts)

    cmd = [
        '-y',
        '-ss', '5',
        '-i', raw_video,
        '-stream_loop', '-1',
        '-i', audio_track,
        '-filter_complex', filter_complex,
        '-map', '[v]',
        '-map', '[a]',
        '-c:v', 'libx264',
        '-preset', video_cfg.long_preset,
        '-crf', str(video_cfg.long_crf),
        '-c:a', 'aac',
        '-b:a', video_cfg.long_audio_bitrate,
        '-t', str(duration_sec),
        output_video
    ]

    run_ffmpeg(cmd, "Long video render")


def generate_custom_thumbnail(
    video_path: str,
    output_thumb: str,
    main_text: str,
    sub_text: str
) -> None:
    """
    Generate high-CTR 16:9 thumbnail from video frame at 30s.
    """
    cfg = get_config()
    video_cfg = cfg.video
    font_file = video_cfg.font_primary
    if not os.path.exists(font_file):
        font_file = video_cfg.font_fallback

    clean_main = sanitize_drawtext(main_text)
    clean_sub = sanitize_drawtext(sub_text)

    vf = (
        f"scale=1920:1080,"
        f"eq=saturation=1.2:contrast=1.1,"
        f"drawtext=fontfile='{font_file}':text='{clean_main}':fontcolor=yellow:fontsize=95:borderw=10:bordercolor=black:shadowcolor=black@0.8:shadowx=6:shadowy=6:x=(w-text_w)/2:y=80,"
        f"drawtext=fontfile='{font_file}':text='{clean_sub}':fontcolor=white:fontsize=70:borderw=9:bordercolor=black:shadowcolor=black@0.8:shadowx=6:shadowy=6:x=(w-text_w)/2:y=200,"
        f"drawtext=fontfile='{font_file}':text='DON OF VICE CITY':fontcolor=cyan:fontsize=50:borderw=6:bordercolor=black:shadowcolor=black@0.8:shadowx=4:shadowy=4:x=(w-text_w)/2:y=920"
    )

    cmd = [
        '-y',
        '-ss', '30',
        '-i', video_path,
        '-vf', vf,
        '-vframes', '1',
        '-q:v', '2',
        output_thumb
    ]

    run_ffmpeg(cmd, "Thumbnail generation")


# ============================================================================
# MAIN ORCHESTRATION
# ============================================================================
def build_and_publish_daily_long_video(channel_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Main function to build and schedule daily long video.
    Returns dict with video info.
    """
    log.info("=" * 60)
    log.info("  DON OF VICE CITY — DAILY LONG VIDEO ENGINE (1440p)")
    log.info("=" * 60)

    cfg = get_config()
    ensure_output_dirs()

    db = load_db()
    today_key = get_date_key()

    # Check if already done today
    if today_key in db.get("daily_long_videos", {}):
        existing = db["daily_long_videos"][today_key]
        log.info(f"Today's long video already scheduled: {existing['url']}")
        return existing

    # Select topic not recently used
    used_topics = set(db.get("used_long_topics", []))
    selected_topic = None

    for topic in cfg.long_video_pool:
        if topic["id_key"] not in used_topics:
            selected_topic = topic
            break

    if not selected_topic:
        log.info("All topics used, recycling...")
        db["used_long_topics"] = []
        save_db(db)
        selected_topic = cfg.long_video_pool[0]

    topic = selected_topic
    log.info(f"Selected topic: {topic['title']} (ID: {topic['id_key']})")

    # Schedule time: Today at 6:00 PM IST
    now = datetime.now()
    target_time = now.replace(hour=cfg.schedule.long_video_hour, minute=cfg.schedule.long_video_minute, second=0, microsecond=0)

    min_lead = timedelta(minutes=cfg.schedule.long_min_lead_minutes)
    if now >= target_time - min_lead:
        target_time = now + min_lead
        # Round to nearest 5 minutes
        minute = (target_time.minute // cfg.schedule.long_round_minutes) * cfg.schedule.long_round_minutes
        target_time = target_time.replace(minute=minute, second=0, microsecond=0)

    publish_iso = format_iso_ist(target_time)
    log.info(f"Scheduling for: {target_time.strftime('%I:%M %p')} IST ({publish_iso})")

    # Paths
    timestamp = get_timestamp()
    raw_path = cfg.get_output_path(f"raw_long_{timestamp}.mkv")
    final_path = cfg.get_output_path(f"final_long_{timestamp}.mp4")
    thumb_path = cfg.get_output_path(f"thumb_long_{timestamp}.jpg")
    audio_path = get_audio_track()

    try:
        # 1. Download source
        log.info(f"1/4 Downloading source clip for '{topic['title']}'...")
        used_ids = set(db.get("used_source_ids", []))
        src_id = download_source_video(
            topic['search_query'],
            raw_path,
            topic['duration_sec'],
            used_ids,
            start_offset=cfg.download['trim']['long_start_seconds']
        )
        if src_id and src_id not in db["used_source_ids"]:
            db["used_source_ids"].append(src_id)

        # 2. Render video
        log.info("2/4 Rendering 1440p Ultra HD video...")
        render_long_video(
            raw_path, final_path,
            topic['intro_title'], topic['sub_title'],
            topic['duration_sec'], audio_path
        )

        # 3. Generate thumbnail
        log.info("3/4 Generating custom thumbnail...")
        generate_custom_thumbnail(final_path, thumb_path, topic['intro_title'], topic['sub_title'])

        # 4. Build description with chapters
        desc = (
            f"{topic['title']}\n\n"
            "Experience next-gen Grand Theft Auto VI in stunning 1440p/4K 60FPS! "
            "Witness Vice City's extreme open-world realism, advanced AI, dynamic physics, "
            "and intense action in the state of Leonida.\n\n"
            "TIMESTAMPS / CHAPTERS:\n"
            + "\n".join([f"{c['time']} - {c['title']}" for c in topic['chapters']])
            + f"\n\n🔥 SUBSCRIBE to @{cfg.default_channel} for daily GTA 6 4K gameplay, physics comparisons, and police escapes!\n\n"
            "#gta6 #gta6gameplay #vicecity #ps5pro #rockstargames #gtavi #donofvicecity"
        )

        # 5. Upload to YouTube
        log.info(f"4/4 Uploading to YouTube (scheduled: {publish_iso})...")
        res = upload_long_video(
            file_path=final_path,
            thumb_path=thumb_path,
            title=topic['title'],
            description=desc,
            tags=topic['tags'],
            publish_at=publish_iso,
            channel_key=channel_key
        )

        video_id = res.get('id')

        # Update database
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

        log.info(f"✅ ALL DONE! Long video scheduled: https://www.youtube.com/watch?v={video_id}")
        return db["daily_long_videos"][today_key]

    except Exception as e:
        log.exception(f"Failed to build long video: {e}")
        raise
    finally:
        # Cleanup raw download
        if os.path.exists(raw_path):
            try:
                os.remove(raw_path)
            except Exception:
                pass


def build_long_video_only(topic_id: str, channel_key: Optional[str] = None) -> Dict[str, Any]:
    """Build a specific long video by topic ID (for testing/manual runs)."""
    cfg = get_config()
    topic = next((t for t in cfg.long_video_pool if t['id_key'] == topic_id), None)
    if not topic:
        raise ValueError(f"Topic not found: {topic_id}")

    # Temporarily override topic selection
    original_pool = cfg.long_video_pool
    cfg.long_video_pool = [topic]

    try:
        return build_and_publish_daily_long_video(channel_key)
    finally:
        cfg.long_video_pool = original_pool


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Long Video Engine")
    parser.add_argument('--topic', type=str, help='Specific topic ID to build')
    parser.add_argument('--channel', type=str, help='Channel key')
    parser.add_argument('--quota', action='store_true', help='Show quota report')

    args = parser.parse_args()

    if args.quota:
        from upload_video import print_quota_report
        print_quota_report()
    elif args.topic:
        build_long_video_only(args.topic, args.channel)
    else:
        build_and_publish_daily_long_video(args.channel)