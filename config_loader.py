"""
DON OF VICE CITY — Configuration Loader
=======================================
Loads config.yaml with environment-variable overrides and validation.

Design notes
------------
* ``config.yaml`` is the single source of truth.  Paths are resolved relative
  to the directory containing the config file, not the current working
  directory.  This makes the project safe to launch from Task Scheduler,
  a shortcut, or another folder.
* Every existing config section is loaded.  Sections that are not yet used by
  the pipeline are exposed as dictionaries so they can be consumed by later
  phases without changing this loader again.
* ``load_config(path)`` is available for tests.  The normal application path
  uses the cached ``get_config()`` singleton.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

log = logging.getLogger("config_loader")

# Resolution values accepted by the editor.  Kept intentionally permissive
# because YouTube accepts many aspect ratios; this only catches typos.
_RESOLUTION_RE = re.compile(r"^\d{2,5}x\d{2,5}$")
_PRESETS = {
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
}


@dataclass
class ChannelConfig:
    name: str
    token_file: str
    client_secret_file: str
    channel_id: str = ""
    upload_defaults: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoConfig:
    # Long video
    long_resolution: str = "2560x1440"
    long_fps: int = 60
    long_duration_range: Tuple[int, int] = (150, 180)
    long_crf: int = 18
    long_preset: str = "fast"
    long_audio_bitrate: str = "192k"
    long_audio_volume: float = 0.85
    long_saturation: float = 1.12
    long_contrast: float = 1.05

    # Short video
    short_resolution: str = "1080x1920"
    short_fps: int = 60
    short_duration: int = 26
    short_crf: int = 20
    short_preset: str = "fast"
    short_audio_bitrate: str = "192k"
    short_audio_volume: float = 0.9
    short_trim_start: int = 2

    # Fonts
    font_primary: str = "C:/Windows/Fonts/ariblk.ttf"
    font_fallback: str = "C:/Windows/Fonts/impact.ttf"
    allow_font_fallback: bool = True

    # Watermarks
    long_watermark: Dict[str, Any] = field(default_factory=dict)
    short_watermark: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleConfig:
    timezone: str = "Asia/Kolkata"
    long_video_hour: int = 18
    long_video_minute: int = 0
    long_min_lead_minutes: int = 15
    long_round_minutes: int = 5
    long_video_weekday: Optional[int] = None

    shorts_standard_slots: List[Dict[str, Any]] = field(default_factory=list)
    shorts_min_first_lead: int = 20
    shorts_end_hour: int = 23
    shorts_end_minute: int = 30
    shorts_min_spread_hours: float = 1.5
    shorts_late_interval_hours: int = 2
    shorts_round_minutes: int = 5
    shorts_max_per_day: int = 4


@dataclass
class QuotaConfig:
    """YouTube quota configuration.

    YouTube's current documented quota model uses separate buckets:

    * 100 ``search.list`` calls per day (1 unit each)
    * 100 ``videos.insert`` calls per day (1 unit each)
    * 10,000 units per day for all other endpoints

    All daily quotas reset at midnight Pacific Time.  The values remain
    configurable because Google occasionally changes the limits.
    """

    daily_limit: int = 10000
    upload_daily_limit: int = 100
    search_daily_limit: int = 100
    video_upload_cost: int = 1
    video_update_cost: int = 50
    video_list_cost: int = 1
    search_list_cost: int = 1
    thumbnail_set_cost: int = 50
    alert_threshold: float = 0.8
    reserve_buffer: int = 2000
    reset_timezone: str = "America/Los_Angeles"

    def estimate_daily_usage(self, num_longs: int = 1, num_shorts: int = 4,
                             num_thumbnails: int = 1) -> int:
        """Estimate general quota units for the daily bundle.

        Uploads consume 1600 units each from the 10,000-unit general quota;
        the 100-uploads/day cap is tracked separately.
        """
        return (num_longs * self.video_upload_cost +
                num_shorts * self.video_upload_cost +
                num_thumbnails * self.thumbnail_set_cost)

    def estimate_uploads(self, num_longs: int = 1, num_shorts: int = 4) -> int:
        return num_longs + num_shorts

    def check_quota_safe(self, estimated_usage: int) -> Tuple[bool, str]:
        if estimated_usage > self.daily_limit:
            return False, (f"Estimated usage ({estimated_usage}) exceeds "
                           f"daily limit ({self.daily_limit})")
        if estimated_usage > self.daily_limit * self.alert_threshold:
            return True, (f"WARNING: Estimated usage ({estimated_usage}) exceeds "
                          f"{self.alert_threshold * 100:.0f}% threshold")
        return True, f"OK: Estimated usage {estimated_usage}/{self.daily_limit}"


@dataclass
class Config:
    # Version of the in-memory schema, not the file.  Older files are upgraded
    # in memory with defaults.
    config_version: int = 2

    # Channels
    default_channel: str = "donofvicecity2026"
    channels: Dict[str, ChannelConfig] = field(default_factory=dict)

    # Paths
    base_dir: str = "."
    output_dir: str = "daily_generated"
    assets_audio: str = "assets/audio"
    assets_footage: str = "assets/footage"
    db_file: str = "autopilot_db.json"
    lock_file: str = "autopilot.lock"
    log_file: str = "autopilot.log"
    ledger_file: str = "upload_ledger.json"
    ffmpeg_exe: str = ""
    ffprobe_exe: str = ""

    # Video settings
    video: VideoConfig = field(default_factory=VideoConfig)

    # Schedule
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)

    # Topics
    long_video_pool: List[Dict[str, Any]] = field(default_factory=list)
    shorts_pool: List[Dict[str, Any]] = field(default_factory=list)

    # Audio
    audio_tracks: List[Dict[str, Any]] = field(default_factory=list)
    audio_verified_tracks: List[str] = field(default_factory=list)

    # Quota
    quota: QuotaConfig = field(default_factory=QuotaConfig)

    # Existing sections
    download: Dict[str, Any] = field(default_factory=dict)
    deduplication: Dict[str, Any] = field(default_factory=dict)
    network: Dict[str, Any] = field(default_factory=dict)
    cleanup: Dict[str, Any] = field(default_factory=dict)
    logging: Dict[str, Any] = field(default_factory=dict)

    # Lock
    lock_enabled: bool = True
    lock_check_pid: bool = True

    # Sections that existed in config.yaml but were previously ignored.
    thumbnails: Dict[str, Any] = field(default_factory=dict)
    content_analysis: Dict[str, Any] = field(default_factory=dict)
    smart_scheduling: Dict[str, Any] = field(default_factory=dict)
    retry: Dict[str, Any] = field(default_factory=dict)
    monetization: Dict[str, Any] = field(default_factory=dict)
    deployment: Dict[str, Any] = field(default_factory=dict)
    approval: Dict[str, Any] = field(default_factory=dict)
    ai: Dict[str, Any] = field(default_factory=dict)
    analytics: Dict[str, Any] = field(default_factory=dict)
    source_policy: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def get_output_path(self, *parts: str) -> str:
        return str(Path(self.base_dir) / self.output_dir / Path(*parts))

    def get_assets_audio_path(self, *parts: str) -> str:
        return str(Path(self.base_dir) / self.assets_audio / Path(*parts))

    def get_assets_footage_path(self, *parts: str) -> str:
        return str(Path(self.base_dir) / self.assets_footage / Path(*parts))

    def get_db_path(self) -> str:
        return str(Path(self.base_dir) / self.db_file)

    def get_lock_path(self) -> str:
        return str(Path(self.base_dir) / self.lock_file)

    def get_log_path(self) -> str:
        return str(Path(self.base_dir) / self.log_file)

    def get_ledger_path(self) -> str:
        return str(Path(self.base_dir) / self.ledger_file)

    def get_ffmpeg_exe(self) -> str:
        if self.ffmpeg_exe:
            if os.path.isfile(self.ffmpeg_exe):
                return self.ffmpeg_exe
            log.warning("Configured FFmpeg path does not exist: %s", self.ffmpeg_exe)
        found = shutil.which("ffmpeg")
        if found:
            return found
        raise FileNotFoundError(
            "FFmpeg not found. Install FFmpeg or set paths.ffmpeg_exe in config.yaml"
        )

    def get_ffprobe_exe(self) -> str:
        if self.ffprobe_exe and os.path.isfile(self.ffprobe_exe):
            return self.ffprobe_exe
        if self.ffmpeg_exe:
            candidate = Path(self.ffmpeg_exe).with_name(
                "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            if candidate.is_file():
                return str(candidate)
        found = shutil.which("ffprobe")
        if found:
            return found
        raise FileNotFoundError(
            "FFprobe not found. It normally ships with FFmpeg; set paths.ffprobe_exe "
            "in config.yaml if it is in a non-standard location."
        )


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


class ConfigLoader:
    """Singleton loader for the application configuration."""

    _instance: Optional["ConfigLoader"] = None
    _config: Optional[Config] = None

    def __new__(cls) -> "ConfigLoader":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._config is not None:
            return
        path = self._find_config_path()
        self._config = load_config(path)

    @staticmethod
    def _find_config_path() -> Path:
        candidates = [
            Path(__file__).resolve().parent / "config.yaml",
            Path.cwd() / "config.yaml",
        ]
        env_path = (os.environ.get("YOUTUBE_CONFIG")
                    or os.environ.get("YOUTUBE_AUTOPROJECT_CONFIG"))
        if env_path:
            candidates.insert(0, Path(env_path).expanduser())

        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()

        raise FileNotFoundError(
            "config.yaml not found. Checked: "
            + ", ".join(str(p) for p in candidates)
        )

    @property
    def config(self) -> Config:
        assert self._config is not None
        return self._config

    def get_channel(self, channel_key: Optional[str] = None) -> ChannelConfig:
        key = channel_key or self._config.default_channel  # type: ignore[union-attr]
        if key not in self._config.channels:  # type: ignore[union-attr]
            raise KeyError(
                f"Channel '{key}' not configured. "
                f"Available: {list(self._config.channels)}"  # type: ignore[union-attr]
            )
        return self._config.channels[key]  # type: ignore[union-attr]

    def reload(self) -> None:
        self._config = load_config(self._find_config_path())


def load_config(config_path: str | os.PathLike[str]) -> Config:
    """Load and validate a specific config file.

    This function does not use application-level caching, which makes it safe
    for tests and for validating a proposed config before replacing the live
    one.
    """
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("config.yaml must contain a YAML mapping at the top level")

    raw = _apply_env_overrides(raw)
    project_root = path.parent
    config = _build_config(raw, project_root)
    _validate_config(config)
    return config


def _build_config(raw: Dict[str, Any], project_root: Path) -> Config:
    config = Config()
    config.config_version = int(raw.get("config_version", 1))

    # Channels ---------------------------------------------------------
    channels_raw = _as_dict(raw.get("channels"))
    config.default_channel = str(
        channels_raw.get("default") or "donofvicecity2026"
    )
    for key, channel_raw in _as_dict(channels_raw.get("accounts")).items():
        channel_data = _as_dict(channel_raw)
        config.channels[str(key)] = ChannelConfig(
            name=str(channel_data.get("name", key)),
            token_file=str(channel_data.get("token_file", "token.pickle")),
            client_secret_file=str(
                channel_data.get("client_secret_file", "client_secret.json")
            ),
            channel_id=str(channel_data.get("channel_id", "")),
            upload_defaults=_as_dict(channel_data.get("upload_defaults")),
        )

    # Paths ------------------------------------------------------------
    paths = _as_dict(raw.get("paths"))
    base_raw = Path(str(paths.get("base_dir", ".")))
    config.base_dir = str(
        (base_raw if base_raw.is_absolute() else project_root / base_raw).resolve()
    )
    config.output_dir = str(paths.get("output_dir", "daily_generated"))
    config.assets_audio = str(paths.get("assets_audio", "assets/audio"))
    config.assets_footage = str(paths.get("assets_footage", "assets/footage"))
    config.db_file = str(paths.get("db_file", "autopilot_db.json"))
    config.lock_file = str(paths.get("lock_file", "autopilot.lock"))
    config.log_file = str(paths.get("log_file", "autopilot.log"))
    config.ledger_file = str(paths.get("ledger_file", "upload_ledger.json"))
    config.ffmpeg_exe = str(paths.get("ffmpeg_exe", "") or "")
    config.ffprobe_exe = str(paths.get("ffprobe_exe", "") or "")

    ffmpeg_override = os.environ.get("FFMPEG_PATH") or os.environ.get(
        "YOUTUBE_FFMPEG_PATH"
    )
    if ffmpeg_override:
        config.ffmpeg_exe = ffmpeg_override
    ffprobe_override = os.environ.get("FFPROBE_PATH") or os.environ.get(
        "YOUTUBE_FFPROBE_PATH"
    )
    if ffprobe_override:
        config.ffprobe_exe = ffprobe_override

    # Video ------------------------------------------------------------
    video_raw = _as_dict(raw.get("video"))
    long_raw = _as_dict(video_raw.get("long"))
    short_raw = _as_dict(video_raw.get("short"))
    fonts_raw = _as_dict(video_raw.get("fonts"))
    duration_range = _as_list(
        long_raw.get("duration_range_seconds", [150, 180])
    )
    if len(duration_range) != 2:
        duration_range = [150, 180]
    config.video = VideoConfig(
        long_resolution=str(long_raw.get("resolution", "2560x1440")),
        long_fps=int(long_raw.get("fps", 60)),
        long_duration_range=(int(duration_range[0]), int(duration_range[1])),
        long_crf=int(long_raw.get("crf", 18)),
        long_preset=str(long_raw.get("preset", "fast")),
        long_audio_bitrate=str(long_raw.get("audio_bitrate", "192k")),
        long_audio_volume=float(long_raw.get("audio_volume", 0.85)),
        long_saturation=float(
            _as_dict(long_raw.get("color_grading")).get("saturation", 1.12)
        ),
        long_contrast=float(
            _as_dict(long_raw.get("color_grading")).get("contrast", 1.05)
        ),
        short_resolution=str(short_raw.get("resolution", "1080x1920")),
        short_fps=int(short_raw.get("fps", 60)),
        short_duration=int(short_raw.get("duration_seconds", 26)),
        short_crf=int(short_raw.get("crf", 20)),
        short_preset=str(short_raw.get("preset", "fast")),
        short_audio_bitrate=str(short_raw.get("audio_bitrate", "192k")),
        short_audio_volume=float(short_raw.get("audio_volume", 0.9)),
        short_trim_start=int(short_raw.get("trim_start_seconds", 2)),
        font_primary=str(
            fonts_raw.get("primary", "C:/Windows/Fonts/ariblk.ttf")
        ),
        font_fallback=str(
            fonts_raw.get("fallback", "C:/Windows/Fonts/impact.ttf")
        ),
        allow_font_fallback=bool(
            fonts_raw.get("allow_default_fallback", True)
        ),
        long_watermark=_as_dict(long_raw.get("watermark")),
        short_watermark=_as_dict(short_raw.get("watermark")),
    )

    # Schedule ---------------------------------------------------------
    sched_raw = _as_dict(raw.get("schedule"))
    long_sched = _as_dict(sched_raw.get("long_video"))
    short_sched = _as_dict(sched_raw.get("shorts"))
    long_weekday_raw = long_sched.get("weekday")
    long_video_weekday = (
        None
        if long_weekday_raw in (None, "", "null")
        else int(long_weekday_raw)
    )

    config.schedule = ScheduleConfig(
        timezone=str(sched_raw.get("timezone", "Asia/Kolkata")),
        long_video_hour=int(long_sched.get("target_hour", 18)),
        long_video_minute=int(long_sched.get("target_minute", 0)),
        long_min_lead_minutes=int(long_sched.get("min_lead_minutes", 15)),
        long_round_minutes=int(long_sched.get("round_to_minutes", 5)),
        long_video_weekday=long_video_weekday,
        shorts_standard_slots=_as_list(short_sched.get("standard_slots")),
        shorts_min_first_lead=int(
            short_sched.get("min_first_lead_minutes", 20)
        ),
        shorts_end_hour=int(short_sched.get("end_of_day_hour", 23)),
        shorts_end_minute=int(short_sched.get("end_of_day_minute", 30)),
        shorts_min_spread_hours=float(
            short_sched.get("min_spread_hours", 1.5)
        ),
        shorts_late_interval_hours=int(
            short_sched.get("late_night_interval_hours", 2)
        ),
        shorts_round_minutes=int(
            short_sched.get("round_schedule_to_minutes", 5)
        ),
        shorts_max_per_day=int(short_sched.get("max_per_day", 4)),
    )

    # Topics / audio ---------------------------------------------------
    topics_raw = _as_dict(raw.get("topics"))
    config.long_video_pool = _as_list(topics_raw.get("long_video_pool"))
    config.shorts_pool = _as_list(topics_raw.get("shorts_pool"))
    audio_raw = _as_dict(raw.get("audio"))
    config.audio_tracks = _as_list(audio_raw.get("background_tracks"))
    config.audio_verified_tracks = [
        str(name)
        for name in _as_list(audio_raw.get("verified_tracks"))
        if name
    ]

    # Quota ------------------------------------------------------------
    quota_raw = _as_dict(raw.get("quota"))
    costs = _as_dict(quota_raw.get("costs"))
    config.quota = QuotaConfig(
        daily_limit=int(quota_raw.get("daily_limit", 10000)),
        upload_daily_limit=int(quota_raw.get("upload_daily_limit", 100)),
        search_daily_limit=int(quota_raw.get("search_daily_limit", 100)),
        video_upload_cost=int(costs.get("video_upload", 1)),
        video_update_cost=int(costs.get("video_update", 50)),
        video_list_cost=int(costs.get("video_list", 1)),
        search_list_cost=int(costs.get("search_list", 1)),
        thumbnail_set_cost=int(costs.get("thumbnail_set", 50)),
        alert_threshold=float(
            quota_raw.get("alert_threshold_percent", 80)
        ) / 100.0,
        reserve_buffer=int(quota_raw.get("reserve_buffer", 2000)),
        reset_timezone=str(
            quota_raw.get("reset_timezone", "America/Los_Angeles")
        ),
    )

    # Previously ignored sections -------------------------------------
    config.download = _as_dict(raw.get("download"))
    config.deduplication = _as_dict(raw.get("deduplication"))
    config.network = _as_dict(raw.get("network"))
    config.cleanup = _as_dict(raw.get("cleanup"))
    config.logging = _as_dict(raw.get("logging"))
    config.thumbnails = _as_dict(raw.get("thumbnails"))
    config.content_analysis = _as_dict(raw.get("content_analysis"))
    config.smart_scheduling = _as_dict(raw.get("smart_scheduling"))
    config.retry = _as_dict(raw.get("retry"))
    config.monetization = _as_dict(raw.get("monetization"))
    config.deployment = _as_dict(raw.get("deployment"))
    config.approval = _as_dict(raw.get("approval"))
    config.ai = _as_dict(raw.get("ai"))
    config.analytics = _as_dict(raw.get("analytics"))
    config.source_policy = _as_dict(raw.get("source_policy"))

    # Safe defaults for newly loaded sections.  They preserve the previous
    # zero-touch behaviour unless the user explicitly opts into manual review.
    config.approval.setdefault("required", False)
    config.approval.setdefault("auto_approve", True)
    config.ai.setdefault("provider", "none")
    config.ai.setdefault("enabled", False)
    config.analytics.setdefault("enabled", False)
    config.source_policy.setdefault("enforce_license_manifest", False)
    config.source_policy.setdefault("allow_external_downloads", True)

    # Lock -------------------------------------------------------------
    lock_raw = _as_dict(raw.get("lock"))
    config.lock_enabled = bool(lock_raw.get("enabled", True))
    config.lock_check_pid = bool(lock_raw.get("check_pid", True))

    return config


def _apply_env_overrides(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment-variable overrides without mutating the caller."""
    raw = dict(raw)

    if os.environ.get("YOUTUBE_CHANNEL"):
        channels = dict(_as_dict(raw.get("channels")))
        channels["default"] = os.environ["YOUTUBE_CHANNEL"]
        raw["channels"] = channels

    if os.environ.get("LOG_LEVEL"):
        logging_raw = dict(_as_dict(raw.get("logging")))
        logging_raw["level"] = os.environ["LOG_LEVEL"]
        raw["logging"] = logging_raw

    if os.environ.get("QUOTA_ALERT_THRESHOLD"):
        quota = dict(_as_dict(raw.get("quota")))
        try:
            quota["alert_threshold_percent"] = int(
                os.environ["QUOTA_ALERT_THRESHOLD"]
            )
        except ValueError:
            log.warning("Ignoring invalid QUOTA_ALERT_THRESHOLD")
        raw["quota"] = quota

    return raw


