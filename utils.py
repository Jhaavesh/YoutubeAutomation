"""
DON OF VICE CITY — Shared Utilities
Common functions used across all modules: DB, FFmpeg, sanitization, logging, quota tracking.
"""
import os
import sys
import json
import time
import logging
import subprocess
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from contextlib import contextmanager

# Add project root to path for config_loader
sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_config, get_channel_config, ConfigLoader, get_db_path, get_log_path


def get_logger(name: str = "autopilot", level: Optional[str] = None) -> logging.Logger:
    """Get or create a logger with proper configuration."""
    cfg = get_config()
    log_cfg = cfg.logging

    log_level = level or log_cfg.get('level', 'INFO')
    log_format = log_cfg.get('format', '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s')
    date_format = log_cfg.get('date_format', '%Y-%m-%d %H:%M:%S')

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()

    formatter = logging.Formatter(log_format, datefmt=date_format)

    # Console handler
    if log_cfg.get('console_enabled', True):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # File handler with rotation
    if log_cfg.get('file_enabled', True):
        log_file = get_log_path()
        max_bytes = log_cfg.get('max_log_size_mb', 10) * 1024 * 1024
        backup_count = log_cfg.get('backup_count', 5)

        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# Default logger (lazy initialization)
_log_cache = {}

def log():
    """Get cached logger instance."""
    if 'default' not in _log_cache:
        _log_cache['default'] = get_logger("autopilot")
    return _log_cache['default']


# ============================================================================
# FFMPEG HELPERS
# ============================================================================
def get_ffmpeg_exe() -> str:
    """Get FFmpeg executable path from config, with fallback to PATH."""
    cfg = get_config()
    return cfg.get_ffmpeg_exe()


