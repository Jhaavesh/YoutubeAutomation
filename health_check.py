#!/usr/bin/env python3
"""
DON OF VICE CITY — Health Check & Monitoring
Run manually or as a scheduled task to monitor system health.

This script is read-only: it does not refresh tokens, upload, or modify the DB.
"""
from __future__ import annotations

import json
import os
import pickle
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import get_channel_config, get_config
from utils import get_date_key, get_ffprobe_exe, load_db, setup_logging
from upload_video import get_quota_report

UPLOAD_SCOPES = {
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
}
UPDATE_SCOPES = {
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtubepartner",
}
ANALYTICS_SCOPES = {"https://www.googleapis.com/auth/yt-analytics.readonly"}

PACKAGE_IMPORTS = {
    "google-api-python-client": "googleapiclient",
    "google-auth-httplib2": "google_auth_httplib2",
    "google-auth-oauthlib": "google_auth_oauthlib",
    "yt-dlp": "yt_dlp",
    "PyYAML": "yaml",
    "tzdata": "tzdata",
}


def check_disk_space(path: str) -> dict:
    """Check available disk space."""
    try:
        total, used, free = shutil.disk_usage(path)
        return {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "percent_used": round(used / total * 100, 1),
        }
    except Exception as exc:
        return {"error": str(exc)}


def check_ffmpeg() -> dict:
    """Check the configured FFmpeg and FFprobe binaries."""
    result = {"installed": False}
    try:
        cfg = get_config()
        ffmpeg = cfg.get_ffmpeg_exe()
        ffprobe = get_ffprobe_exe()
        proc = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        result.update(
            {
                "installed": proc.returncode == 0,
                "path": ffmpeg,
                "ffprobe": ffprobe,
                "version": (proc.stdout or "").splitlines()[0]
                if proc.stdout
                else "unknown",
            }
        )
    except Exception as exc:
        result["error"] = str(exc)
    return result


def check_python_packages() -> dict:
    """Check required Python packages by their real import names."""
    missing = []
    for package, import_name in PACKAGE_IMPORTS.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package)
    return {"all_installed": not missing, "missing": missing}


def check_token(channel_key: str | None = None) -> dict:
    """Inspect the stored OAuth token without refreshing or modifying it."""
    cfg = get_config()
    channel = get_channel_config(channel_key)
    token_path = channel.token_file
    if not os.path.isabs(token_path):
        token_path = os.path.join(cfg.base_dir, token_path)

    result = {
        "path": token_path,
        "exists": os.path.isfile(token_path),
        "scopes": [],
        "expired": None,
        "has_refresh_token": False,
        "upload_ready": False,
        "metadata_ready": False,
        "analytics_ready": False,
    }
    if not result["exists"]:
        return result

    try:
        with open(token_path, "rb") as handle:
            creds = pickle.load(handle)
        scopes = set(creds.scopes or [])
        result.update(
            {
                "scopes": sorted(scopes),
                "expired": bool(creds.expired),
                "has_refresh_token": bool(creds.refresh_token),
                "upload_ready": bool(scopes & UPLOAD_SCOPES),
                "metadata_ready": bool(scopes & UPDATE_SCOPES),
                "analytics_ready": bool(scopes & ANALYTICS_SCOPES),
            }
        )
    except Exception as exc:
        result["error"] = str(exc)
    return result


def check_recent_logs(log_path: str, hours: int = 24) -> dict:
    """Check recent log entries for errors."""
    if not os.path.exists(log_path):
        return {"exists": False}

    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        errors = []
        warnings = []

        with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    ts_str = line.split(" | ")[0].strip()
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    if ts >= cutoff:
                        if " | ERROR " in line:
                            errors.append(line.strip())
                        elif " | WARNING " in line:
                            warnings.append(line.strip())
                except Exception:
                    continue

        return {
            "exists": True,
            "errors_last_24h": len(errors),
            "warnings_last_24h": len(warnings),
            "recent_errors": errors[-5:],
            "recent_warnings": warnings[-5:],
        }
    except Exception as exc:
        return {"exists": True, "error": str(exc)}


