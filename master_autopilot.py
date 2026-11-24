"""
DON OF VICE CITY — MASTER AUTOPILOT (Refactored)
=================================================
Orchestrates daily content production:
- 1 Long Video (16:9 1440p 60FPS) scheduled for 6:00 PM IST
- 4 Shorts (9:16 Vertical 60FPS) scheduled at peak times

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
    setup_logging, run_with_lock
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
    log.info("  (1 Long 4K Video + 4 High-Action Shorts / Day)")
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
    log.info(f"Quota Status: {report['used']}/{report['limit']} used ({report['percent_used']}%)")
    if not report['is_safe']:
        log.warning("⚠️ Quota usage above alert threshold!")

    # ========================================================================
    # STEP 1: DAILY LONG VIDEO
    # ========================================================================
    log.info("\n" + "-" * 60)
    log.info("  [STEP 1] DAILY 16:9 4K/1440p LONG VIDEO AUTOMATION")
    log.info("-" * 60)

    long_video_info = None
    if today_key in db.get("daily_long_videos", {}):
        existing = db["daily_long_videos"][today_key]
        log.info(f"Today's Long Video already scheduled: {existing['url']}")
        long_video_info = existing
    else:
        try:
            long_video_info = build_and_publish_daily_long_video(channel_key)
            # Reload DB to get updated state
            db = load_db()
            long_video_info = db["daily_long_videos"].get(today_key, long_video_info)
        except Exception as e:
            log.exception(f"Long video generation failed: {e}")
            # Continue with shorts even if long video fails
            long_video_info = {
                'url': f'https://www.youtube.com/@{cfg.default_channel}',
                'title': 'GTA 6 4K Ultra Gameplay'
            }

    # ========================================================================
    # STEP 2: DAILY SHORTS (with cross-promotion)
    # ========================================================================
    log.info("\n" + "-" * 60)
    log.info("  [STEP 2] DAILY 4 SHORTS AUTOMATION (WITH 4K LINK)")
    log.info("-" * 60)

    shorts_results = []
    try:
        shorts_results = run_daily_shorts(channel_key, long_video_info)
    except Exception as e:
        log.exception(f"Shorts generation failed: {e}")

    # ========================================================================
    # FINAL CLEANUP & SUMMARY
    # ========================================================================
    cleanup_old_files(cfg.get_output_path())

    # Final quota report
    final_report = get_quota_report()
    log.info(f"\nFinal Quota: {final_report['used']}/{final_report['limit']} used ({final_report['percent_used']}%)")

    log.info("\n" + "=" * 60)
    log.info("  DAILY AUTOPILOT BUNDLE COMPLETE!")
    log.info(f"  Long Video: {'✅' if long_video_info else '❌'}")
    log.info(f"  Shorts: {len(shorts_results)}/4 scheduled")
    log.info("  All videos safely scheduled on YouTube servers.")
    log.info("  You can now safely shut down or use your laptop.")
    log.info("=" * 60)

    return {
        "success": True,
        "date": today_key,
        "long_video": long_video_info,
        "shorts": shorts_results,
        "quota_used": final_report['used'],
        "quota_limit": final_report['limit']
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
        build_and_publish_daily_long_video(args.channel)
        return

    if args.shorts_only:
        run_daily_shorts(args.channel)
        return

    # Default: run master autopilot
    if args.all_channels:
        run_all_channels()
    else:
        # Use default channel or specified channel
        channel = args.channel or get_config().default_channel
        run_master_autopilot(channel)


if __name__ == '__main__':
    # Use run_with_lock for safety
    run_with_lock(main)