def _validate_config(config: Config) -> None:
    errors: List[str] = []
    warnings: List[str] = []

    if not config.channels:
        errors.append("No channels configured under channels.accounts")
    if config.default_channel not in config.channels:
        errors.append(
            f"Default channel '{config.default_channel}' not found in "
            f"channels.accounts"
        )

    for key, channel in config.channels.items():
        if not channel.token_file:
            errors.append(f"Channel '{key}' has an empty token_file")
        if not channel.client_secret_file:
            errors.append(f"Channel '{key}' has an empty client_secret_file")

    # Video validation
    for label, resolution in (
        ("video.long.resolution", config.video.long_resolution),
        ("video.short.resolution", config.video.short_resolution),
    ):
        if not _RESOLUTION_RE.match(resolution):
            errors.append(
                f"{label} must look like WIDTHxHEIGHT (got '{resolution}')"
            )
    for label, fps in (
        ("video.long.fps", config.video.long_fps),
        ("video.short.fps", config.video.short_fps),
    ):
        if not 1 <= fps <= 240:
            errors.append(f"{label} must be between 1 and 240")
    if not 1 <= config.video.short_duration <= 180:
        errors.append("video.short.duration_seconds must be between 1 and 180")
    for label, crf in (
        ("video.long.crf", config.video.long_crf),
        ("video.short.crf", config.video.short_crf),
    ):
        if not 0 <= crf <= 51:
            errors.append(f"{label} must be between 0 and 51")
    for label, preset in (
        ("video.long.preset", config.video.long_preset),
        ("video.short.preset", config.video.short_preset),
    ):
        if preset not in _PRESETS:
            errors.append(
                f"{label} must be one of: {', '.join(sorted(_PRESETS))}"
            )

    # Schedule validation
    seen_slots: set[int] = set()
    for slot in config.schedule.shorts_standard_slots:
        if not isinstance(slot, dict):
            errors.append("Each shorts standard slot must be a mapping")
            continue
        try:
            slot_id = int(slot["slot_id"])
            hour = int(slot["hour"])
            minute = int(slot["minute"])
        except (KeyError, TypeError, ValueError):
            errors.append("Each shorts slot needs integer slot_id, hour, minute")
            continue
        if slot_id in seen_slots:
            errors.append(f"Duplicate shorts slot_id: {slot_id}")
        seen_slots.add(slot_id)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            errors.append(
                f"Shorts slot {slot_id} has invalid time {hour}:{minute:02d}"
            )
    if not config.schedule.shorts_standard_slots:
        warnings.append("No shorts standard slots configured")

    if not 0 <= config.schedule.long_video_hour <= 23:
        errors.append("schedule.long_video.target_hour must be 0-23")
    if not 0 <= config.schedule.long_video_minute <= 59:
        errors.append("schedule.long_video.target_minute must be 0-59")
    if (
        config.schedule.long_video_weekday is not None
        and not 0 <= config.schedule.long_video_weekday <= 6
    ):
        errors.append(
            "schedule.long_video.weekday must be 0-6 (0 = Monday) or empty"
        )
    if config.schedule.shorts_max_per_day < 1:
        errors.append("schedule.shorts.max_per_day must be at least 1")

    # Audio and topic warnings (not fatal: later phases may use other sources)
    if not config.audio_tracks:
        warnings.append(
            "No background audio tracks configured; renders will fail if a "
            "track is required"
        )
    else:
        for track in config.audio_tracks:
            filename = _as_dict(track).get("filename")
            if not filename:
                warnings.append("An audio track is missing its filename")
                continue
            if not Path(config.get_assets_audio_path(str(filename))).is_file():
                warnings.append(
                    f"Audio track not found: {config.get_assets_audio_path(str(filename))}"
                )
    if not config.long_video_pool:
        warnings.append("topics.long_video_pool is empty")
    if not config.shorts_pool:
        warnings.append("topics.shorts_pool is empty")

    # Quota validation
    if config.quota.daily_limit <= 0:
        errors.append("quota.daily_limit must be greater than zero")
    if config.quota.upload_daily_limit <= 0:
        errors.append("quota.upload_daily_limit must be greater than zero")
    if not 0.0 < config.quota.alert_threshold <= 1.0:
        errors.append("quota.alert_threshold_percent must be between 1 and 100")

    # Fonts are warnings because FFmpeg can use its built-in font.
    for font in (config.video.font_primary, config.video.font_fallback):
        if font and not Path(font).is_file():
            if config.video.allow_font_fallback:
                warnings.append(f"Font not found (FFmpeg fallback allowed): {font}")
            else:
                errors.append(f"Font not found: {font}")

    # FFmpeg is checked lazily by the renderer, but warning early is useful.
    if config.ffmpeg_exe and not Path(config.ffmpeg_exe).is_file():
        warnings.append(
            f"Configured FFmpeg path does not exist: {config.ffmpeg_exe}"
        )

    if config.base_dir and not Path(config.base_dir).exists():
        errors.append(f"base_dir does not exist: {config.base_dir}")

    for message in warnings:
        log.warning(message)

    if errors:
        raise ValueError(
            "Config validation failed:\n"
            + "\n".join(f"  - {error}" for error in errors)
        )