def check_scheduled_videos(db: dict) -> dict:
    """Check today's scheduled videos using the configured schedule date."""
    today = get_date_key()
    today_videos = db.get("daily_long_videos", {}).get(today)
    today_shorts = db.get("scheduled_slots", {}).get(today, [])
    return {
        "date": today,
        "long_video": today_videos is not None,
        "long_video_info": today_videos,
        "shorts_scheduled": len(today_shorts),
        "shorts_slots": today_shorts,
        "total_scheduled": (1 if today_videos else 0) + len(today_shorts),
    }


def check_database_health(db: dict) -> dict:
    """Check database integrity and stats."""
    source_ids = db.get("used_source_ids", [])
    duplicates = len(source_ids) - len(set(source_ids))
    return {
        "used_source_ids": len(source_ids),
        "used_long_topics": len(db.get("used_long_topics", [])),
        "total_uploaded": len(db.get("uploaded_videos", [])),
        "duplicate_source_ids": duplicates,
        "healthy": duplicates == 0,
    }


def check_quota() -> dict:
    """Get quota status."""
    report = get_quota_report()
    return {
        "limit": report["limit"],
        "used": report["used"],
        "remaining": report["remaining"],
        "percent": report["percent_used"],
        "uploads": report["uploads"],
        "upload_limit": report["upload_limit"],
        "is_safe": report["is_safe"],
        "operations_today": len(report["operations"]),
    }


def run_health_check(verbose: bool = False) -> dict:
    """Run a comprehensive, read-only health check."""
    setup_logging("health_check")
    cfg = get_config()
    db = load_db()

    print("=" * 60)
    print("  DON OF VICE CITY — SYSTEM HEALTH CHECK")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Project: {cfg.base_dir}")
    print(f"Channel: {cfg.default_channel}")
    print()

    results: dict = {}

    print("Checking disk space...")
    disk = check_disk_space(cfg.base_dir)
    results["disk"] = disk
    if "error" not in disk:
        status = "OK" if disk["percent_used"] < 90 else "WARNING"
        print(
            f"   {status}: {disk['free_gb']} GB free / "
            f"{disk['total_gb']} GB ({disk['percent_used']}% used)"
        )
    else:
        print(f"   ERROR: {disk['error']}")

    print("\nChecking FFmpeg...")
    ffmpeg = check_ffmpeg()
    results["ffmpeg"] = ffmpeg
    if ffmpeg.get("installed"):
        print(f"   OK: {ffmpeg['version']}")
        print(f"   ffprobe: {ffmpeg.get('ffprobe')}")
    else:
        print(f"   ERROR: {ffmpeg.get('error', 'not found')}")

    print("\nChecking Python packages...")
    packages = check_python_packages()
    results["packages"] = packages
    if packages["all_installed"]:
        print("   OK: all required packages installed")
    else:
        print(f"   ERROR: missing {', '.join(packages['missing'])}")

    print("\nChecking OAuth token...")
    token = check_token(cfg.default_channel)
    results["token"] = token
    if not token["exists"]:
        print(f"   ERROR: token not found at {token['path']}")
    elif token.get("error"):
        print(f"   ERROR: {token['error']}")
    else:
        print(f"   Path: {token['path']}")
        print(f"   Expired: {token['expired']} (refresh token: {token['has_refresh_token']})")
        print(f"   Upload scope: {'OK' if token['upload_ready'] else 'MISSING'}")
        print(
            "   Metadata update/delete scope: "
            f"{'OK' if token['metadata_ready'] else 'MISSING'}"
        )
        print(f"   Analytics scope: {'OK' if token['analytics_ready'] else 'MISSING'}")
        if not token["metadata_ready"] or not token["analytics_ready"]:
            print("   Re-authenticate with: python setup_auth.py --channel <key>")

    print("\nChecking YouTube API quota...")
    quota = check_quota()
    results["quota"] = quota
    status = "OK" if quota["is_safe"] else "WARNING"
    print(
        f"   {status}: {quota['used']}/{quota['limit']} units "
        f"({quota['percent']}%)"
    )
    print(f"   Uploads today: {quota['uploads']}/{quota['upload_limit']}")

    print("\nChecking today's schedule...")
    schedule = check_scheduled_videos(db)
    results["schedule"] = schedule
    print(f"   Date: {schedule['date']}")
    print(
        "   Long Video: "
        + ("scheduled" if schedule["long_video"] else "not scheduled")
    )
    if schedule["long_video"] and schedule["long_video_info"]:
        info = schedule["long_video_info"]
        print(f"      {info.get('title', '(untitled)')[:70]}")
        print(f"      {info.get('scheduled_for', '(no time)')}")
    print(
        f"   Shorts: {schedule['shorts_scheduled']} scheduled "
        f"({schedule['shorts_slots']})"
    )

    print("\nChecking database health...")
    db_health = check_database_health(db)
    results["database"] = db_health
    status = "OK" if db_health["healthy"] else "WARNING"
    print(f"   {status}: used sources {db_health['used_source_ids']}")
    print(f"   Used long topics: {db_health['used_long_topics']}")
    print(f"   Total uploaded: {db_health['total_uploaded']}")
    if db_health["duplicate_source_ids"] > 0:
        print(f"   WARNING: duplicate source IDs: {db_health['duplicate_source_ids']}")

    print("\nChecking recent logs...")
    log_health = check_recent_logs(cfg.get_log_path())
    results["logs"] = log_health
    if log_health.get("exists"):
        if log_health.get("errors_last_24h", 0) == 0:
            print("   OK: no errors in last 24h")
        else:
            print(
                f"   WARNING: {log_health['errors_last_24h']} errors, "
                f"{log_health['warnings_last_24h']} warnings in last 24h"
            )
            if verbose:
                for err in log_health.get("recent_errors", []):
                    print(f"      ERROR: {err[:120]}")
    else:
        print("   No log file found")

    all_ok = (
        disk.get("percent_used", 100) < 90
        and ffmpeg.get("installed", False)
        and packages["all_installed"]
        and token.get("upload_ready", False)
        and quota["is_safe"]
        and db_health["healthy"]
    )
    print("\n" + "=" * 60)
    print(f"  OVERALL STATUS: {'HEALTHY' if all_ok else 'ISSUES DETECTED'}")
    print("=" * 60)
    results["all_ok"] = all_ok
    return results


