#!/usr/bin/env python3
"""
DON OF VICE CITY — Read-only preflight doctor.

Checks the things that usually break an unattended run:
config, assets, Python imports, FFmpeg, OAuth scopes, state files, the Windows
scheduled task, and the latest rendered media.  It never uploads, refreshes a
token, or changes state.

Usage:
    python doctor.py
    python doctor.py --json
    python doctor.py --skip-task
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))

from config_loader import get_config
from health_check import (
    check_database_health,
    check_disk_space,
    check_ffmpeg,
    check_python_packages,
    check_quota,
    check_token,
)
from utils import load_db, load_ledger, probe_video, setup_logging

TASK_NAME = "DonOfViceCity_DailyShorts"


def check_imports() -> Dict[str, Any]:
    modules = [
        "config_loader",
        "utils",
        "upload_video",
        "long_video_engine",
        "auto_pilot_bot",
        "master_autopilot",
        "continuous_autopilot",
        "health_check",
    ]
    failures = {}
    for name in modules:
        try:
            __import__(name)
        except Exception as exc:
            failures[name] = str(exc)
    return {"ok": not failures, "failures": failures}


def check_config_shape(cfg: Any) -> Dict[str, Any]:
    problems: List[str] = []
    if not cfg.channels:
        problems.append("no channels configured")
    if cfg.default_channel not in cfg.channels:
        problems.append("default channel is not in channels.accounts")
    if not cfg.long_video_pool:
        problems.append("topics.long_video_pool is empty")
    if not cfg.shorts_pool:
        problems.append("topics.shorts_pool is empty")
    if not cfg.schedule.shorts_standard_slots:
        problems.append("schedule.shorts.standard_slots is empty")
    if not cfg.audio_tracks:
        problems.append("audio.background_tracks is empty")
    return {"ok": not problems, "problems": problems}


def check_assets(cfg: Any) -> Dict[str, Any]:
    results = {"audio": [], "fonts": [], "output_dir": cfg.get_output_path()}
    for track in cfg.audio_tracks:
        filename = track.get("filename") if isinstance(track, dict) else None
        if not filename:
            results["audio"].append({"file": None, "exists": False})
            continue
        path = cfg.get_assets_audio_path(str(filename))
        results["audio"].append({"file": path, "exists": os.path.isfile(path)})
    for label, path in (
        ("primary", cfg.video.font_primary),
        ("fallback", cfg.video.font_fallback),
    ):
        results["fonts"].append(
            {"label": label, "file": path, "exists": os.path.isfile(path)}
        )
    results["ok"] = all(item["exists"] for item in results["audio"]) and os.path.isdir(
        cfg.get_output_path()
    )
    return results


def check_state(cfg: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    db_path = cfg.get_db_path()
    ledger_path = cfg.get_ledger_path()
    result["db_exists"] = os.path.isfile(db_path)
    result["ledger_exists"] = os.path.isfile(ledger_path)
    try:
        db = load_db(db_path)
        result["db_health"] = check_database_health(db)
    except Exception as exc:
        result["db_error"] = str(exc)
    try:
        ledger = load_ledger(ledger_path)
        result["ledger_entries"] = len(ledger.get("uploads", {}))
    except Exception as exc:
        result["ledger_error"] = str(exc)
    lock_path = cfg.get_lock_path()
    result["lock_exists"] = os.path.isfile(lock_path)
    if result["lock_exists"]:
        try:
            result["lock_pid"] = int(Path(lock_path).read_text(encoding="utf-8").strip())
        except Exception:
            result["lock_pid"] = None
    return result


def check_latest_outputs(cfg: Any) -> Dict[str, Any]:
    output_dir = Path(cfg.get_output_path())
    results: Dict[str, Any] = {"long": None, "short": None}
    if not output_dir.is_dir():
        return results
    patterns = {
        "long": ["final_long_*.mp4"],
        "short": ["final_slot*.mp4", "final_short_*.mp4"],
    }
    for label, label_patterns in patterns.items():
        files = []
        for pattern in label_patterns:
            files.extend(output_dir.glob(pattern))
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        if not files:
            continue
        latest = files[0]
        try:
            info = probe_video(str(latest))
            info["file"] = latest.name
            info["size_mb"] = round(info["size_bytes"] / (1024 * 1024), 1)
            results[label] = info
        except Exception as exc:
            results[label] = {"file": latest.name, "error": str(exc)}
    return results


def check_windows_task() -> Dict[str, Any]:
    if os.name != "nt":
        return {"supported": False}
    try:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            return {"supported": True, "found": False, "error": proc.stderr.strip()}
        fields = {}
        for line in proc.stdout.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        return {
            "supported": True,
            "found": True,
            "status": fields.get("Status"),
            "last_run": fields.get("Last Run Time"),
            "last_result": fields.get("Last Result"),
            "next_run": fields.get("Next Run Time"),
        }
    except Exception as exc:
        return {"supported": True, "found": False, "error": str(exc)}


def run_doctor(skip_task: bool = False) -> Dict[str, Any]:
    setup_logging("doctor")
    cfg = get_config()
    results: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "base_dir": cfg.base_dir,
        "channel": cfg.default_channel,
        "timezone": cfg.schedule.timezone,
        "imports": check_imports(),
        "config": check_config_shape(cfg),
        "assets": check_assets(cfg),
        "disk": check_disk_space(cfg.base_dir),
        "packages": check_python_packages(),
        "ffmpeg": check_ffmpeg(),
        "token": check_token(cfg.default_channel),
        "quota": check_quota(),
        "state": check_state(cfg),
        "latest_outputs": check_latest_outputs(cfg),
    }
    if not skip_task:
        results["windows_task"] = check_windows_task()
    return results


def print_report(results: Dict[str, Any]) -> None:
    print("=" * 64)
    print("  DON OF VICE CITY — PREFLIGHT DOCTOR")
    print("=" * 64)
    print(f"Python:  {results['python']}")
    print(f"Project: {results['base_dir']}")
    print(f"Channel: {results['channel']}")
    print(f"Timezone: {results['timezone']}")
    print()

    def line(label: str, ok: bool, detail: str = "", warn: bool = False) -> None:
        status = "OK" if ok else ("WARN" if warn else "FAIL")
        print(f"  [{status}] {label}" + (f": {detail}" if detail else ""))

    line("Python imports", results["imports"]["ok"], str(results["imports"]["failures"] or ""))
    line("Config sections", results["config"]["ok"], ", ".join(results["config"]["problems"]))
    line("Audio/font assets", results["assets"]["ok"])
    for item in results["assets"]["audio"]:
        print(f"        audio: {item['file']} -> {item['exists']}")
    for item in results["assets"]["fonts"]:
        print(f"        font {item['label']}: {item['file']} -> {item['exists']}")

    disk = results["disk"]
    line(
        "Disk space",
        disk.get("percent_used", 100) < 90,
        f"{disk.get('free_gb', '?')} GB free ({disk.get('percent_used', '?')}% used)",
    )
    line(
        "Python packages",
        results["packages"]["all_installed"],
        ", ".join(results["packages"]["missing"]),
    )
    ffmpeg = results["ffmpeg"]
    line("FFmpeg", ffmpeg.get("installed", False), ffmpeg.get("version", ffmpeg.get("error", "")))
    print(f"        ffprobe: {ffmpeg.get('ffprobe', '?')}")

    token = results["token"]
    line("OAuth token exists", token["exists"], token["path"])
    line("Upload scope", token.get("upload_ready", False))
    line("Metadata update/delete scope", token.get("metadata_ready", False), warn=True)
    line("Analytics scope", token.get("analytics_ready", False), warn=True)
    if not token.get("metadata_ready") or not token.get("analytics_ready"):
        print("        Optional for uploads; re-authenticate to enable them:")
        print("        python setup_auth.py --channel <key>")

    quota = results["quota"]
    line(
        "Quota",
        quota["is_safe"],
        f"{quota['used']}/{quota['limit']} units; uploads "
        f"{quota['uploads']}/{quota['upload_limit']}",
    )

    state = results["state"]
    line("Database exists", state["db_exists"], results["state"].get("db_error", ""))
    line(
        "Upload ledger",
        True,
        "ready" if state["ledger_exists"] else "not created yet (first upload creates it)",
    )
    if state.get("db_health"):
        print(f"        DB healthy: {state['db_health']['healthy']}")
    print(f"        Ledger entries: {state.get('ledger_entries', 0)}")
    print(f"        Lock file present: {state.get('lock_exists')} (PID {state.get('lock_pid')})")

    for label in ("long", "short"):
        item = results["latest_outputs"].get(label)
        if not item:
            print(f"  [--] Latest {label} output: none")
        elif item.get("error"):
            print(f"  [FAIL] Latest {label} output: {item['file']}: {item['error']}")
        else:
            print(
                f"  [OK] Latest {label} output: {item['file']} "
                f"{item['width']}x{item['height']} "
                f"{item['duration']:.1f}s {item['size_mb']} MB"
            )

    task = results.get("windows_task")
    if task and task.get("supported"):
        if task.get("found"):
            print(
                f"  [{'OK' if task.get('last_result') == '0' else 'WARN'}] "
                f"Scheduled task: {task.get('status')}, last result "
                f"{task.get('last_result')}, next {task.get('next_run')}"
            )
        else:
            print(f"  [WARN] Scheduled task not found: {task.get('error', '')}")
    print("=" * 64)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Read-only preflight doctor")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument("--skip-task", action="store_true", help="Skip Task Scheduler check")
    args = parser.parse_args()

    results = run_doctor(skip_task=args.skip_task)
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_report(results)

    critical_ok = (
        results["imports"]["ok"]
        and results["config"]["ok"]
        and results["assets"]["ok"]
        and results["packages"]["all_installed"]
        and results["ffmpeg"].get("installed", False)
        and results["token"].get("upload_ready", False)
        and results["quota"]["is_safe"]
    )
    sys.exit(0 if critical_ok else 1)


if __name__ == "__main__":
    main()
