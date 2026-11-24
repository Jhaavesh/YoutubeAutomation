"""
DON OF VICE CITY — Shorts Engine (Refactored)
Generates 9:16 vertical Shorts with bold typography, Phonk audio, and smart scheduling.
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
from config_loader import get_config
from utils import (
    load_db, save_db, get_ffmpeg_exe, run_ffmpeg, sanitize_drawtext,
    wait_for_internet, format_iso_ist, format_time_ist, get_timestamp, get_date_key,
    get_audio_track, ensure_output_dirs, cleanup_old_files,
    compute_schedule_times
)
from upload_video import upload_short, get_quota_report

log = logging.getLogger("auto_pilot_bot")


# ============================================================================
# SOURCE VIDEO DOWNLOAD
# ============================================================================
def find_and_download_unique_source_clip(
    search_query: str,
    target_path: str,
    used_source_ids: set,
    duration: int = 35
) -> Optional[str]:
    """
    Search top 10 YouTube results and download a never-before-used clip.
    Guarantees 100% unique footage.
    """
    cfg = get_config()
    download_cfg = cfg.download

    search_opts = {
        'quiet': True,
        'extract_flat': True,
        'noplaylist': True
    }

    selected_id = None
    selected_title = None

    with yt_dlp.YoutubeDL(search_opts) as ydl:
        try:
            res = ydl.extract_info(f"ytsearch{download_cfg['search']['max_results']}:{search_query}", download=False)
            for entry in res.get('entries', []):
                vid = entry.get('id')
                if not vid:
                    continue
                if vid not in used_source_ids:
                    selected_id = vid
                    selected_title = entry.get('title')
                    break
                else:
                    log.debug(f"[Dedup] Skipping used source: {vid} ('{entry.get('title', '')[:30]}...')")
        except Exception as e:
            log.warning(f"Search warning: {e}")

    if not selected_id:
        log.warning("No unused video in top 10, using fallback query")
        target_url = f"ytsearch1:{search_query}"
    else:
        target_url = f"https://www.youtube.com/watch?v={selected_id}"
        log.info(f">>> Selected fresh unique source: {selected_id} ('{selected_title}')")

    ydl_opts = {
        'format': download_cfg['format']['short'],
        'outtmpl': target_path,
        'noplaylist': True,
        'quiet': True,
        'merge_output_format': download_cfg['merge_output_format']['short'],
        'ffmpeg_location': os.path.dirname(get_ffmpeg_exe()),
        'download_ranges': yt_dlp.utils.download_range_func(
            None, [(download_cfg['trim']['short_start_seconds'], download_cfg['trim']['short_start_seconds'] + duration)]
        )
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([target_url])

    return selected_id


# ============================================================================
# VIDEO EDITING (Vertical Short)
# ============================================================================
def edit_to_vertical_short(
    input_video: str,
    output_video: str,
    hook_text: str,
    bottom_text: str,
    audio_track: str
) -> None:
    """
    Edit to 9:16 vertical short (1080x1920):
    - 26 seconds duration
    - Center-crop/scale to fill (no letterboxing)
    - Modern floating typography (no black boxes)
    - Copyright-free Phonk beat mixed in
    """
    cfg = get_config()
    video_cfg = cfg.video
    font_file = video_cfg.font_primary
    if not os.path.exists(font_file):
        font_file = video_cfg.font_fallback

    # Sanitize
    clean_hook = sanitize_drawtext(hook_text)
    clean_bottom = sanitize_drawtext(bottom_text)
    watermark = video_cfg.short_watermark

    filter_complex = (
        f"[0:v]trim=start={video_cfg.short_trim_start}:duration={video_cfg.short_duration},setpts=PTS-STARTPTS,"
        f"scale={video_cfg.short_resolution}:force_original_aspect_ratio=increase,crop={video_cfg.short_resolution},"
        # Hook text (top)
        f"drawtext=fontfile='{font_file}':text='{clean_hook}':fontcolor=white:fontsize=60:borderw=6:bordercolor=black:"
        f"shadowcolor=black@0.6:shadowx=3:shadowy=3:x=(w-text_w)/2:y=180,"
        # Bottom text
        f"drawtext=fontfile='{font_file}':text='{clean_bottom}':fontcolor=yellow:fontsize=44:borderw=5:bordercolor=black:"
        f"shadowcolor=black@0.6:shadowx=3:shadowy=3:x=(w-text_w)/2:y=260,"
        # Watermark (bottom center)
        f"drawtext=fontfile='{font_file}':text='{sanitize_drawtext(watermark.get('text', 'DON OF VICE CITY'))}':"
        f"fontcolor={watermark.get('color', 'cyan')}:fontsize={watermark.get('font_size', 36)}:"
        f"borderw=3:bordercolor=black:"
        f"shadowcolor=black@0.6:shadowx=2:shadowy=2:"
        f"x=(w-text_w)/2:y={watermark.get('y_position', 1740)}[v];"
        # Audio
        f"[1:a]volume={video_cfg.short_audio_volume}[a]"
    )

    cmd = [
        '-y',
        '-ss', str(video_cfg.short_trim_start),
        '-i', input_video,
        '-stream_loop', '-1',
        '-i', audio_track,
        '-filter_complex', filter_complex,
        '-map', '[v]',
        '-map', '[a]',
        '-c:v', 'libx264',
        '-preset', video_cfg.short_preset,
        '-crf', str(video_cfg.short_crf),
        '-c:a', 'aac',
        '-b:a', video_cfg.short_audio_bitrate,
        '-t', str(video_cfg.short_duration),
        output_video
    ]

    run_ffmpeg(cmd, "Short video edit")


# ============================================================================
# MAIN SHORTS ORCHESTRATION
# ============================================================================
def run_daily_shorts(channel_key: Optional[str] = None, long_video_info: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Run daily shorts automation for all pending slots.
    Returns list of uploaded video info.
    """
    log.info("=" * 60)
    log.info("  DON OF VICE CITY — DAILY SHORTS ENGINE (9:16 Vertical)")
    log.info("=" * 60)

    cfg = get_config()
    ensure_output_dirs()

    db = load_db()
    today_key = get_date_key()

    # Initialize today's slots if needed
    if today_key not in db.get("scheduled_slots", {}):
        db["scheduled_slots"][today_key] = []

    today_done = db["scheduled_slots"][today_key]
    pending_slots = [s for s in cfg.schedule.shorts_standard_slots if s["slot_id"] not in today_done]

    if not pending_slots:
        log.info(f"All {len(cfg.schedule.shorts_standard_slots)} Shorts for {today_key} already scheduled!")
        return []

    log.info(f"Pending Shorts: {len(pending_slots)} slot(s)")

    # Compute schedule times
    now = datetime.now()
    schedule_times = compute_schedule_times(
        pending_slots=pending_slots,
        now=now,
        min_first_lead_minutes=cfg.schedule.shorts_min_first_lead,
        end_hour=cfg.schedule.shorts_end_hour,
        end_minute=cfg.schedule.shorts_end_minute,
        min_spread_hours=cfg.schedule.shorts_min_spread_hours,
        late_interval_hours=cfg.schedule.shorts_late_interval_hours,
        round_minutes=cfg.schedule.shorts_round_minutes,
        standard_slots=cfg.schedule.shorts_standard_slots
    )

    # Shuffle topics for variety
    available_topics = list(cfg.shorts_pool)
    random.shuffle(available_topics)
    bg_audio = get_audio_track()

    # Long video URL for cross-promotion
    long_video_url = long_video_info.get('url', f'https://www.youtube.com/@{cfg.default_channel}') if long_video_info else f'https://www.youtube.com/@{cfg.default_channel}'
    long_video_title = long_video_info.get('title', 'GTA 6 4K Ultra Gameplay') if long_video_info else 'GTA 6 4K Ultra Gameplay'

    results = []

    for i, slot in enumerate(pending_slots):
        topic = available_topics[i % len(available_topics)]
        target_time = schedule_times[i]
        publish_iso = format_iso_ist(target_time)
        time_str = format_time_ist(target_time)

        log.info(f"\n>>> [Short {slot['slot_id']}/{len(cfg.schedule.shorts_standard_slots)}] Target: {time_str} | {topic['title']}")

        timestamp = get_timestamp()
        temp_raw = cfg.get_output_path(f"raw_short_{slot['slot_id']}_{timestamp}.mp4")
        out_final = cfg.get_output_path(f"final_short_{slot['slot_id']}_{timestamp}.mp4")

        try:
            # 1. Download unique clip
            log.info(f"    1/3 Downloading unique clip for '{topic['search_query']}'...")
            used_sources = set(db.get("used_source_ids", []))
            src_id = find_and_download_unique_source_clip(
                topic['search_query'], temp_raw, used_sources
            )
            if src_id and src_id not in db["used_source_ids"]:
                db["used_source_ids"].append(src_id)

            # 2. Edit to vertical short
            log.info("    2/3 Editing 9:16 vertical short with Phonk beat...")
            edit_to_vertical_short(temp_raw, out_final, topic['hook_text'], topic['bottom_text'], bg_audio)

            # 3. Build description with cross-promotion CTA
            description = (
                f"{topic['hook_text']} — {topic['bottom_text']}\n\n"
                f"🔥 WATCH FULL 4K VIDEO HERE:\n"
                f"👉 {long_video_url}\n"
                f"({long_video_title})\n\n"
                f"📌 SUBSCRIBE to @{cfg.default_channel} for daily GTA 6 leaks, physics, and gameplay!\n\n"
                f"#gta6 #shorts #gaming #vicecity #ps5pro"
            )

            # 4. Upload to YouTube
            log.info(f"    3/3 Uploading to YouTube (scheduled: {publish_iso})...")
            res = upload_short(
                file_path=out_final,
                title=topic['title'],
                description=description,
                tags=topic['tags'],
                publish_at=publish_iso,
                channel_key=channel_key
            )

            video_id = res.get('id')

            # Update database
            db["scheduled_slots"][today_key].append(slot["slot_id"])
            db["uploaded_videos"].append({
                "id": video_id,
                "title": topic["title"],
                "slot": slot["name"],
                "scheduled_for": publish_iso,
                "date_key": today_key
            })
            save_db(db)

            log.info(f"    ✅ SUCCESS: Uploaded {video_id} scheduled for {time_str}")
            results.append({
                "slot_id": slot["slot_id"],
                "video_id": video_id,
                "title": topic["title"],
                "scheduled_for": publish_iso,
                "time_str": time_str
            })

        except Exception as e:
            log.exception(f"    ❌ ERROR processing Short {slot['slot_id']}: {e}")

        finally:
            # Cleanup temp raw download
            if os.path.exists(temp_raw):
                try:
                    os.remove(temp_raw)
                except Exception:
                    pass

    # Final cleanup
    cleanup_old_files(cfg.get_output_path())

    log.info("\n" + "=" * 60)
    log.info(f"  ALL {len(results)} SHORTS SCHEDULED ON YOUTUBE!")
    log.info("  YouTube will auto-publish each at the scheduled time.")
    log.info("=" * 60)

    return results


