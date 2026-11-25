"""
DON OF VICE CITY — Shared Utilities
Common functions used across all modules: DB, FFmpeg, sanitization, logging, quota tracking.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    import msvcrt  # Windows process/file locking
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None
    import fcntl

# Add project root to path for config_loader
sys.path.insert(0, str(Path(__file__).parent))
from config_loader import (  # noqa: E402
    Config,
    ConfigLoader,
    get_channel_config,
    get_config,
    get_db_path,
    get_log_path,
)

# ============================================================================
# LOGGING
# ============================================================================
_SECRET_PATTERNS = (
    re.compile(r"(access_token\s*[=:]\s*)([^\s,&]+)", re.IGNORECASE),
    re.compile(r"(refresh_token\s*[=:]\s*)([^\s,&]+)", re.IGNORECASE),
    re.compile(r"(client_secret\s*[=:]\s*)([^\s,&]+)", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[=:]\s*)([^\s,&]+)", re.IGNORECASE),
    re.compile(r"(authorization:\s*bearer\s+)(\S+)", re.IGNORECASE),
)


class _SecretRedactionFilter(logging.Filter):
    """Prevent credentials from leaking into console or rotating logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


_logging_lock = None
_logging_configured = False
_log_cache: Dict[str, logging.Logger] = {}


