"""
DON OF VICE CITY — Configuration Loader
Loads config.yaml with environment variable overrides and validation.
Supports multi-channel configuration.
"""
import os
import sys
import yaml
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field

# Logger for config loading
log = logging.getLogger("config_loader")


@dataclass
class ChannelConfig:
    name: str
    token_file: str
    client_secret_file: str
    channel_id: str = ""
    upload_defaults: Dict = field(default_factory=dict)


@dataclass
class VideoConfig:
    # Long video
    long_resolution: str = "2560x1440"
    long_fps: int = 60
    long_duration_range: tuple = (150, 180)
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
    allow_font_fallback: bool = True  # Allow FFmpeg default font if custom fonts missing

    # Watermarks
    long_watermark: Dict = field(default_factory=dict)
    short_watermark: Dict = field(default_factory=dict)


@dataclass
class ScheduleConfig:
    timezone: str = "Asia/Kolkata"
    long_video_hour: int = 18
    long_video_minute: int = 0
    long_min_lead_minutes: int = 15
    long_round_minutes: int = 5

    shorts_standard_slots: List[Dict] = field(default_factory=list)
    shorts_min_first_lead: int = 20
    shorts_end_hour: int = 23
    shorts_end_minute: int = 30
    shorts_min_spread_hours: float = 1.5
    shorts_late_interval_hours: int = 2
    shorts_round_minutes: int = 5


@dataclass
class QuotaConfig:
    daily_limit: int = 10000
    video_upload_cost: int = 1600
    video_update_cost: int = 50
    video_list_cost: int = 1
    search_list_cost: int = 100
    thumbnail_set_cost: int = 50
    alert_threshold: float = 0.8
    reserve_buffer: int = 2000

    def estimate_daily_usage(self, num_longs: int = 1, num_shorts: int = 4, num_thumbnails: int = 1) -> int:
        return (num_longs * self.video_upload_cost +
                num_shorts * self.video_upload_cost +
                num_thumbnails * self.thumbnail_set_cost)

    def check_quota_safe(self, estimated_usage: int) -> tuple:
        if estimated_usage > self.daily_limit:
            return False, f"Estimated usage ({estimated_usage}) exceeds daily limit ({self.daily_limit})"
        if estimated_usage > self.daily_limit * self.alert_threshold:
            return True, f"WARNING: Estimated usage ({estimated_usage}) exceeds {self.alert_threshold*100:.0f}% threshold"
        return True, f"OK: Estimated usage {estimated_usage}/{self.daily_limit}"


@dataclass
class Config:
    # Channels
    default_channel: str = "donofvicecity2026"
    channels: Dict[str, ChannelConfig] = field(default_factory=dict)

    # Paths
    base_dir: str = "."
    output_dir: str = "daily_generated"
    assets_audio: str = "assets/audio"
    db_file: str = "autopilot_db.json"
    lock_file: str = "autopilot.lock"
    log_file: str = "autopilot.log"
    ffmpeg_exe: str = ""

    # Video settings
    video: VideoConfig = field(default_factory=VideoConfig)

    # Schedule
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)

    # Topics
    long_video_pool: List[Dict] = field(default_factory=list)
    shorts_pool: List[Dict] = field(default_factory=list)

    # Audio
    audio_tracks: List[Dict] = field(default_factory=list)

    # Quota
    quota: QuotaConfig = field(default_factory=QuotaConfig)

    # Download
    download: Dict = field(default_factory=dict)

    # Deduplication
    deduplication: Dict = field(default_factory=dict)

    # Network
    network: Dict = field(default_factory=dict)

    # Cleanup
    cleanup: Dict = field(default_factory=dict)

    # Lock
    lock_enabled: bool = True
    lock_check_pid: bool = True

    # Logging
    logging: Dict = field(default_factory=dict)

    # Helper methods
    def get_output_path(self, *parts) -> str:
        return str(Path(self.base_dir) / self.output_dir / Path(*parts))

    def get_assets_audio_path(self, *parts) -> str:
        return str(Path(self.base_dir) / self.assets_audio / Path(*parts))

    def get_db_path(self) -> str:
        return str(Path(self.base_dir) / self.db_file)

    def get_lock_path(self) -> str:
        return str(Path(self.base_dir) / self.lock_file)

    def get_log_path(self) -> str:
        return str(Path(self.base_dir) / self.log_file)

    def get_ffmpeg_exe(self) -> str:
        if self.ffmpeg_exe and os.path.exists(self.ffmpeg_exe):
            return self.ffmpeg_exe
        found = shutil.which('ffmpeg')
        if found:
            return found
        raise FileNotFoundError("FFmpeg not found. Install FFmpeg or set FFMPEG_PATH in config.yaml")


