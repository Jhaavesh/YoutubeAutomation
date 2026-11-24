#!/usr/bin/env python3
"""
DON OF VICE CITY — Health Check & Monitoring
Run manually or as scheduled task to monitor system health.
"""
import os
import sys
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import get_config
from utils import load_db
from upload_video import get_quota_report


def check_disk_space(path: str) -> dict:
    """Check available disk space."""
    try:
        import shutil
        total, used, free = shutil.disk_usage(path)
        return {
            'total_gb': round(total / (1024**3), 2),
            'used_gb': round(used / (1024**3), 2),
            'free_gb': round(free / (1024**3), 2),
            'percent_used': round(used / total * 100, 1)
        }
    except Exception as e:
        return {'error': str(e)}


def check_ffmpeg() -> dict:
    """Check FFmpeg installation."""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
        version_line = result.stdout.split('\n')[0] if result.stdout else 'unknown'
        return {'installed': True, 'version': version_line}
    except Exception as e:
        return {'installed': False, 'error': str(e)}


def check_python_packages() -> dict:
    """Check required Python packages."""
    required = [
        'google-api-python-client',
        'google-auth-httplib2',
        'google-auth-oauthlib',
        'yt-dlp',
        'PyYAML'
    ]

    missing = []
    for pkg in required:
        try:
            __import__(pkg.replace('-', '_'))
        except ImportError:
            missing.append(pkg)

    return {
        'all_installed': len(missing) == 0,
        'missing': missing
    }


def check_recent_logs(log_path: str, hours: int = 24) -> dict:
    """Check recent log entries for errors."""
    if not os.path.exists(log_path):
        return {'exists': False}

    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        errors = []
        warnings = []

        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                # Parse timestamp from log format: "2026-11-24 10:30:45 | ERROR   | name | message"
                try:
                    ts_str = line.split(' | ')[0].strip()
                    ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    if ts >= cutoff:
                        if ' | ERROR ' in line:
                            errors.append(line.strip())
                        elif ' | WARNING ' in line:
                            warnings.append(line.strip())
                except Exception:
                    continue

        return {
            'exists': True,
            'errors_last_24h': len(errors),
            'warnings_last_24h': len(warnings),
            'recent_errors': errors[-5:],
            'recent_warnings': warnings[-5:]
        }
    except Exception as e:
        return {'exists': True, 'error': str(e)}


def check_scheduled_videos(db: dict) -> dict:
    """Check today's scheduled videos."""
    today = datetime.now().strftime('%Y-%m-%d')
    today_videos = db.get('daily_long_videos', {}).get(today)
    today_shorts = db.get('scheduled_slots', {}).get(today, [])

    return {
        'date': today,
        'long_video': today_videos is not None,
        'long_video_info': today_videos,
        'shorts_scheduled': len(today_shorts),
        'shorts_slots': today_shorts,
        'total_scheduled': (1 if today_videos else 0) + len(today_shorts)
    }


def check_database_health(db: dict) -> dict:
    """Check database integrity and stats."""
    used_sources = len(db.get('used_source_ids', []))
    used_topics = len(db.get('used_long_topics', []))
    uploaded = len(db.get('uploaded_videos', []))

    # Check for duplicates in used_source_ids
    source_ids = db.get('used_source_ids', [])
    duplicates = len(source_ids) - len(set(source_ids))

    return {
        'used_source_ids': used_sources,
        'used_long_topics': used_topics,
        'total_uploaded': uploaded,
        'duplicate_source_ids': duplicates,
        'healthy': duplicates == 0
    }


def check_quota() -> dict:
    """Get quota status."""
    report = get_quota_report()
    return {
        'limit': report['limit'],
        'used': report['used'],
        'remaining': report['remaining'],
        'percent': report['percent_used'],
        'is_safe': report['is_safe'],
        'operations_today': len(report['operations'])
    }


