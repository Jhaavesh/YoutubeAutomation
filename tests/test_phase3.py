"""Phase 3 regression tests for the stabilized pipeline."""
from __future__ import annotations

import array
import logging
import os
import subprocess
import tempfile
import unittest
import wave
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from config_loader import ChannelConfig, load_config
from utils import (
    QuotaTracker,
    acquire_lock,
    compute_schedule_times,
    find_ledger_entry,
    format_iso_tz,
    get_drawtext_font,
    get_ffmpeg_exe,
    load_db,
    load_ledger,
    probe_video,
    record_ledger_entry,
    release_lock,
    resolution_to_filter_size,
    sanitize_drawtext,
    save_db,
    validate_video_file,
)


class ConfigTests(unittest.TestCase):
    def test_example_config_loads(self) -> None:
        cfg = load_config("config.example.yaml")
        self.assertEqual(cfg.config_version, 2)
        self.assertIn(cfg.default_channel, cfg.channels)
        self.assertTrue(Path(cfg.base_dir).is_dir())
        self.assertTrue(cfg.schedule.shorts_standard_slots)
        self.assertFalse(cfg.approval["required"])
        self.assertTrue(cfg.approval["auto_approve"])
        self.assertEqual(cfg.quota.video_upload_cost, 1600)
        self.assertEqual(cfg.quota.estimate_daily_usage(), 5 * 1600 + 50)

    def test_timezone_format(self) -> None:
        value = format_iso_tz(datetime(2026, 11, 24, 18, 0))
        self.assertTrue(value.startswith("2026-11-24T18:00:00+05:30"), value)


class ScheduleTests(unittest.TestCase):
    def test_standard_slot_is_used_when_lead_time_allows(self) -> None:
        now = datetime(2026, 11, 24, 17, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        slots = [{"slot_id": 1, "name": "Evening"}]
        times = compute_schedule_times(
            slots,
            now,
            min_first_lead_minutes=20,
            standard_slots=[{"slot_id": 1, "hour": 18, "minute": 0}],
        )
        self.assertEqual(times[0].hour, 18)
        self.assertIsNotNone(times[0].tzinfo)

    def test_past_standard_slot_falls_back_to_lead_time(self) -> None:
        now = datetime(2026, 11, 24, 18, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        slots = [{"slot_id": 1, "name": "Evening"}]
        times = compute_schedule_times(
            slots,
            now,
            min_first_lead_minutes=20,
            standard_slots=[{"slot_id": 1, "hour": 18, "minute": 0}],
        )
        self.assertGreater(times[0], now)
        self.assertIsNotNone(times[0].tzinfo)


class LockTests(unittest.TestCase):
    def test_lock_is_exclusive_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = os.path.join(temp_dir, "test.lock")
            self.assertTrue(acquire_lock(lock_path))
            self.assertFalse(acquire_lock(lock_path))
            release_lock(lock_path)
            self.assertFalse(os.path.exists(lock_path))

    def test_stale_lock_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = os.path.join(temp_dir, "stale.lock")
            Path(lock_path).write_text("999999", encoding="utf-8")
            self.assertTrue(acquire_lock(lock_path))
            self.assertEqual(
                Path(lock_path).read_text(encoding="utf-8").strip(),
                str(os.getpid()),
            )
            release_lock(lock_path)


class LedgerTests(unittest.TestCase):
    def test_ledger_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = os.path.join(temp_dir, "ledger.json")
            record_ledger_entry(
                "channel:hash",
                {"video_id": "abc123", "title": "Test"},
                ledger_path,
            )
            entry = find_ledger_entry("channel:hash", ledger_path)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["video_id"], "abc123")
            self.assertEqual(len(load_ledger(ledger_path)["uploads"]), 1)


class QuotaTests(unittest.TestCase):
    def test_upload_bucket_increments(self) -> None:
        db = {"quota_usage": {}}
        with patch("utils.save_db"):
            tracker = QuotaTracker(db)
            self.assertEqual(tracker.uploads_today, 0)
            tracker.add_usage(1, "video_upload", "abc")
            self.assertEqual(tracker.uploads_today, 1)
            self.assertEqual(tracker.used_today, 1)

    def test_quota_usage_persists_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "db.json")
            db = load_db(db_path)
            tracker = QuotaTracker(db, db_path=db_path)
            tracker.add_usage(1600, "video_upload", "vid123")

            reloaded = load_db(db_path)
            entry = reloaded["quota_usage"][tracker.today]
            self.assertEqual(entry["used"], 1600)
            self.assertEqual(entry["uploads"], 1)
            self.assertEqual(entry["operations"][0]["video_id"], "vid123")

    def test_save_db_merges_existing_quota(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "db.json")
            db = load_db(db_path)
            tracker = QuotaTracker(db, db_path=db_path)
            tracker.add_usage(1600, "video_upload", "vid123")

            stale = load_db(db_path)
            stale["quota_usage"] = {}
            stale["used_source_ids"] = ["source-1"]
            save_db(stale, db_path, lock=False)

            entry = load_db(db_path)["quota_usage"][tracker.today]
            self.assertEqual(entry["used"], 1600)
            self.assertEqual(entry["uploads"], 1)
            self.assertEqual(entry["operations"][0]["video_id"], "vid123")

    def test_save_db_refuses_to_wipe_populated_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "db.json")
            db = load_db(db_path)
            db["used_source_ids"] = ["source-1"]
            save_db(db, db_path, lock=False)

            empty = load_db(db_path)
            empty["used_source_ids"] = []
            with self.assertRaises(RuntimeError):
                save_db(empty, db_path, lock=False)


