"""
DON OF VICE CITY — MASTER AUTOPILOT (Refactored)
=================================================
Orchestrates daily content production:
- 1 Long Video (16:9 1440p, configured FPS) scheduled at the configured time
- 4 Shorts (9:16 Vertical, configured FPS) scheduled at the configured slots

Features:
- Multi-channel support via config.yaml
- Quota tracking with alerts
- Process locking to prevent duplicates
- Comprehensive logging
- Cross-promotion funnel (Shorts → Long Video)
- Smart dynamic scheduling
"""
import os
import sys
import logging
from datetime import datetime
from typing import Optional, Dict, Any

# Local imports
from config_loader import get_config
from utils import (
    load_db, save_db, acquire_lock, release_lock,
    wait_for_internet, cleanup_old_files, get_date_key,
    is_long_video_day, setup_logging, run_with_lock
)
from long_video_engine import build_and_publish_daily_long_video
from auto_pilot_bot import run_daily_shorts
from upload_video import get_quota_report, print_quota_report

log = setup_logging("master_autopilot")


def run_master_autopilot(channel_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Main orchestration function.
    Runs long video + shorts for a channel.
    """
    log.info("=" * 60)
    log.info("  DON OF VICE CITY — MASTER AUTOPILOT LAUNCHER")
    log.info("  (Long-Form + Shorts Automation)")
    log.info("=" * 60)

    cfg = get_config()
    today_key = get_date_key()

    # Pre-flight: Cleanup old files
    cleanup_old_files(cfg.get_output_path())

    # Pre-flight: Check internet
    if not wait_for_internet():
        log.error("Aborting: Internet connection not available")
        return {"success": False, "error": "No internet"}

    # Load DB
    db = load_db()

    # Print quota report
    report = get_quota_report()
    log.info(
        "Quota Status: %s/%s units used (%s%%); uploads %s/%s",
        report["used"],
        report["limit"],
        report["percent_used"],
        report["uploads"],
        report["upload_limit"],
    )
    if not report["is_safe"]:
        log.warning("Quota usage is above the configured alert threshold.")

    # ========================================================================
    # STEP 1: DAILY LONG VIDEO
    # ========================================================================
    log.info("\n" + "-" * 60)
    log.info("  [STEP 1] DAILY 16:9 1440p LONG VIDEO AUTOMATION")
    log.info("-" * 60)

    long_video_info = None
    long_error = None
    long_expected = is_long_video_day()
    if today_key in db.get("daily_long_videos", {}):
        existing = db["daily_long_videos"][today_key]
        log.info(f"Today's Long Video already scheduled: {existing.get('url')}")
        long_video_info = existing
    elif not long_expected:
        log.info(
            "Long video is not scheduled today (configured weekday: %s).",
            cfg.schedule.long_video_weekday,
        )
    else:
        try:
            long_video_info = build_and_publish_daily_long_video(channel_key)
            db = load_db()
            long_video_info = db["daily_long_videos"].get(today_key, long_video_info)
        except Exception as e:
            long_error = str(e)
            log.exception(f"Long video generation failed: {e}")
            # Shorts can still run, but the overall run must report failure.

    # ========================================================================
    # STEP 2: DAILY SHORTS (with cross-promotion)
    # ========================================================================
    log.info("\n" + "-" * 60)
    log.info("  [STEP 2] DAILY SHORTS AUTOMATION (WITH 1440p LINK)")
    log.info("-" * 60)

    shorts_results = []
    shorts_error = None
    try:
        shorts_results = run_daily_shorts(channel_key, long_video_info)
    except Exception as e:
        shorts_error = str(e)
        log.exception(f"Shorts generation failed: {e}")

    # ========================================================================
    # FINAL CLEANUP & SUMMARY
    # ========================================================================
    cleanup_old_files(cfg.get_output_path())

    # Re-read the DB so "already scheduled" slots count as success.
    db = load_db()
    scheduled_today = db.get("scheduled_slots", {}).get(today_key, [])
    expected_shorts = min(
        len(cfg.schedule.shorts_standard_slots),
        max(1, int(cfg.schedule.shorts_max_per_day)),
    )

    long_ok = (not long_expected) or long_video_info is not None
    shorts_ok = len(scheduled_today) >= expected_shorts
    success = long_ok and shorts_ok

    final_report = get_quota_report()
    log.info(
        "\nFinal Quota: %s/%s units used (%s%%); uploads %s/%s",
        final_report["used"],
        final_report["limit"],
        final_report["percent_used"],
        final_report["uploads"],
        final_report["upload_limit"],
    )

    log.info("\n" + "=" * 60)
    if success:
        log.info("  DAILY AUTOPILOT BUNDLE COMPLETE")
    else:
        log.info("  DAILY AUTOPILOT FINISHED WITH ERRORS")
    log.info("  Long Video: %s", "OK" if long_ok else "FAILED")
    log.info(
        "  Shorts: %s/%s scheduled",
        len(scheduled_today),
        expected_shorts,
    )
    if long_error:
        log.error("  Long video error: %s", long_error)
    if shorts_error:
        log.error("  Shorts error: %s", shorts_error)
    if success:
        log.info("  All requested videos are scheduled on YouTube.")
    else:
        log.info("  Check the errors above; the run will not be reported as successful.")
    log.info("=" * 60)

    return {
        "success": success,
        "date": today_key,
        "long_video": long_video_info,
        "long_error": long_error,
        "shorts": shorts_results,
        "shorts_scheduled": len(scheduled_today),
        "shorts_expected": expected_shorts,
        "shorts_error": shorts_error,
        "quota_used": final_report["used"],
        "quota_limit": final_report["limit"],
    }


def run_for_channel(channel_key: str) -> Dict[str, Any]:
    """Run autopilot for a specific channel."""
    log.info(f"Running for channel: {channel_key}")
    return run_master_autopilot(channel_key)


def run_all_channels() -> Dict[str, Any]:
    """Run autopilot for all configured channels."""
    cfg = get_config()
    results = {}

    for channel_key in cfg.channels.keys():
        log.info(f"\n{'='*60}")
        log.info(f"  PROCESSING CHANNEL: {channel_key}")
        log.info(f"{'='*60}")
        try:
            results[channel_key] = run_master_autopilot(channel_key)
        except Exception as e:
            log.exception(f"Channel {channel_key} failed: {e}")
            results[channel_key] = {"success": False, "error": str(e)}

    return results


def main():
    """CLI entry point."""
    import argparse

    # Relative font paths for FFmpeg's drawtext require the project directory.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser(description="DON OF VICE CITY - Master Autopilot")
    parser.add_argument('--channel', type=str, help='Specific channel key to run')
    parser.add_argument('--all-channels', action='store_true', help='Run for all configured channels')
    parser.add_argument('--quota', action='store_true', help='Show quota report and exit')
    parser.add_argument('--verify', action='store_true', help='Verify channel authentication')
    parser.add_argument('--long-only', action='store_true', help='Run only long video')
    parser.add_argument('--shorts-only', action='store_true', help='Run only shorts')

    args = parser.parse_args()

    if args.quota:
        print_quota_report()
        return

    if args.verify:
        from upload_video import verify_channel
        try:
            info = verify_channel(args.channel)
            print(f"✅ Connected: {info['snippet']['title']} ({info['id']})")
            print(f"Subscribers: {info['statistics'].get('subscriberCount', 'hidden')}")
        except Exception as e:
            print(f"❌ Verification failed: {e}")
            sys.exit(1)
        return

    if args.long_only:
        from long_video_engine import build_and_publish_daily_long_video

        result = build_and_publish_daily_long_video(args.channel)
        if not result or not result.get("id"):
            log.error("Long-video run did not produce a scheduled video")
            sys.exit(1)
        return

    if args.shorts_only:
        run_daily_shorts(args.channel)
        cfg = get_config()
        expected = min(
            len(cfg.schedule.shorts_standard_slots),
            max(1, int(cfg.schedule.shorts_max_per_day)),
        )
        scheduled = len(
            load_db().get("scheduled_slots", {}).get(get_date_key(), [])
        )
        log.info("Shorts scheduled today: %s/%s", scheduled, expected)
        if scheduled < expected:
            log.error("Shorts run did not schedule every configured slot")
            sys.exit(1)
        return

    # Default: run master autopilot
    if args.all_channels:
        results = run_all_channels()
        if not all(result.get("success") for result in results.values()):
            sys.exit(1)
    else:
        channel = args.channel or get_config().default_channel
        result = run_master_autopilot(channel)
        if not result.get("success"):
            sys.exit(1)


if __name__ == '__main__':
    # Use run_with_lock for safety
    run_with_lock(main)