def fix_duplicates() -> None:
    """Remove duplicate source IDs from database."""
    db = load_db()
    source_ids = db.get("used_source_ids", [])
    unique = list(dict.fromkeys(source_ids))
    removed = len(source_ids) - len(unique)

    if removed > 0:
        db["used_source_ids"] = unique
        from utils import save_db

        save_db(db)
        print(f"Removed {removed} duplicate source IDs")
    else:
        print("No duplicates found")


def show_recent_uploads(days: int = 7) -> None:
    """Show recently uploaded videos."""
    db = load_db()
    cutoff = datetime.now() - timedelta(days=days)

    print(f"\nVideos uploaded in last {days} days:")
    print("-" * 60)

    count = 0
    for video in reversed(db.get("uploaded_videos", [])):
        try:
            ts = datetime.fromisoformat(video.get("scheduled_for", ""))
            if ts.tzinfo is not None:
                ts = ts.astimezone().replace(tzinfo=None)
            if ts >= cutoff:
                print(
                    f"  {ts.strftime('%m-%d %H:%M')} | "
                    f"{video.get('slot', '?'):<30} | {video.get('id', '?')}"
                )
                count += 1
        except Exception:
            continue

    if count == 0:
        print("  (none)")
    print(f"\nTotal: {count} videos")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Health Check for DON OF VICE CITY")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "--fix-duplicates",
        action="store_true",
        help="Remove duplicate source IDs from DB",
    )
    parser.add_argument(
        "--recent",
        type=int,
        metavar="DAYS",
        help="Show recent uploads (default: 7 days)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.fix_duplicates:
        fix_duplicates()
        return

    if args.recent is not None:
        show_recent_uploads(args.recent)
        return

    results = run_health_check(verbose=args.verbose)

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    sys.exit(0 if results.get("all_ok") else 1)


if __name__ == "__main__":
    main()