class ShortDedupeTests(unittest.TestCase):
    def test_used_topic_is_filtered(self) -> None:
        from auto_pilot_bot import select_available_short_topics

        pool = [{"title": "Topic A"}, {"title": "Topic B"}]
        db = {"used_short_topics": ["topic a"]}
        self.assertEqual(
            [t["title"] for t in select_available_short_topics(pool, db)],
            ["Topic B"],
        )

    def test_history_seeds_used_topics(self) -> None:
        from auto_pilot_bot import select_available_short_topics

        pool = [{"title": "Topic A"}, {"title": "Topic B"}]
        db = {"used_short_topics": [], "uploaded_videos": [{"title": "Topic A"}]}
        self.assertEqual(
            [t["title"] for t in select_available_short_topics(pool, db)],
            ["Topic B"],
        )

    def test_all_topics_used_returns_empty(self) -> None:
        from auto_pilot_bot import select_available_short_topics

        pool = [{"title": "Topic A"}, {"title": "Topic B"}]
        db = {"used_short_topics": ["Topic A", "Topic B"]}
        self.assertEqual(select_available_short_topics(pool, db), [])


class AudioSafetyTests(unittest.TestCase):
    def test_unverified_track_is_never_selected(self) -> None:
        from types import SimpleNamespace

        import utils

        with tempfile.TemporaryDirectory() as temp_dir:
            verified = os.path.join(temp_dir, "original_phonk_9.mp3")
            unverified = os.path.join(temp_dir, "phonk_1.mp3")
            Path(verified).write_bytes(b"verified-audio")
            Path(unverified).write_bytes(b"unverified-audio")

            fake_cfg = SimpleNamespace(
                audio_tracks=[
                    {"filename": "phonk_1.mp3", "license": "unknown"},
                    {
                        "filename": "original_phonk_9.mp3",
                        "license": "original",
                    },
                ],
                audio_verified_tracks=[],
                get_assets_audio_path=lambda *parts: os.path.join(
                    temp_dir, *parts
                ),
            )
            with patch.object(
                utils, "get_config", return_value=fake_cfg
            ), patch.object(
                utils, "log", return_value=logging.getLogger("test")
            ):
                selected = utils.get_audio_track()

            self.assertEqual(selected, verified)

    def test_every_track_has_a_valid_mood(self) -> None:
        from audio_factory import STYLE_PRESETS

        cfg = load_config("config.example.yaml")
        styles = set()
        filenames = set()
        for track in cfg.audio_tracks:
            filenames.add(track["filename"])
            style = track.get("style")
            self.assertIn(style, STYLE_PRESETS)
            styles.add(style)
        self.assertEqual(styles, set(STYLE_PRESETS))
        self.assertEqual(set(cfg.audio_verified_tracks), filenames)

    def test_topic_mood_mapping(self) -> None:
        import utils

        cases = {
            "supercar_pursuit": "action",
            "nightlife_neon": "nightlife",
            "alligator_wildlife": "tension",
            "taxi_missions": "fun",
        }
        for category, expected in cases.items():
            self.assertEqual(
                utils.resolve_audio_style({"category": category}), expected
            )
        self.assertEqual(
            utils.resolve_audio_style({"id_key": "everglades_wildlife"}),
            "tension",
        )
        self.assertEqual(
            utils.resolve_audio_style({"id_key": "nightlife_neon_tour"}),
            "nightlife",
        )
        self.assertEqual(
            utils.resolve_audio_style(
                {"category": "something_new", "audio_style": "fun"}
            ),
            "fun",
        )
        self.assertEqual(
            utils.resolve_audio_style({"category": "future_shark_topic"}),
            "tension",
        )
        self.assertEqual(
            utils.resolve_audio_style({"category": "unknown"}), "action"
        )

    def test_get_audio_track_respects_requested_style(self) -> None:
        from types import SimpleNamespace

        import utils

        with tempfile.TemporaryDirectory() as temp_dir:
            action = os.path.join(temp_dir, "original_phonk_1.mp3")
            nightlife = os.path.join(
                temp_dir, "original_nightlife_1.mp3"
            )
            Path(action).write_bytes(b"action-audio")
            Path(nightlife).write_bytes(b"nightlife-audio")

            fake_cfg = SimpleNamespace(
                audio_tracks=[
                    {
                        "filename": "original_phonk_1.mp3",
                        "license": "original",
                        "style": "action",
                    },
                    {
                        "filename": "original_nightlife_1.mp3",
                        "license": "original",
                        "style": "nightlife",
                    },
                ],
                audio_verified_tracks=[],
                get_assets_audio_path=lambda *parts: os.path.join(
                    temp_dir, *parts
                ),
            )
            with patch.object(
                utils, "get_config", return_value=fake_cfg
            ), patch.object(
                utils, "log", return_value=logging.getLogger("test")
            ):
                selected = utils.get_audio_track("nightlife")

            self.assertEqual(
                os.path.basename(selected), "original_nightlife_1.mp3"
            )

    def test_synthesized_styles_are_distinct(self) -> None:
        from audio_factory import STYLE_PRESETS, synthesize_style

        buffers = {}
        for style in STYLE_PRESETS:
            samples = synthesize_style(style, duration=0.4, seed=42)
            self.assertEqual(len(samples), int(0.4 * 44100))
            self.assertGreater(max(abs(sample) for sample in samples), 0.05)
            buffers[style] = samples

        styles = list(buffers)
        for index, first in enumerate(styles):
            for second in styles[index + 1:]:
                self.assertNotEqual(buffers[first], buffers[second])

    def test_audio_factory_creates_valid_wav(self) -> None:
        from audio_factory import synthesize_phonk, write_wav

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "beat.wav")
            samples = synthesize_phonk(duration=0.5, bpm=140, seed=7)
            write_wav(path, samples)

            with wave.open(path, "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertEqual(handle.getframerate(), 44100)
                self.assertAlmostEqual(
                    handle.getnframes() / 44100, 0.5, places=2
                )
                frames = handle.readframes(handle.getnframes())

            pcm = array.array("h")
            pcm.frombytes(frames)
            self.assertGreater(max(abs(value) for value in pcm), 1000)

    def test_example_config_uses_original_audio_only(self) -> None:
        cfg = load_config("config.example.yaml")
        self.assertTrue(cfg.audio_verified_tracks)
        for track in cfg.audio_tracks:
            self.assertEqual(track.get("license"), "original")

    def test_example_config_has_safer_cadence(self) -> None:
        cfg = load_config("config.example.yaml")
        self.assertEqual(cfg.schedule.shorts_max_per_day, 1)
        self.assertEqual(cfg.schedule.long_video_weekday, 5)

    def test_long_video_weekday_matching(self) -> None:
        from types import SimpleNamespace

        import utils

        fake_cfg = SimpleNamespace(
            schedule=SimpleNamespace(long_video_weekday=5)
        )
        saturday = datetime(
            2026, 11, 28, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")
        )
        friday = datetime(
            2026, 11, 27, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")
        )
        with patch.object(utils, "get_config", return_value=fake_cfg):
            self.assertTrue(utils.is_long_video_day(saturday))
            self.assertFalse(utils.is_long_video_day(friday))


class UploadBodyTests(unittest.TestCase):
    def test_channel_defaults_are_used(self) -> None:
        fake = ChannelConfig(
            name="Test",
            token_file="token.pickle",
            client_secret_file="client_secret.json",
            upload_defaults={
                "default_tags": ["default"],
                "category_id": "20",
                "language": "en",
            },
        )
        from upload_video import _build_snippet_body

        with patch("upload_video.get_channel_config", return_value=fake):
            body = _build_snippet_body(
                "Title", "Description", ["custom"], channel_key="other"
            )
        self.assertEqual(body["tags"], ["custom", "default"])
        self.assertEqual(body["categoryId"], "20")
        self.assertEqual(body["defaultLanguage"], "en")

    def test_approval_hold_forces_private_draft(self) -> None:
        from types import SimpleNamespace

        from upload_video import _build_status_body

        fake_channel = ChannelConfig(
            name="Test",
            token_file="token.pickle",
            client_secret_file="client_secret.json",
            upload_defaults={"privacy_status": "public"},
        )
        fake_config = SimpleNamespace(
            approval={"required": True, "auto_approve": True}
        )
        with patch(
            "upload_video.get_channel_config", return_value=fake_channel
        ), patch("upload_video.get_config", return_value=fake_config):
            body = _build_status_body(
                publish_at="2026-11-24T18:00:00+05:30"
            )
        self.assertEqual(body["privacyStatus"], "private")
        self.assertNotIn("publishAt", body)

    def test_no_approval_hold_schedules_publish(self) -> None:
        from types import SimpleNamespace

        from upload_video import _build_status_body

        fake_channel = ChannelConfig(
            name="Test",
            token_file="token.pickle",
            client_secret_file="client_secret.json",
            upload_defaults={"privacy_status": "public"},
        )
        fake_config = SimpleNamespace(
            approval={"required": False, "auto_approve": True}
        )
        with patch(
            "upload_video.get_channel_config", return_value=fake_channel
        ), patch("upload_video.get_config", return_value=fake_config):
            body = _build_status_body(
                publish_at="2026-11-24T18:00:00+05:30"
            )
        self.assertEqual(body["privacyStatus"], "private")
        self.assertEqual(
            body["publishAt"], "2026-11-24T18:00:00+05:30"
        )

    def test_duplicate_upload_returns_existing_video(self) -> None:
        import upload_video

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"not-a-real-video")
            path = handle.name
        try:
            with patch(
                "upload_video.validate_video_file",
                return_value=(
                    True,
                    "OK",
                    {
                        "size_bytes": 17,
                        "duration": 1.0,
                        "width": 1920,
                        "height": 1080,
                    },
                ),
            ), patch(
                "upload_video.build_upload_key",
                return_value=("key", "digest"),
            ), patch(
                "upload_video.find_ledger_entry",
                return_value={
                    "video_id": "existing123",
                    "uploaded_at": "2026-11-24T18:00:00+05:30",
                },
            ), patch(
                "upload_video.get_authenticated_service"
            ) as auth:
                response = upload_video.upload_video(
                    path, "Title", "Description"
                )
            self.assertEqual(response["id"], "existing123")
            self.assertTrue(response["duplicate"])
            auth.assert_not_called()
        finally:
            os.remove(path)


