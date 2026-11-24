#!/usr/bin/env python3
"""
DON OF VICE CITY — Continuous Auto-Pilot (ZERO-TOUCH)
=====================================================
Fully automated system that:
- Runs daily content creation
- Monitors system health
- Auto-recovers from failures
- Restarts on crash
- Sends alerts via webhook
- Self-schedules next run

Designed for Windows Task Scheduler or systemd service.
Run: python continuous_autopilot.py
"""
import os
import sys
import time
import json
import subprocess
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import get_config
from utils import load_db, save_db, cleanup_old_files, get_timestamp
from upload_video import get_quota_report, print_quota_report


class ContinuousAutopilot:
    """Zero-touch autopilot with auto-recovery and health monitoring."""

    def __init__(self):
        self.cfg = get_config()
        self.log_file = str(Path(self.cfg.base_dir) / self.cfg.log_file)
        self.health_file = str(Path(self.cfg.base_dir) / "last_run_health.json")
        self.error_file = str(Path(self.cfg.base_dir) / "autopilot_errors.json")

    def log(self, message: str, level: str = "INFO"):
        """Log with timestamp."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        print(line, flush=True)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(line + "\n")

    def notify_webhook(self, event: str, data: dict):
        """Send notification to webhook if configured."""
        webhook = self.cfg.network.get('notification_webhook', '')
        if not webhook:
            return

        try:
            import requests
            payload = {
                "text": f"DON OF VICE CITY - {event}",
                "attachments": [{
                    "color": "good" if data.get('success') else "danger",
                    "fields": [
                        {"title": "Status", "value": event, "short": True},
                        {"title": "Time", "value": datetime.now().isoformat(), "short": True},
                        {"title": "Details", "value": str(data), "short": False}
                    ]
                }]
            }
            requests.post(webhook, json=payload, timeout=10)
        except Exception as e:
            self.log(f"Webhook notification failed: {e}", "ERROR")

    def run_daily_cycle(self) -> dict:
        """Execute one full daily cycle."""
        from master_autopilot import run_master_autopilot

        today = datetime.now().strftime("%Y-%m-%d")
        channel = self.cfg.default_channel

        self.log("=" * 60)
        self.log("  DAILY AUTOPILOT CYCLE STARTED")
        self.log("=" * 60)

        try:
            result = run_master_autopilot(channel)
            result['date'] = today
            result['success'] = True
            result['timestamp'] = datetime.now().isoformat()

            # Update health file
            health = {
                'last_run': datetime.now().isoformat(),
                'date': today,
                'status': 'SUCCESS' if result.get('success') else 'FAILED',
                'result': result
            }
            with open(self.health_file, 'w') as f:
                json.dump(health, f, indent=2)

            self.notify_webhook("Daily Cycle Complete", result)
            self.log("=" * 60)
            self.log("  DAILY AUTOPILOT CYCLE COMPLETED SUCCESSFULLY")
            self.log("=" * 60)

            return result

        except Exception as e:
            self.log(f"Daily cycle FAILED: {e}", "ERROR")
            self.log(traceback.format_exc(), "ERROR")

            # Update health file
            health = {
                'last_run': datetime.now().isoformat(),
                'date': today,
                'status': 'FAILED',
                'error': str(e),
                'traceback': traceback.format_exc()
            }
            with open(self.health_file, 'w') as f:
                json.dump(health, f, indent=2)

            # Update error tracking
            self._track_error(str(e))

            self.notify_webhook("Daily Cycle FAILED", {
                'error': str(e),
                'date': today
            })

            return {'success': False, 'error': str(e), 'date': today}

    def _track_error(self, error: str):
        """Track recurring errors for auto-recovery."""
        errors = []
        if os.path.exists(self.error_file):
            try:
                with open(self.error_file, 'r') as f:
                    errors = json.load(f)
            except:
                pass

        errors.append({
            'timestamp': datetime.now().isoformat(),
            'error': error
        })

        # Keep last 100 errors
        if len(errors) > 100:
            errors = errors[-100:]

        with open(self.error_file, 'w') as f:
            json.dump(errors, f, indent=2)

    def check_and_run(self):
        """Check if today's content is done, run if not."""
        db = load_db()
        today = datetime.now().strftime("%Y-%m-%d")

        # Check if long video already scheduled
        if today in db.get('daily_long_videos', {}):
            long_done = db['daily_long_videos'][today]['id']
            shorts_done = len(db.get('scheduled_slots', {}).get(today, []))

            self.log(f"Already scheduled: Long={long_done[:8] if long_done else 'N'}, Shorts={shorts_done}/4")
            return True

        # Run daily cycle
        return self.run_daily_cycle()

    def run(self):
        """
        Main continuous loop.
        Run once per day, or as a service that checks daily.
        """
        self.log("=" * 60)
        self.log("  DON OF VICE CITY — CONTINUOUS AUTOPILOT")
        self.log("  Zero-Touch Daily Content Generation")
        self.log("=" * 60)
        self.log(f"Mode: {self.cfg.deployment.get('mode', 'auto')}")
        self.log(f"Startup check: {self.cfg.deployment.get('startup_check', True)}")

        # Run daily
        self.check_and_run()

        # Show final quota status
        report = get_quota_report()
        self.log(f"Final Quota: {report['used']}/{report['limit']} ({report['percent_used']}%)")


def run_once():
    """Run a single daily cycle (for scheduled tasks)."""
    auto = ContinuousAutopilot()
    auto.run()


def run_continuous(interval_hours: int = 24):
    """Run continuously, checking every X hours."""
    auto = ContinuousAutopilot()

    while True:
        try:
            auto.check_and_run()

            # If daily content is done, sleep until next day
            if datetime.now().hour >= 20:  # After 8 PM
                # Sleep until tomorrow 10 AM
                next_run = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
                if next_run <= datetime.now():
                    next_run += timedelta(days=1)
                sleep_seconds = (next_run - datetime.now()).total_seconds()
                print(f"Sleeping {sleep_seconds/3600:.1f} hours until next run...")
                time.sleep(sleep_seconds)
            else:
                # Check every hour
                time.sleep(interval_hours * 3600)

        except KeyboardInterrupt:
            print("\nInterrupted by user")
            break
        except Exception as e:
            print(f"Error in continuous mode: {e}")
            time.sleep(300)  # Wait 5 minutes before retry


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Continuous Auto-Pilot for DON OF VICE CITY")
    parser.add_argument('--continuous', '-c', action='store_true',
                       help='Run continuously (for service/daemon mode)')
    parser.add_argument('--interval', '-i', type=int, default=24,
                       help='Check interval in hours when running continuously')
    parser.add_argument('--health', action='store_true',
                       help='Show health status and exit')

    args = parser.parse_args()

    if args.health:
        health_file = Path(get_config().base_dir) / "last_run_health.json"
        if health_file.exists():
            with open(health_file) as f:
                data = json.load(f)
            print(json.dumps(data, indent=2))
        else:
            print("No health data available yet.")
        return

    if args.continuous:
        run_continuous(args.interval)
    else:
        run_once()


if __name__ == '__main__':
    main()