def get_config() -> Config:
    """Get the global application config."""
    return ConfigLoader().config


def get_channel_config(channel_key: Optional[str] = None) -> ChannelConfig:
    return ConfigLoader().get_channel(channel_key)


def get_db_path() -> str:
    return get_config().get_db_path()


def get_log_path() -> str:
    return get_config().get_log_path()


def get_paths() -> Dict[str, Any]:
    """Backward-compatible paths dictionary."""
    cfg = get_config()
    return {
        "base_dir": cfg.base_dir,
        "output_dir": cfg.output_dir,
        "assets_audio": cfg.assets_audio,
        "assets_footage": cfg.assets_footage,
        "db_file": cfg.db_file,
        "lock_file": cfg.lock_file,
        "log_file": cfg.log_file,
        "ledger_file": cfg.ledger_file,
    }


if __name__ == "__main__":
    try:
        cfg = get_config()
        print("OK: config loaded")
        print(f"Config version: {cfg.config_version}")
        print(f"Default channel: {cfg.default_channel}")
        print(f"Channels: {list(cfg.channels)}")
        print(f"Base directory: {cfg.base_dir}")
        print(f"Long topics: {len(cfg.long_video_pool)}")
        print(f"Shorts topics: {len(cfg.shorts_pool)}")
        print(f"Audio tracks: {len(cfg.audio_tracks)}")
        print(f"FFmpeg: {cfg.ffmpeg_exe or '(auto-detect)'}")
        print(f"Quota: {cfg.quota.daily_limit} units + "
              f"{cfg.quota.upload_daily_limit} uploads/day")
        safe, message = cfg.quota.check_quota_safe(
            cfg.quota.estimate_daily_usage()
        )
        print(f"Quota estimate: {message}")
    except Exception as exc:  # pragma: no cover - CLI convenience
        print(f"FAILED: {exc}")
        sys.exit(1)