class MediaTests(unittest.TestCase):
    def test_generated_video_probes_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "test.mp4")
            subprocess.run(
                [
                    get_ffmpeg_exe(),
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=320x240:d=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    video_path,
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            info = probe_video(video_path)
            self.assertGreater(info["duration"], 0.5)
            self.assertEqual(info["width"], 320)
            ok, message, _ = validate_video_file(video_path)
            self.assertTrue(ok, message)

    def test_drawtext_sanitization(self) -> None:
        self.assertEqual(
            sanitize_drawtext("a:b'c&d%e"),
            "a\\:bcANDde",
        )

    def test_filter_size_uses_colons(self) -> None:
        self.assertEqual(resolution_to_filter_size("2560x1440"), "2560:1440")
        self.assertEqual(resolution_to_filter_size("1080x1920"), "1080:1920")
        with self.assertRaises(ValueError):
            resolution_to_filter_size("1080")

    def test_drawtext_font_path_has_no_drive_colon(self) -> None:
        project_root = str(Path(__file__).resolve().parent.parent)
        with patch("utils.os.getcwd", return_value=project_root):
            font = get_drawtext_font("C:/Windows/Fonts/ariblk.ttf")
        self.assertNotIn(":", font)
        self.assertTrue(font.endswith("ariblk.ttf"))


class HealthTests(unittest.TestCase):
    def test_package_check_uses_real_import_names(self) -> None:
        from health_check import check_python_packages

        result = check_python_packages()
        self.assertTrue(result["all_installed"], result["missing"])


if __name__ == "__main__":
    unittest.main()