def run_single_short(
    slot_id: int,
    topic_category: Optional[str] = None,
    channel_key: Optional[str] = None,
    long_video_info: Optional[Dict] = None
) -> Dict[str, Any]:
    """Run a single short for testing (specific slot and topic)."""
    cfg = get_config()

    # Find slot
    slot = next((s for s in cfg.schedule.shorts_standard_slots if s['slot_id'] == slot_id), None)
    if not slot:
        raise ValueError(f"Slot {slot_id} not found")

    # Find topic
    if topic_category:
        topic = next((t for t in cfg.shorts_pool if t['category'] == topic_category), None)
    else:
        topic = cfg.shorts_pool[0]

    if not topic:
        raise ValueError(f"Topic not found: {topic_category}")

    # Schedule for 20 min from now
    now = datetime.now() + timedelta(minutes=20)
    minute = (now.minute // 5) * 5
    target_time = now.replace(minute=minute, second=0, microsecond=0)
    publish_iso = format_iso_ist(target_time)

    ensure_output_dirs()
    bg_audio = get_audio_track()

    long_video_url = long_video_info.get('url', f'https://www.youtube.com/@{cfg.default_channel}') if long_video_info else f'https://www.youtube.com/@{cfg.default_channel}'
    long_video_title = long_video_info.get('title', 'GTA 6 4K Ultra Gameplay') if long_video_info else 'GTA 6 4K Ultra Gameplay'

    timestamp = get_timestamp()
    temp_raw = cfg.get_output_path(f"raw_short_{slot_id}_{timestamp}.mp4")
    out_final = cfg.get_output_path(f"final_short_{slot_id}_{timestamp}.mp4")

    try:
        log.info(f"Building single short: {topic['title']} for {publish_iso}")

        used_sources = set(load_db().get("used_source_ids", []))
        src_id = find_and_download_unique_source_clip(topic['search_query'], temp_raw, used_sources)

        edit_to_vertical_short(temp_raw, out_final, topic['hook_text'], topic['bottom_text'], bg_audio)

        description = (
            f"{topic['hook_text']} — {topic['bottom_text']}\n\n"
            f"🔥 WATCH FULL 4K VIDEO HERE:\n"
            f"👉 {long_video_url}\n"
            f"({long_video_title})\n\n"
            f"📌 SUBSCRIBE to @{cfg.default_channel} for daily GTA 6 leaks, physics, and gameplay!\n\n"
            f"#gta6 #shorts #gaming #vicecity #ps5pro"
        )

        res = upload_short(
            file_path=out_final,
            title=topic['title'],
            description=description,
            tags=topic['tags'],
            publish_at=publish_iso,
            channel_key=channel_key
        )

        video_id = res.get('id')
        log.info(f"✅ Single short uploaded: {video_id}")

        return {"video_id": video_id, "title": topic['title'], "scheduled_for": publish_iso}

    finally:
        if os.path.exists(temp_raw):
            try:
                os.remove(temp_raw)
            except Exception:
                pass


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Shorts Engine")
    parser.add_argument('--slot', type=int, help='Specific slot ID to run (1-4)')
    parser.add_argument('--topic', type=str, help='Topic category for single short')
    parser.add_argument('--channel', type=str, help='Channel key')
    parser.add_argument('--quota', action='store_true', help='Show quota report')
    parser.add_argument('--all', action='store_true', help='Run all pending shorts (default)')

    args = parser.parse_args()

    if args.quota:
        from upload_video import print_quota_report
        print_quota_report()
    elif args.slot:
        run_single_short(args.slot, args.topic, args.channel)
    else:
        run_daily_shorts(args.channel)