def _reconfigure_std_streams() -> None:
    """Make Windows console output UTF-8 safe for emoji/unicode log messages."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def setup_logging(name: str = "autopilot", level: Optional[str] = None) -> logging.Logger:
    """Configure application logging once and return a named logger.

    The root logger owns the handlers, so third-party modules that simply call
    ``logging.getLogger(__name__)`` also get the same structured output.
    """
    global _logging_configured

    if not _logging_configured:
        _reconfigure_std_streams()
        cfg = get_config()
        log_cfg = cfg.logging
        log_level = (level or log_cfg.get("level", "INFO") or "INFO").upper()
        log_format = log_cfg.get(
            "format", "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
        date_format = log_cfg.get("date_format", "%Y-%m-%d %H:%M:%S")
        formatter = logging.Formatter(log_format, datefmt=date_format)
        redaction = _SecretRedactionFilter()

        root = logging.getLogger()
        root.setLevel(getattr(logging, log_level, logging.INFO))
        root.handlers.clear()

        if log_cfg.get("console_enabled", True):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            console_handler.addFilter(redaction)
            root.addHandler(console_handler)

        if log_cfg.get("file_enabled", True):
            log_file = get_log_path()
            try:
                Path(log_file).parent.mkdir(parents=True, exist_ok=True)
                from logging.handlers import RotatingFileHandler

                max_bytes = int(log_cfg.get("max_log_size_mb", 10)) * 1024 * 1024
                backup_count = int(log_cfg.get("backup_count", 5))
                file_handler = RotatingFileHandler(
                    log_file,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                file_handler.addFilter(redaction)
                root.addHandler(file_handler)
            except OSError as exc:
                # Do not crash the overnight pipeline because a log file is
                # temporarily locked by another process.
                logging.getLogger(__name__).warning(
                    "Could not open log file %s: %s", log_file, exc
                )

        logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
        logging.getLogger("googleapiclient").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("yt_dlp").setLevel(logging.WARNING)
        _logging_configured = True

    logger = logging.getLogger(name)
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


def get_logger(name: str = "autopilot", level: Optional[str] = None) -> logging.Logger:
    """Backward-compatible alias for :func:`setup_logging`."""
    return setup_logging(name, level)


def log() -> logging.Logger:
    """Get the cached default application logger."""
    if "default" not in _log_cache:
        _log_cache["default"] = setup_logging("autopilot")
    return _log_cache["default"]


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


def get_ffprobe_exe() -> str:
    """Get FFprobe executable path from config, with fallback to PATH."""
    return get_config().get_ffprobe_exe()


def probe_video(path: str) -> Dict[str, Any]:
    """Return the first video stream and format metadata using ffprobe.

    Raises RuntimeError with a useful message when ffprobe cannot read the
    file, so callers never hand an unreadable file to YouTube.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Video file not found: {path}")
    if os.path.getsize(path) <= 0:
        raise ValueError(f"Video file is empty: {path}")

    cmd = [
        get_ffprobe_exe(),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe could not read {path}: {(result.stderr or '').strip()[:500]}"
        )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc

    streams = payload.get("streams", []) or []
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )
    if video_stream is None:
        raise RuntimeError(f"No video stream found in {path}")

    fmt = payload.get("format", {}) or {}
    try:
        duration = float(fmt.get("duration") or video_stream.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    return {
        "path": path,
        "size_bytes": os.path.getsize(path),
        "duration": duration,
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": (audio_stream or {}).get("codec_name"),
        "has_audio": audio_stream is not None,
        "format_name": fmt.get("format_name"),
    }


def validate_video_file(
    path: str,
    min_duration: float = 1.0,
    require_audio: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate a rendered video before upload.

    Returns ``(ok, message, metadata)``.  This is deliberately read-only and
    does not upload anything.
    """
    try:
        info = probe_video(path)
    except Exception as exc:
        return False, str(exc), {}

    if info["duration"] < min_duration:
        return (
            False,
            f"Video is too short ({info['duration']:.2f}s < {min_duration:.2f}s)",
            info,
        )
    if info["width"] <= 0 or info["height"] <= 0:
        return False, "Video has invalid dimensions", info
    if require_audio and not info["has_audio"]:
        return False, "Video has no audio stream", info
    return True, "OK", info


def resolution_to_filter_size(resolution: str) -> str:
    """Convert ``2560x1440`` to the ``2560:1440`` form used by pad/crop/scale."""
    width, separator, height = resolution.lower().partition("x")
    if not separator or not width.strip() or not height.strip():
        raise ValueError(f"Invalid resolution '{resolution}'; expected WIDTHxHEIGHT")
    return f"{width.strip()}:{height.strip()}"


def get_drawtext_font(font_path: str) -> str:
    """Return a colon-free font path for FFmpeg's drawtext filter.

    FFmpeg treats ``:`` as a filter-option separator, so an absolute Windows
    path such as ``C:/Windows/Fonts/ariblk.ttf`` breaks the filter graph.
    A path relative to the current working directory avoids the drive colon
    entirely.  Callers must run from the project directory (the launchers do).
    """
    relative = os.path.relpath(font_path, os.getcwd()).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", relative):
        raise ValueError(
            f"Font '{font_path}' is on a different drive than the project; "
            "copy it into the project directory instead"
        )
    return relative


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
        f"drawtext=fontfile={format_drawtext_path(fontfile)}:"
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
@contextmanager
def file_lock(lock_path: str) -> Iterator[None]:
    """Cross-process advisory lock for small state files.

    On Windows this uses ``msvcrt.locking``; on POSIX it uses ``fcntl.flock``.
    The lock is held only while reading/modifying/writing a JSON file.
    """
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        # msvcrt.locking needs at least one byte at the current position.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - POSIX
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if msvcrt is not None:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - POSIX
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()


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


def save_db(
    db: Dict[str, Any],
    db_path: Optional[str] = None,
    lock: bool = True,
) -> None:
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
    lock_context = file_lock(path + '.lock') if lock else _null_context()
    try:
        with lock_context:
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
def _null_context() -> Iterator[None]:
    yield


@contextmanager
def db_transaction(db_path: Optional[str] = None):
    """Context manager for atomic DB read-modify-write.

    Holds an OS-level file lock across the read and write so two processes
    cannot silently overwrite each other's updates.
    """
    cfg = get_config()
    path = db_path or cfg.get_db_path()
    with file_lock(path + '.lock'):
        db = load_db(path)
        yield db
        save_db(db, path, lock=False)


# ============================================================================
# UPLOAD LEDGER (IDEMPOTENCY)
# ============================================================================
def _default_ledger() -> Dict[str, Any]:
    return {"version": 1, "uploads": {}}


def load_ledger(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the upload ledger, returning an empty ledger if missing/corrupt."""
    ledger_path = Path(path or get_config().get_ledger_path())
    if not ledger_path.is_file():
        return _default_ledger()
    try:
        with ledger_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("ledger root is not an object")
        data.setdefault("version", 1)
        data.setdefault("uploads", {})
        if not isinstance(data["uploads"], dict):
            raise ValueError("ledger uploads is not an object")
        return data
    except Exception as exc:
        log().warning("Could not read upload ledger %s: %s", ledger_path, exc)
        return _default_ledger()


def save_ledger(ledger: Dict[str, Any], path: Optional[str] = None) -> None:
    """Atomically save the upload ledger."""
    ledger_path = Path(path or get_config().get_ledger_path())
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    with file_lock(str(ledger_path) + ".lock"):
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(ledger, handle, indent=2, ensure_ascii=False)
        os.replace(temp_path, ledger_path)


def file_sha256(path: str, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it all into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_upload_key(file_path: str, channel_key: str) -> Tuple[str, str]:
    """Return ``(idempotency_key, sha256)`` for an upload."""
    digest = file_sha256(file_path)
    return f"{channel_key}:{digest}", digest


def find_ledger_entry(key: str, path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    entry = load_ledger(path).get("uploads", {}).get(key)
    return entry if isinstance(entry, dict) else None


def record_ledger_entry(
    key: str,
    entry: Dict[str, Any],
    path: Optional[str] = None,
) -> None:
    """Record a successful upload exactly once under its content hash."""
    ledger_path = path or get_config().get_ledger_path()
    with file_lock(ledger_path + ".lock"):
        ledger = load_ledger(ledger_path)
        ledger["uploads"][key] = entry
        ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp_path = ledger_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(ledger, handle, indent=2, ensure_ascii=False)
        os.replace(temp_path, ledger_path)


# ============================================================================
# QUOTA TRACKING
# ============================================================================
class QuotaTracker:
    """Track YouTube API quota using YouTube's Pacific-time reset.

    The general bucket is 10,000 units/day.  ``videos.insert`` costs 1,600
    units from that bucket, while a separate 100-uploads/day cap also applies.
    ``search.list`` (when used) costs 100 units and has its own 100-calls/day
    cap.  All limits reset at midnight Pacific Time and stay configurable.
    """

    def __init__(self, db: Dict[str, Any]):
        self.db = db
        cfg = get_config()
        self.cfg = cfg
        try:
            self.reset_tz = ZoneInfo(cfg.quota.reset_timezone)
        except ZoneInfoNotFoundError:
            log().warning(
                "Unknown quota.reset_timezone '%s'; using UTC",
                cfg.quota.reset_timezone,
            )
            self.reset_tz = timezone.utc
        self.today = datetime.now(self.reset_tz).strftime("%Y-%m-%d")
        self.limit = cfg.quota.daily_limit
        self.upload_limit = cfg.quota.upload_daily_limit
        self.search_limit = cfg.quota.search_daily_limit
        self.alert_threshold = cfg.quota.alert_threshold

        if 'quota_usage' not in self.db:
            self.db['quota_usage'] = {}

        entry = self.db['quota_usage'].setdefault(self.today, {})
        entry.setdefault('used', 0)
        entry.setdefault('operations', [])
        entry.setdefault('uploads', 0)
        entry.setdefault('searches', 0)
        self._entry = entry

    @property
    def used_today(self) -> int:
        return int(self._entry.get('used', 0))

    @property
    def uploads_today(self) -> int:
        return int(self._entry.get('uploads', 0))

    @property
    def searches_today(self) -> int:
        return int(self._entry.get('searches', 0))

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used_today)

    @property
    def percent_used(self) -> float:
        return (self.used_today / self.limit) * 100 if self.limit > 0 else 0

    def add_usage(self, units: int, operation: str, video_id: str = "") -> None:
        """Record quota usage for an operation."""
        self._entry['used'] = self.used_today + units
        if operation == 'video_upload':
            self._entry['uploads'] = self.uploads_today + 1
        elif operation == 'search_list':
            self._entry['searches'] = self.searches_today + 1
        self._entry.setdefault('operations', []).append({
            'timestamp': datetime.now(self.reset_tz).isoformat(),
            'units': units,
            'operation': operation,
            'video_id': video_id
        })
        save_db(self.db)

    def check_and_warn(self, estimated_additional: int = 0) -> Tuple[bool, str]:
        """Check if the general quota bucket is safe for more operations."""
        projected = self.used_today + estimated_additional
        if projected > self.limit:
            return False, f"QUOTA EXCEEDED: {projected}/{self.limit} (would exceed limit)"
        if projected > self.limit * self.alert_threshold:
            return True, f"QUOTA WARNING: {projected}/{self.limit} ({projected/self.limit*100:.0f}% used)"
        return True, f"Quota OK: {projected}/{self.limit} ({projected/self.limit*100:.0f}% used)"

    def can_afford(self, units: int) -> bool:
        return (self.used_today + units) <= self.limit

    def can_upload(self) -> bool:
        return self.uploads_today < self.upload_limit

    def can_search(self) -> bool:
        return self.searches_today < self.search_limit


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
# TIMEZONE HELPERS
# ============================================================================
def get_timezone() -> ZoneInfo:
    """Return the configured scheduling timezone."""
    cfg = get_config()
    try:
        return ZoneInfo(cfg.schedule.timezone)
    except ZoneInfoNotFoundError:
        log().warning(
            "Unknown schedule.timezone '%s'; using UTC",
            cfg.schedule.timezone,
        )
        return timezone.utc


def now_local() -> datetime:
    """Current time in the configured scheduling timezone."""
    return datetime.now(get_timezone())


def ensure_aware(dt: datetime) -> datetime:
    """Attach the configured timezone to a naive datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=get_timezone())
    return dt.astimezone(get_timezone())


def format_iso_tz(dt: datetime) -> str:
    """Format a datetime as RFC3339 with the configured UTC offset."""
    return ensure_aware(dt).isoformat(timespec="seconds")


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
    now = ensure_aware(now)
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
    """Backward-compatible alias for :func:`format_iso_tz`.

    The name is historical; the offset now comes from
    ``schedule.timezone`` instead of a hardcoded +05:30.
    """
    return format_iso_tz(dt)


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
def _pid_is_running(pid: int) -> bool:
    """Return True when a process with ``pid`` currently exists."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if ctypes.windll.kernel32.GetExitCodeProcess(
                    handle, ctypes.byref(exit_code)
                ):
                    return exit_code.value == 259  # STILL_ACTIVE
                return True
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:  # pragma: no cover - POSIX
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_lock(lock_path: Optional[str] = None) -> bool:
    """Atomically acquire a single-instance lock.

    Unlike the previous implementation this fails closed: if the lock cannot
    be created, the caller does not run.  A stale lock whose PID is gone is
    removed automatically.
    """
    cfg = get_config()
    if not cfg.lock_enabled:
        return True

    path = Path(lock_path or cfg.get_lock_path())
    path.parent.mkdir(parents=True, exist_ok=True)

    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            log().debug("Acquired lock %s (PID %s)", path, os.getpid())
            return True
        except FileExistsError:
            owner = 0
            try:
                owner = int(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                owner = 0

            if not cfg.lock_check_pid:
                log().warning(
                    "Lock %s already exists; refusing to start a second instance",
                    path,
                )
                return False

            if owner and _pid_is_running(owner):
                log().warning(
                    "Another autopilot instance (PID %s) is running; refusing to start",
                    owner,
                )
                return False

            log().warning("Removing stale lock %s (PID %s is not running)", path, owner)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                log().error("Could not remove stale lock %s: %s", path, exc)
                return False
        except OSError as exc:
            log().error("Failed to acquire lock %s: %s", path, exc)
            return False

    return False


def release_lock(lock_path: Optional[str] = None) -> None:
    """Release the lock only if this process owns it."""
    cfg = get_config()
    path = Path(lock_path or cfg.get_lock_path())

    try:
        if not path.exists():
            return
        try:
            owner = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            owner = 0
        if owner and owner != os.getpid():
            log().warning(
                "Not releasing lock %s owned by PID %s", path, owner
            )
            return
        path.unlink()
        log().debug("Released lock %s", path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log().warning("Failed to release lock %s: %s", path, exc)


# ============================================================================
# TIMESTAMP HELPERS
# ============================================================================
def get_timestamp() -> int:
    """Get current Unix timestamp."""
    return int(time.time())


def get_date_key() -> str:
    """Get today's date key (YYYY-MM-DD) in the scheduling timezone."""
    return now_local().strftime("%Y-%m-%d")


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