def run_health_check(verbose: bool = False) -> dict:
    """Run comprehensive health check."""
    cfg = get_config()
    db = load_db()

    print("=" * 60)
    print("  DON OF VICE CITY — SYSTEM HEALTH CHECK")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Project: {cfg.base_dir}")
    print(f"Channel: {cfg.default_channel}")
    print()

    results = {}

    # 1. Disk Space
    print("📀 Checking disk space...")
    disk = check_disk_space(cfg.base_dir)
    results['disk'] = disk
    if 'error' not in disk:
        status = "✅" if disk['percent_used'] < 90 else "⚠️"
        print(f"   {status} Free: {disk['free_gb']} GB / {disk['total_gb']} GB ({disk['percent_used']}% used)")
    else:
        print(f"   ❌ Error: {disk['error']}")

    # 2. FFmpeg
    print("\n🎬 Checking FFmpeg...")
    ffmpeg = check_ffmpeg()
    results['ffmpeg'] = ffmpeg
    if ffmpeg['installed']:
        print(f"   ✅ {ffmpeg['version']}")
    else:
        print(f"   ❌ Not found: {ffmpeg['error']}")

    # 3. Python Packages
    print("\n🐍 Checking Python packages...")
    pkgs = check_python_packages()
    results['packages'] = pkgs
    if pkgs['all_installed']:
        print("   ✅ All required packages installed")
    else:
        print(f"   ❌ Missing: {', '.join(pkgs['missing'])}")

    # 4. Quota
    print("\n📊 Checking YouTube API quota...")
    quota = check_quota()
    results['quota'] = quota
    status = "✅" if quota['is_safe'] else "⚠️"
    print(f"   {status} Used: {quota['used']}/{quota['limit']} ({quota['percent']}%)")
    print(f"      Remaining: {quota['remaining']} units")

    # 5. Scheduled Videos
    print("\n📅 Checking today's schedule...")
    schedule = check_scheduled_videos(db)
    results['schedule'] = schedule
    print(f"   Date: {schedule['date']}")
    print(f"   Long Video: {'✅ Scheduled' if schedule['long_video'] else '❌ Not scheduled'}")
    if schedule['long_video']:
        print(f"      → {schedule['long_video_info']['title'][:60]}...")
        print(f"      → {schedule['long_video_info']['scheduled_for']}")
    print(f"   Shorts: {schedule['shorts_scheduled']}/4 slots ({schedule['shorts_slots']})")

    # 6. Database Health
    print("\n💾 Checking database health...")
    db_health = check_database_health(db)
    results['database'] = db_health
    status = "✅" if db_health['healthy'] else "⚠️"
    print(f"   {status} Used sources: {db_health['used_source_ids']}")
    print(f"      Used long topics: {db_health['used_long_topics']}")
    print(f"      Total uploaded: {db_health['total_uploaded']}")
    if db_health['duplicate_source_ids'] > 0:
        print(f"   ⚠️  Duplicate source IDs found: {db_health['duplicate_source_ids']}")

    # 7. Recent Logs
    print("\n📝 Checking recent logs...")
    log_health = check_recent_logs(cfg.get_log_path())
    results['logs'] = log_health
    if log_health['exists']:
        if log_health['errors_last_24h'] == 0:
            print("   ✅ No errors in last 24h")
        else:
            print(f"   ⚠️  {log_health['errors_last_24h']} errors, {log_health['warnings_last_24h']} warnings in last 24h")
            if verbose and log_health['recent_errors']:
                for err in log_health['recent_errors']:
                    print(f"      ERROR: {err[:100]}")
    else:
        print("   ℹ️  No log file found")

    # Overall Status
    print("\n" + "=" * 60)
    all_ok = (
        disk.get('percent_used', 100) < 90 and
        ffmpeg['installed'] and
        pkgs['all_installed'] and
        quota['is_safe'] and
        db_health['healthy'] and
        log_health.get('errors_last_24h', 0) == 0
    )
    overall = "✅ HEALTHY" if all_ok else "⚠️  ISSUES DETECTED"
    print(f"  OVERALL STATUS: {overall}")
    print("=" * 60)

    return results


def fix_duplicates():
    """Remove duplicate source IDs from database."""
    db = load_db()
    source_ids = db.get('used_source_ids', [])
    unique = list(dict.fromkeys(source_ids))  # Preserve order
    removed = len(source_ids) - len(unique)

    if removed > 0:
        db['used_source_ids'] = unique
        from utils import save_db
        save_db(db)
        print(f"✅ Removed {removed} duplicate source IDs")
    else:
        print("✅ No duplicates found")


def show_recent_uploads(days: int = 7):
    """Show recently uploaded videos."""
    db = load_db()
    cutoff = datetime.now() - timedelta(days=days)

    print(f"\n📹 Videos uploaded in last {days} days:")
    print("-" * 60)

    count = 0
    for video in reversed(db.get('uploaded_videos', [])):
        try:
            ts = datetime.fromisoformat(video.get('scheduled_for', '').replace('+05:30', ''))
            if ts >= cutoff:
                print(f"  {ts.strftime('%m-%d %H:%M')} | {video['slot']:<30} | {video['id']}")
                count += 1
        except Exception:
            continue

    if count == 0:
        print("  (none)")
    print(f"\nTotal: {count} videos")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Health Check for DON OF VICE CITY")
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--fix-duplicates', action='store_true', help='Remove duplicate source IDs from DB')
    parser.add_argument('--recent', type=int, metavar='DAYS', help='Show recent uploads (default: 7 days)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

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

    # Exit code for monitoring systems
    sys.exit(0 if results.get('disk', {}).get('percent_used', 100) < 90 and
                  results.get('ffmpeg', {}).get('installed', False) and
                  results.get('packages', {}).get('all_installed', False) and
                  results.get('quota', {}).get('is_safe', False) and
                  results.get('database', {}).get('healthy', False) else 1)


if __name__ == '__main__':
    main()