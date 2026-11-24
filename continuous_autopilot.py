#!/usr/bin/env python3
"""
DON OF VICE CITY — Continuous Auto-Pilot
=========================================
Runs the daily pipeline, records health, sends optional webhook alerts, and
can stay alive as a service.  Every cycle respects the single-instance lock.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import get_config
from utils import (
    acquire_lock,
    cleanup_old_files,
    get_date_key,
    load_db,
    now_local,
    release_lock,
    setup_logging,
)


class ContinuousAutopilot:
    """Daily autopilot with health tracking and optional auto-recovery."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.logger = setup_logging("continuous_autopilot")
        self.health_file = str(Path(self.cfg.base_dir) / "last_run_health.json")
        self.error_file = str(Path(self.cfg.base_dir) / "autopilot_errors.json")

    def log(self, message: str, level: str = "INFO") -> None:
        """Log through the shared rotating logger."""
        getattr(self.logger, level.lower(), self.logger.info)(message)

    def _write_json_atomic(self, path: str, payload: Any) -> None:
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)

    def notify_webhook(self, event: str, data: Dict[str, Any]) -> None:
        """Send a notification to the configured webhook, if any."""
        webhook = (
            self.cfg.deployment.get("notification_webhook")
            or self.cfg.network.get("notification_webhook")
            or ""
        )
        if not webhook:
            return

        try:
            import requests

            payload = {
                "text": f"DON OF VICE CITY - {event}",
                "attachments": [
                    {
                        "color": "good" if data.get("success") else "danger",
                        "fields": [
                            {"title": "Status", "value": event, "short": True},
                            {
                                "title": "Time",
                                "value": now_local().isoformat(timespec="seconds"),
                                "short": True,
                            },
                            {
                                "title": "Details",
                                "value": str(data)[:1500],
                                "short": False,
                            },
                        ],
                    }
                ],
            }
            requests.post(webhook, json=payload, timeout=10)
        except Exception as exc:
            self.log(f"Webhook notification failed: {exc}", "ERROR")

    def run_daily_cycle(self) -> Dict[str, Any]:
        """Execute one full daily cycle and record the real result."""
        from master_autopilot import run_master_autopilot

        today = get_date_key()
        channel = self.cfg.default_channel

        self.log("=" * 60)
        self.log("  DAILY AUTOPILOT CYCLE STARTED")
        self.log("=" * 60)

        try:
            result = run_master_autopilot(channel)
            result.setdefault("date", today)
            result["timestamp"] = now_local().isoformat(timespec="seconds")
            success = bool(result.get("success"))

            self._write_json_atomic(
                self.health_file,
                {
                    "last_run": result["timestamp"],
                    "date": today,
                    "status": "SUCCESS" if success else "FAILED",
                    "result": result,
                },
            )

            self.notify_webhook(
                "Daily Cycle Complete" if success else "Daily Cycle Failed",
                result,
            )
            self.log(
                "Daily cycle completed successfully"
                if success
                else "Daily cycle finished with errors",
                "INFO" if success else "ERROR",
            )
            return result

        except Exception as exc:
            self.log(f"Daily cycle FAILED: {exc}", "ERROR")
            self.log(traceback.format_exc(), "ERROR")
            self._write_json_atomic(
                self.health_file,
                {
                    "last_run": now_local().isoformat(timespec="seconds"),
                    "date": today,
                    "status": "FAILED",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            self._track_error(str(exc))
            self.notify_webhook(
                "Daily Cycle FAILED",
                {"success": False, "error": str(exc), "date": today},
            )
            return {"success": False, "error": str(exc), "date": today}

    def _track_error(self, error: str) -> None:
        """Keep the last 100 errors for diagnostics."""
        errors = []
        if os.path.exists(self.error_file):
            try:
                with open(self.error_file, "r", encoding="utf-8") as handle:
                    errors = json.load(handle)
            except Exception:
                errors = []

        errors.append(
            {
                "timestamp": now_local().isoformat(timespec="seconds"),
                "error": error,
            }
        )
        errors = errors[-100:]
        self._write_json_atomic(self.error_file, errors)

    def check_and_run(self) -> Dict[str, Any]:
        """Run only when today's requested content is not already complete."""
        db = load_db()
        today = get_date_key()
        expected_shorts = len(self.cfg.schedule.shorts_standard_slots)
        long_done = today in db.get("daily_long_videos", {})
        shorts_done = len(db.get("scheduled_slots", {}).get(today, []))

        if long_done and shorts_done >= expected_shorts:
            self.log(
                f"Already complete: Long={long_done}, Shorts={shorts_done}/"
                f"{expected_shorts}"
            )
            return {
                "success": True,
                "skipped": True,
                "date": today,
                "shorts_scheduled": shorts_done,
            }

        return self.run_daily_cycle()

    def run(self) -> Dict[str, Any]:
        """Run one cycle and show final quota status."""
        self.log("=" * 60)
        self.log("  DON OF VICE CITY — CONTINUOUS AUTOPILOT")
        self.log("=" * 60)
        self.log(f"Mode: {self.cfg.deployment.get('mode', 'auto')}")
        self.log(
            f"Startup check: {self.cfg.deployment.get('startup_check', True)}"
        )

        result = self.check_and_run()

        from upload_video import get_quota_report

        report = get_quota_report()
        self.log(
            f"Final Quota: {report['used']}/{report['limit']} "
            f"({report['percent_used']}%); uploads "
            f"{report['uploads']}/{report['upload_limit']}"
        )
        return result


def _run_with_single_instance_lock(auto: ContinuousAutopilot) -> Optional[Dict[str, Any]]:
    """Run one cycle while holding the process lock."""
    if not acquire_lock():
        return None
    try:
        return auto.check_and_run()
    finally:
        release_lock()


def run_once() -> int:
    """Run a single daily cycle (for scheduled tasks)."""
    auto = ContinuousAutopilot()
    result = _run_with_single_instance_lock(auto)
    if result is None:
        return 1
    return 0 if result.get("success") else 1


def run_continuous(interval_hours: int = 24) -> int:
    """Run continuously, checking every X hours."""
    auto = ContinuousAutopilot()

    while True:
        try:
            result = _run_with_single_instance_lock(auto)
            if result is None:
                auto.log("Another instance holds the lock; waiting.", "WARNING")
                time.sleep(300)
                continue

            if now_local().hour >= 20:
                next_run = now_local().replace(
                    hour=10, minute=0, second=0, microsecond=0
                )
                if next_run <= now_local():
                    next_run += timedelta(days=1)
                sleep_seconds = (next_run - now_local()).total_seconds()
                auto.log(f"Sleeping {sleep_seconds / 3600:.1f} hours until next run")
                time.sleep(sleep_seconds)
            else:
                time.sleep(interval_hours * 3600)

        except KeyboardInterrupt:
            auto.log("Interrupted by user", "WARNING")
            return 0
        except Exception as exc:
            auto.log(f"Error in continuous mode: {exc}", "ERROR")
            time.sleep(300)


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Continuous Auto-Pilot for DON OF VICE CITY"
    )
    parser.add_argument(
        "--continuous",
        "-c",
        action="store_true",
        help="Run continuously (for service/daemon mode)",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=24,
        help="Check interval in hours when running continuously",
    )
    parser.add_argument(
        "--health", action="store_true", help="Show health status and exit"
    )

    args = parser.parse_args()

    if args.health:
        health_file = Path(get_config().base_dir) / "last_run_health.json"
        if health_file.exists():
            with open(health_file, "r", encoding="utf-8") as handle:
                print(json.dumps(json.load(handle), indent=2))
        else:
            print("No health data available yet.")
        return

    if args.continuous:
        sys.exit(run_continuous(args.interval))
    sys.exit(run_once())


if __name__ == "__main__":
    main()