class ConfigLoader:
    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is not None:
            return
        self._config = self._load_config()

    def _load_config(self) -> Config:
        # Find config.yaml
        config_paths = [
            Path(__file__).parent / "config.yaml",
            Path.cwd() / "config.yaml",
            Path(os.environ.get("YOUTUBE_AUTOPROJECT_CONFIG", "")) if os.environ.get("YOUTUBE_AUTOPROJECT_CONFIG") else None,
        ]

        config_path = None
        for p in config_paths:
            if p and p.exists():
                config_path = p
                break

        if not config_path:
            raise FileNotFoundError(
                "config.yaml not found. Checked: " + ", ".join(str(p) for p in config_paths if p)
            )

        with open(config_path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)

        # Apply environment variable overrides
        raw = self._apply_env_overrides(raw)

        # Build Config object
        config = Config()

        # Channels
        config.default_channel = raw.get('channels', {}).get('default', 'donofvicecity2026')
        for key, ch_data in raw.get('channels', {}).get('accounts', {}).items():
            config.channels[key] = ChannelConfig(
                name=ch_data.get('name', key),
                token_file=ch_data.get('token_file', 'token.pickle'),
                client_secret_file=ch_data.get('client_secret_file', 'client_secret.json'),
                channel_id=ch_data.get('channel_id', ''),
                upload_defaults=ch_data.get('upload_defaults', {})
            )

        # Paths
        paths = raw.get('paths', {})
        config.base_dir = paths.get('base_dir', '.')
        config.output_dir = paths.get('output_dir', 'daily_generated')
        config.assets_audio = paths.get('assets_audio', 'assets/audio')
        config.db_file = paths.get('db_file', 'autopilot_db.json')
        config.lock_file = paths.get('lock_file', 'autopilot.lock')
        config.log_file = paths.get('log_file', 'autopilot.log')
        config.ffmpeg_exe = paths.get('ffmpeg_exe', '')

        # Video settings
        video_raw = raw.get('video', {})
        config.video = VideoConfig(
            long_resolution=video_raw.get('long', {}).get('resolution', '2560x1440'),
            long_fps=video_raw.get('long', {}).get('fps', 60),
            long_duration_range=tuple(video_raw.get('long', {}).get('duration_range_seconds', [150, 180])),
            long_crf=video_raw.get('long', {}).get('crf', 18),
            long_preset=video_raw.get('long', {}).get('preset', 'fast'),
            long_audio_bitrate=video_raw.get('long', {}).get('audio_bitrate', '192k'),
            long_audio_volume=video_raw.get('long', {}).get('audio_volume', 0.85),
            long_saturation=video_raw.get('long', {}).get('color_grading', {}).get('saturation', 1.12),
            long_contrast=video_raw.get('long', {}).get('color_grading', {}).get('contrast', 1.05),
            short_resolution=video_raw.get('short', {}).get('resolution', '1080x1920'),
            short_fps=video_raw.get('short', {}).get('fps', 60),
            short_duration=video_raw.get('short', {}).get('duration_seconds', 26),
            short_crf=video_raw.get('short', {}).get('crf', 20),
            short_preset=video_raw.get('short', {}).get('preset', 'fast'),
            short_audio_bitrate=video_raw.get('short', {}).get('audio_bitrate', '192k'),
            short_audio_volume=video_raw.get('short', {}).get('audio_volume', 0.9),
            short_trim_start=video_raw.get('short', {}).get('trim_start_seconds', 2),
            font_primary=video_raw.get('fonts', {}).get('primary', 'C:/Windows/Fonts/ariblk.ttf'),
            font_fallback=video_raw.get('fonts', {}).get('fallback', 'C:/Windows/Fonts/impact.ttf'),
            allow_font_fallback=video_raw.get('fonts', {}).get('allow_default_fallback', True),
            long_watermark=video_raw.get('long', {}).get('watermark', {}),
            short_watermark=video_raw.get('short', {}).get('watermark', {}),
        )

        # Schedule
        sched_raw = raw.get('schedule', {})
        config.schedule = ScheduleConfig(
            timezone=sched_raw.get('timezone', 'Asia/Kolkata'),
            long_video_hour=sched_raw.get('long_video', {}).get('target_hour', 18),
            long_video_minute=sched_raw.get('long_video', {}).get('target_minute', 0),
            long_min_lead_minutes=sched_raw.get('long_video', {}).get('min_lead_minutes', 15),
            long_round_minutes=sched_raw.get('long_video', {}).get('round_to_minutes', 5),
            shorts_standard_slots=sched_raw.get('shorts', {}).get('standard_slots', []),
            shorts_min_first_lead=sched_raw.get('shorts', {}).get('min_first_lead_minutes', 20),
            shorts_end_hour=sched_raw.get('shorts', {}).get('end_of_day_hour', 23),
            shorts_end_minute=sched_raw.get('shorts', {}).get('end_of_day_minute', 30),
            shorts_min_spread_hours=sched_raw.get('shorts', {}).get('min_spread_hours', 1.5),
            shorts_late_interval_hours=sched_raw.get('shorts', {}).get('late_night_interval_hours', 2),
            shorts_round_minutes=sched_raw.get('shorts', {}).get('round_schedule_to_minutes', 5),
        )

        # Topics
        config.long_video_pool = raw.get('topics', {}).get('long_video_pool', [])
        config.shorts_pool = raw.get('topics', {}).get('shorts_pool', [])

        # Audio
        config.audio_tracks = raw.get('audio', {}).get('background_tracks', [])

        # Quota
        quota_raw = raw.get('quota', {})
        config.quota = QuotaConfig(
            daily_limit=quota_raw.get('daily_limit', 10000),
            video_upload_cost=quota_raw.get('costs', {}).get('video_upload', 1600),
            video_update_cost=quota_raw.get('costs', {}).get('video_update', 50),
            video_list_cost=quota_raw.get('costs', {}).get('video_list', 1),
            search_list_cost=quota_raw.get('costs', {}).get('search_list', 100),
            thumbnail_set_cost=quota_raw.get('costs', {}).get('thumbnail_set', 50),
            alert_threshold=quota_raw.get('alert_threshold_percent', 80) / 100,
            reserve_buffer=quota_raw.get('reserve_buffer', 2000),
        )

        # Download
        config.download = raw.get('download', {})

        # Deduplication
        config.deduplication = raw.get('deduplication', {})

        # Network
        config.network = raw.get('network', {})

        # Cleanup
        config.cleanup = raw.get('cleanup', {})

        # Lock
        config.lock_enabled = raw.get('lock', {}).get('enabled', True)
        config.lock_check_pid = raw.get('lock', {}).get('check_pid', True)

        # Logging
        config.logging = raw.get('logging', {})

        # Validate
        self._validate_config(config)

        return config

    def _apply_env_overrides(self, raw: Dict) -> Dict:
        """Apply environment variable overrides to config."""
        if os.environ.get('YOUTUBE_CHANNEL'):
            if 'channels' not in raw:
                raw['channels'] = {}
            raw['channels']['default'] = os.environ['YOUTUBE_CHANNEL']

        if os.environ.get('FFMPEG_PATH'):
            if 'paths' not in raw:
                raw['paths'] = {}
            raw['paths']['ffmpeg_exe'] = os.environ['FFMPEG_PATH']

        if os.environ.get('LOG_LEVEL'):
            if 'logging' not in raw:
                raw['logging'] = {}
            raw['logging']['level'] = os.environ['LOG_LEVEL']

        if os.environ.get('QUOTA_ALERT_THRESHOLD'):
            if 'quota' not in raw:
                raw['quota'] = {}
            if 'alert_threshold_percent' not in raw['quota']:
                raw['quota']['alert_threshold_percent'] = 80
            raw['quota']['alert_threshold_percent'] = int(os.environ['QUOTA_ALERT_THRESHOLD'])

        return raw

    def _validate_config(self, config: Config):
        """Validate critical config values."""
        errors = []

        # Check default channel exists
        if config.default_channel not in config.channels:
            errors.append(f"Default channel '{config.default_channel}' not found in channels config")

        # Check font files (warning only, FFmpeg will use default if not found)
        for font_path in [config.video.font_primary, config.video.font_fallback]:
            if not os.path.exists(font_path):
                if config.video.allow_font_fallback:
                    log.warning(f"Font not found (will use FFmpeg default): {font_path}")
                else:
                    errors.append(f"Font not found: {font_path}")

        # Check at least one audio track
        if not config.audio_tracks:
            errors.append("No background audio tracks configured")

        # Check quota estimate
        est_usage = config.quota.estimate_daily_usage()
        safe, msg = config.quota.check_quota_safe(est_usage)
        if not safe:
            errors.append(f"Quota check failed: {msg}")

        if errors:
            raise ValueError("Config validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    @property
    def config(self) -> Config:
        return self._config

    def get_channel(self, channel_key: Optional[str] = None) -> ChannelConfig:
        """Get channel config by key, or default channel."""
        key = channel_key or self._config.default_channel
        if key not in self._config.channels:
            raise KeyError(f"Channel '{key}' not configured. Available: {list(self._config.channels.keys())}")
        return self._config.channels[key]

    def reload(self):
        """Force reload config from disk."""
        self._config = self._load_config()


# Singleton instance getter
def get_config() -> Config:
    """Get the global config instance."""
    return ConfigLoader().config


def get_channel_config(channel_key: Optional[str] = None) -> ChannelConfig:
    """Get channel configuration."""
    return ConfigLoader().get_channel(channel_key)


def get_db_path() -> str:
    """Get path to autopilot_db.json."""
    return str(Path(get_config().base_dir) / get_config().db_file)


def get_log_path() -> str:
    """Get path to autopilot.log."""
    return str(Path(get_config().base_dir) / get_config().log_file)


# Convenience functions for backward compatibility
def get_paths():
    """Get paths dict for backward compatibility."""
    cfg = get_config()
    return {
        'base_dir': cfg.base_dir,
        'output_dir': cfg.output_dir,
        'assets_audio': cfg.assets_audio,
        'db_file': cfg.db_file,
        'lock_file': cfg.lock_file,
        'log_file': cfg.log_file,
    }


if __name__ == '__main__':
    try:
        cfg = get_config()
        print("✅ Config loaded successfully!")
        print(f"Default channel: {cfg.default_channel}")
        print(f"Channels: {list(cfg.channels.keys())}")
        print(f"Long video pool: {len(cfg.long_video_pool)} topics")
        print(f"Shorts pool: {len(cfg.shorts_pool)} topics")
        print(f"Audio tracks: {len(cfg.audio_tracks)}")
        print(f"FFmpeg: {cfg.ffmpeg_exe}")
        print(f"Estimated daily quota: {cfg.quota.estimate_daily_usage()}")
        safe, msg = cfg.quota.check_quota_safe(cfg.quota.estimate_daily_usage())
        print(f"Quota check: {msg}")
    except Exception as e:
        print(f"❌ Config load failed: {e}")
        sys.exit(1)