def run_ffmpeg(cmd: List[str], description: str = "FFmpeg command", check: bool = True) -> subprocess.CompletedProcess:
    """Run FFmpeg command with logging and error handling."""
    ffmpeg_exe = get_ffmpeg_exe()
    full_cmd = [ffmpeg_exe] + cmd

    l = log()
    l.debug(f"Running {description}: {' '.join(full_cmd)}")

    try:
        result = subprocess.run(
            full_cmd,
            check=check,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        if result.stdout:
            l.debug(f"{description} stdout: {result.stdout[:500]}")
        return result
    except subprocess.CalledProcessError as e:
        l.error(f"{description} failed (exit code {e.returncode}): {e.stderr[:500]}")
        raise
    except Exception as e:
        l.error(f"{description} error: {e}")
        raise


def build_drawtext_filter(
    text: str,
    fontfile: str,
    fontcolor: str = "white",
    fontsize: int = 48,
    borderw: int = 4,
    bordercolor: str = "black",
    shadowcolor: str = "black@0.6",
    shadowx: int = 2,
    shadowy: int = 2,
    x: str = "(w-text_w)/2",
    y: str = "(h-text_h)/2",
) -> str:
    """Build a drawtext filter string with proper escaping."""
    escaped = text.replace('\\', '\\\\').replace(':', '\\:').replace("'", "").replace('&', 'AND').replace('%', '')
    return (
        f"drawtext=fontfile='{fontfile}':"
        f"text='{escaped}':"
        f"fontcolor={fontcolor}:"
        f"fontsize={fontsize}:"
        f"borderw={borderw}:"
        f"bordercolor={bordercolor}:"
        f"shadowcolor={shadowcolor}:"
        f"shadowx={shadowx}:"
        f"shadowy={shadowy}:"
        f"x={x}:"
        f"y={y}"
    )


# ============================================================================
# SANITIZATION
# ============================================================================
def sanitize_drawtext(text: str) -> str:
    """Sanitize text for FFmpeg drawtext filter."""
    text = text.replace('\\', '\\\\')
    text = text.replace(':', '\\:')
    text = text.replace("'", "")
    text = text.replace('&', 'AND')
    text = text.replace('%', '')
    return text


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for filesystem safety."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename.strip()


# ============================================================================
# DATABASE HELPERS
# ============================================================================
def load_db(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Load autopilot database with default structure."""
    cfg = get_config()
    path = db_path or cfg.get_db_path()

    default_db = {
        "scheduled_slots": {},
        "uploaded_videos": [],
        "used_source_ids": [],
        "daily_long_videos": {},
        "used_long_topics": [],
        "quota_usage": {},
    }

    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                db = json.load(f)
            for key, default_val in default_db.items():
                if key not in db:
                    db[key] = default_val
            return db
        except (json.JSONDecodeError, Exception) as e:
            log().warning(f"Failed to load DB, using defaults: {e}")

    return default_db


def save_db(db: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Save autopilot database atomically."""
    cfg = get_config()
    path = db_path or cfg.get_db_path()

    max_ids = cfg.deduplication.get('max_used_source_ids', 1000)
    if len(db.get('used_source_ids', [])) > max_ids:
        db['used_source_ids'] = db['used_source_ids'][-max_ids:]

    max_topics = cfg.deduplication.get('max_used_long_topics', 20)
    if len(db.get('used_long_topics', [])) > max_topics:
        db['used_long_topics'] = db['used_long_topics'][-max_topics:]

    temp_path = path + '.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
    except Exception as e:
        log().error(f"Failed to save DB: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise


@contextmanager
def db_transaction(db_path: Optional[str] = None):
    """Context manager for atomic DB read-modify-write."""
    db = load_db(db_path)
    try:
        yield db
        save_db(db, db_path)
    except Exception:
        raise


# ============================================================================
# QUOTA TRACKING
# ============================================================================
class QuotaTracker:
    """Track YouTube API quota usage per day."""

    def __init__(self, db: Dict[str, Any]):
        self.db = db
        self.today = datetime.now().strftime("%Y-%m-%d")
        cfg = get_config()
        self.limit = cfg.quota.daily_limit
        self.alert_threshold = cfg.quota.alert_threshold

        if 'quota_usage' not in self.db:
            self.db['quota_usage'] = {}

        if self.today not in self.db['quota_usage']:
            self.db['quota_usage'][self.today] = {
                'used': 0,
                'operations': []
            }

    @property
    def used_today(self) -> int:
        return self.db['quota_usage'][self.today]['used']

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used_today)

    @property
    def percent_used(self) -> float:
        return (self.used_today / self.limit) * 100 if self.limit > 0 else 0

    def add_usage(self, units: int, operation: str, video_id: str = "") -> None:
        """Record quota usage for an operation."""
        self.db['quota_usage'][self.today]['used'] += units
        self.db['quota_usage'][self.today]['operations'].append({
            'timestamp': datetime.now().isoformat(),
            'units': units,
            'operation': operation,
            'video_id': video_id
        })
        save_db(self.db)

    def check_and_warn(self, estimated_additional: int = 0) -> Tuple[bool, str]:
        """Check if quota is safe for additional operations."""
        projected = self.used_today + estimated_additional
        if projected > self.limit:
            return False, f"QUOTA EXCEEDED: {projected}/{self.limit} (would exceed limit)"
        if projected > self.limit * self.alert_threshold:
            return True, f"QUOTA WARNING: {projected}/{self.limit} ({projected/self.limit*100:.0f}% used)"
        return True, f"Quota OK: {projected}/{self.limit} ({projected/self.limit*100:.0f}% used)"

    def can_afford(self, units: int) -> bool:
        return (self.used_today + units) <= self.limit


# ============================================================================
# NETWORK HELPERS
# ============================================================================
def wait_for_internet(
    timeout_seconds: int = 300,
    check_interval: int = 10,
    test_url: str = "https://www.google.com"
) -> bool:
    """Wait for internet connectivity with configurable timeout."""
    import urllib.request

    l = log()
    l.info("Checking internet connectivity...")
    start_time = time.time()

    while time.time() - start_time < timeout_seconds:
        try:
            urllib.request.urlopen(test_url, timeout=5)
            l.info("Internet connection verified!")
            return True
        except Exception:
            remaining = timeout_seconds - (time.time() - start_time)
            l.info(f"No internet yet. Waiting {check_interval}s... ({remaining:.0f}s remaining)")
            time.sleep(check_interval)

    l.error(f"Internet check timed out after {timeout_seconds}s")
    return False


# ============================================================================
# SCHEDULE HELPERS
# ============================================================================
def compute_schedule_times(
    pending_slots: List[Dict],
    now: datetime,
    min_first_lead_minutes: int = 20,
    end_hour: int = 23,
    end_minute: int = 30,
    min_spread_hours: float = 1.5,
    late_interval_hours: int = 2,
    round_minutes: int = 5,
    standard_slots: Optional[List[Dict]] = None
) -> List[datetime]:
    """Compute scheduled publish times for pending slots."""
    min_first = now + timedelta(minutes=min_first_lead_minutes)
    end_of_day = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)

    use_standard = True
    standard_times = []

    if standard_slots:
        for slot in pending_slots:
            std_slot = next((s for s in standard_slots if s['slot_id'] == slot['slot_id']), None)
            if std_slot:
                st = now.replace(hour=std_slot['hour'], minute=std_slot['minute'], second=0, microsecond=0)
                if st < min_first:
                    use_standard = False
                    break
                standard_times.append(st)

    if use_standard and standard_times:
        return standard_times

    if end_of_day > min_first + timedelta(hours=min_spread_hours):
        total_seconds = (end_of_day - min_first).total_seconds()
        n = len(pending_slots)
        if n == 1:
            return [min_first]

        interval = total_seconds / (n - 1)
        schedule = []
        for i in range(n):
            dt = min_first + timedelta(seconds=i * interval)
            minute = (dt.minute // round_minutes) * round_minutes
            dt = dt.replace(minute=minute, second=0, microsecond=0)
            schedule.append(dt)
        return schedule
    else:
        return [min_first + timedelta(hours=late_interval_hours * i) for i in range(len(pending_slots))]


def format_iso_ist(dt: datetime) -> str:
    """Format datetime as ISO string with IST offset (+05:30)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")


def format_time_ist(dt: datetime) -> str:
    """Format datetime as 12-hour time string with AM/PM."""
    return dt.strftime("%I:%M %p")


# ============================================================================
# FILE CLEANUP
# ============================================================================
def cleanup_old_files(
    directory: str,
    max_age_hours: int = 24,
    delete_patterns: Optional[List[str]] = None,
    keep_recent_hours: int = 24
) -> Tuple[int, float]:
    """Clean up old files in directory."""
    if not os.path.exists(directory):
        return 0, 0.0

    cfg = get_config()
    delete_patterns = delete_patterns or cfg.cleanup.get('delete_patterns', [
        "*.part", "*.ytdl", "*.tmp", "raw_*"
    ])

    now_ts = time.time()
    cutoff_ts = now_ts - (max_age_hours * 3600)
    recent_cutoff = now_ts - (keep_recent_hours * 3600)

    cleaned_count = 0
    freed_bytes = 0

    for fname in os.listdir(directory):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue

        should_delete = False
        for pattern in delete_patterns:
            if _match_pattern(fname, pattern):
                should_delete = True
                break

        if not should_delete:
            mtime = os.path.getmtime(fpath)
            if mtime < cutoff_ts and mtime > recent_cutoff:
                continue
            if mtime < cutoff_ts:
                should_delete = True

        if should_delete:
            try:
                size = os.path.getsize(fpath)
                os.remove(fpath)
                freed_bytes += size
                cleaned_count += 1
                log().debug(f"Cleaned up: {fname} ({size/1024/1024:.2f} MB)")
            except Exception as e:
                log().warning(f"Failed to delete {fname}: {e}")

    freed_mb = freed_bytes / (1024 * 1024)
    if cleaned_count > 0:
        log().info(f"Cleanup: removed {cleaned_count} file(s), freed {freed_mb:.2f} MB")

    return cleaned_count, freed_mb


def _match_pattern(filename: str, pattern: str) -> bool:
    """Simple glob pattern matching."""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


# ============================================================================
# LOCK FILE
# ============================================================================
def acquire_lock(lock_path: Optional[str] = None) -> bool:
    """Acquire process lock to prevent concurrent runs."""
    cfg = get_config()
    if not cfg.lock_enabled:
        return True

    path = lock_path or cfg.get_lock_path()

    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                pid = int(f.read().strip())

            if cfg.lock_check_pid:
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True,
                    text=True
                )
                if str(pid) in result.stdout and 'python' in result.stdout.lower():
                    log().warning(f"Another autopilot instance (PID {pid}) is running! Exiting.")
                    return False
        except Exception:
            pass

    try:
        with open(path, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        log().error(f"Failed to acquire lock: {e}")
        return True


def release_lock(lock_path: Optional[str] = None) -> None:
    """Release process lock."""
    cfg = get_config()
    path = lock_path or cfg.get_lock_path()

    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            log().warning(f"Failed to release lock: {e}")


# ============================================================================
# TIMESTAMP HELPERS
# ============================================================================
def get_timestamp() -> int:
    """Get current Unix timestamp."""
    return int(time.time())


def get_date_key() -> str:
    """Get today's date key (YYYY-MM-DD)."""
    return datetime.now().strftime("%Y-%m-%d")


# ============================================================================
# VIDEO HELPERS
# ============================================================================
def get_audio_track() -> str:
    """Get path to background audio track."""
    cfg = get_config()
    audio_tracks = cfg.audio_tracks
    if not audio_tracks:
        raise ValueError("No audio tracks configured in config.yaml")

    track = audio_tracks[0]
    return cfg.get_assets_audio_path(track['filename'])


def ensure_output_dirs() -> None:
    """Ensure output and assets directories exist."""
    cfg = get_config()
    os.makedirs(cfg.get_output_path(), exist_ok=True)
    os.makedirs(cfg.get_assets_audio_path(), exist_ok=True)


# ============================================================================
# MAIN EXECUTION WRAPPER
# ============================================================================
def run_with_lock(main_func, lock_path: Optional[str] = None, cleanup_on_exit: bool = True):
    """
    Wrapper to run main function with lock, cleanup, and error handling.

    Usage:
        def my_main():
            # your code
            pass

        if __name__ == '__main__':
            run_with_lock(my_main)
    """
    if not acquire_lock(lock_path):
        sys.exit(1)

    try:
        ensure_output_dirs()
        cleanup_old_files(get_config().get_output_path())
        return main_func()
    except KeyboardInterrupt:
        log().warning("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        log().exception(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        if cleanup_on_exit:
            cleanup_old_files(get_config().get_output_path())
        release_lock(lock_path)


if __name__ == '__main__':
    print("Testing utils...")
    try:
        print(f"FFmpeg: {get_ffmpeg_exe()}")
        print(f"Audio track: {get_audio_track()}")
        print(f"Config: {get_config().default_channel}")

        db = load_db()
        print(f"DB loaded: {len(db.get('used_source_ids', []))} used sources")

        tracker = QuotaTracker(db)
        print(f"Quota: {tracker.used_today}/{tracker.limit} used")
        safe, msg = tracker.check_and_warn(8000)
        print(f"Quota check: {msg}")

        print("✅ All utils working!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)