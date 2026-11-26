"""Locally synthesized, original background music for the channel.

Why this exists
---------------
The old ``assets/audio/phonk_1.mp3`` matched a third-party Content ID claim
("Infraction - Don't Care").  Downloading a "royalty-free" track is also not a
guarantee: the same recording can be registered by someone else later.

This module creates a beat from scratch with sine/noise oscillators.  It does
not download, sample, or copy any existing recording, so the output is original
and cannot be matched to a third-party master recording by Content ID.

Usage:
    python audio_factory.py
    python audio_factory.py --count 3 --duration 32
    python audio_factory.py --force
"""
from __future__ import annotations

import argparse
import array
import logging
import math
import os
import random
import subprocess
import tempfile
import wave
from typing import List, Optional

log = logging.getLogger("audio_factory")

SAMPLE_RATE = 44100
DEFAULT_DURATION = 32.0
DEFAULT_BPM = 140.0

# F minor palette (Hz).
F1, AB1, C2, EB2 = 43.65, 51.91, 65.41, 77.78
F3, AB3, C4 = 174.61, 207.65, 261.63
F4, AB4, C5 = 349.23, 415.30, 523.25


def _add_kick(mix: List[float], start: int, amp: float, sr: int) -> None:
    """Deep 808-style kick with a short pitch sweep."""
    n = min(int(0.38 * sr), len(mix) - start)
    phase = 0.0
    for i in range(n):
        t = i / sr
        freq = 45.0 + 105.0 * math.exp(-t * 28.0)
        phase += 2.0 * math.pi * freq / sr
        env = math.exp(-t * 11.0)
        click = math.exp(-t * 120.0) * 0.35
        mix[start + i] += amp * (math.sin(phase) * env + click)


def _add_snare(
    mix: List[float], start: int, amp: float, sr: int, rng: random.Random
) -> None:
    """Noise snare with a small tonal body."""
    n = min(int(0.22 * sr), len(mix) - start)
    prev = 0.0
    for i in range(n):
        t = i / sr
        noise = rng.uniform(-1.0, 1.0)
        high = noise - prev  # crude high-pass to keep the snare crisp
        prev = noise
        env = math.exp(-t * 26.0)
        body = math.sin(2.0 * math.pi * 185.0 * t) * math.exp(-t * 30.0) * 0.5
        mix[start + i] += amp * (high * env * 0.7 + body)


def _add_hat(
    mix: List[float],
    start: int,
    amp: float,
    sr: int,
    rng: random.Random,
    open_hat: bool = False,
) -> None:
    """Short closed hat or a longer open hat."""
    duration = 0.18 if open_hat else 0.055
    n = min(int(duration * sr), len(mix) - start)
    prev = 0.0
    decay = 14.0 if open_hat else 70.0
    for i in range(n):
        t = i / sr
        noise = rng.uniform(-1.0, 1.0)
        high = noise - prev
        prev = noise
        mix[start + i] += amp * high * math.exp(-t * decay)


def _add_bass(
    mix: List[float], start: int, freq: float, amp: float, sr: int
) -> None:
    """Punchy 808 bass note with a short pitch drop."""
    duration = 0.55
    n = min(int(duration * sr), len(mix) - start)
    phase = 0.0
    for i in range(n):
        t = i / sr
        current = freq * (1.0 + 0.06 * math.exp(-t * 30.0))
        phase += 2.0 * math.pi * current / sr
        env = math.exp(-t * 3.2)
        tone = (
            math.sin(phase)
            + 0.28 * math.sin(2.0 * phase)
            + 0.12 * math.sin(3.0 * phase)
        )
        mix[start + i] += amp * tone * env


def _add_cowbell(
    mix: List[float], start: int, freq: float, amp: float, sr: int
) -> None:
    """Metallic cowbell accent."""
    n = min(int(0.28 * sr), len(mix) - start)
    for i in range(n):
        t = i / sr
        env = math.exp(-t * 11.0)
        tone = math.sin(2.0 * math.pi * freq * t) + 0.55 * math.sin(
            2.0 * math.pi * freq * 2.4 * t
        )
        mix[start + i] += amp * tone * env


def _add_pad(mix: List[float], sr: int) -> None:
    """Quiet, slowly breathing minor chord under the drums."""
    n = len(mix)
    for i in range(n):
        t = i / sr
        lfo = 0.55 + 0.45 * math.sin(2.0 * math.pi * 0.07 * t)
        chord = (
            math.sin(2.0 * math.pi * F3 * t)
            + math.sin(2.0 * math.pi * AB3 * t)
            + math.sin(2.0 * math.pi * C4 * t)
        ) / 3.0
        mix[i] += 0.055 * chord * lfo


def _add_crackle(
    mix: List[float], sr: int, rng: random.Random, density: float = 0.00012
) -> None:
    """Sparse vinyl-style crackle for texture."""
    n = len(mix)
    for i in range(n):
        if rng.random() >= density:
            continue
        amp = rng.uniform(0.01, 0.05)
        length = min(int(0.01 * sr), n - i)
        for j in range(length):
            mix[i + j] += amp * math.exp(-j / (0.002 * sr)) * (
                1.0 if j % 2 == 0 else -1.0
            )


def synthesize_phonk(
    duration: float = DEFAULT_DURATION,
    bpm: float = DEFAULT_BPM,
    seed: int = 1,
    sample_rate: int = SAMPLE_RATE,
) -> List[float]:
    """Return a mono float sample buffer in the range [-1, 1]."""
    n = int(duration * sample_rate)
    mix = [0.0] * n
    rng = random.Random(seed)

    step_duration = 60.0 / bpm / 4.0  # one 16th note
    steps = int(duration / step_duration)

    kick_steps = {0, 6, 8, 14}
    snare_steps = {4, 12}
    bass_pattern = {0: F1, 3: F1, 6: AB1, 8: C2, 11: AB1, 14: EB2}
    bell_pattern = {2: F4, 7: AB4, 10: C5, 15: F4}

    for step in range(steps):
        start = int(step * step_duration * sample_rate)
        if start >= n:
            break
        bar_step = step % 16

        if bar_step in kick_steps:
            _add_kick(mix, start, 0.95, sample_rate)
        if bar_step in snare_steps:
            _add_snare(mix, start, 0.55, sample_rate, rng)
        if bar_step % 2 == 0:
            _add_hat(
                mix,
                start,
                0.22,
                sample_rate,
                rng,
                open_hat=(bar_step == 14),
            )
        if bar_step in bass_pattern:
            _add_bass(mix, start, bass_pattern[bar_step], 0.75, sample_rate)
        if bar_step in bell_pattern:
            _add_cowbell(mix, start, bell_pattern[bar_step], 0.16, sample_rate)

    _add_pad(mix, sample_rate)
    _add_crackle(mix, sample_rate, rng)

    # Raise the average level without letting the transients clip.  A plain
    # peak normalize leaves sparse drum tracks sounding quiet on phone
    # speakers, so target a musical RMS first and then respect the peak.
    peak = max(abs(sample) for sample in mix) or 1.0
    rms = math.sqrt(sum(sample * sample for sample in mix) / max(1, n)) or 1.0
    gain = min(0.16 / rms, 0.95 / peak)
    fade = max(1, int(0.08 * sample_rate))
    for i in range(n):
        value = mix[i] * gain
        if i < fade:
            value *= i / fade
        elif i >= n - fade:
            value *= (n - i) / fade
        mix[i] = max(-1.0, min(1.0, value))
    return mix


def write_wav(
    path: str, samples: List[float], sample_rate: int = SAMPLE_RATE
) -> None:
    """Write mono 16-bit PCM."""
    pcm = array.array(
        "h",
        (
            int(max(-1.0, min(1.0, sample)) * 32767)
            for sample in samples
        ),
    )
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def _encode_mp3(wav_path: str, mp3_path: str, ffmpeg_exe: str) -> bool:
    """Encode WAV to MP3.  Return False when the encoder is unavailable."""
    command = [
        ffmpeg_exe,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        wav_path,
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "192k",
        "-ac",
        "2",
        mp3_path,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=120,
        )
        return os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0
    except (OSError, subprocess.SubprocessError):
        return False


def generate_track(
    output_dir: str,
    index: int,
    duration: float = DEFAULT_DURATION,
    bpm: float = DEFAULT_BPM,
    ffmpeg_exe: Optional[str] = None,
    force: bool = False,
) -> str:
    """Generate one original track and return its path (MP3 preferred)."""
    os.makedirs(output_dir, exist_ok=True)
    base = f"original_phonk_{index}"
    mp3_path = os.path.join(output_dir, base + ".mp3")
    wav_path = os.path.join(output_dir, base + ".wav")

    if not force:
        if os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0:
            return mp3_path
        if os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0:
            return wav_path

    log.info("Synthesizing original track %s (%.0fs, %.0f BPM)...", base, duration, bpm)
    samples = synthesize_phonk(duration=duration, bpm=bpm, seed=1000 + index)
    write_wav(wav_path, samples)

    if ffmpeg_exe:
        if _encode_mp3(wav_path, mp3_path, ffmpeg_exe):
            try:
                os.remove(wav_path)
            except OSError:
                pass
            return mp3_path
        log.warning("MP3 encoder unavailable; keeping WAV for %s", base)

    return wav_path


def ensure_original_audio(
    audio_dir: str,
    count: int = 3,
    duration: float = DEFAULT_DURATION,
    ffmpeg_exe: Optional[str] = None,
    force: bool = False,
) -> List[str]:
    """Create the requested number of original tracks if they are missing."""
    paths: List[str] = []
    for index in range(1, max(1, count) + 1):
        bpm = DEFAULT_BPM + (index - 2) * 2.0
        paths.append(
            generate_track(
                audio_dir,
                index,
                duration=duration,
                bpm=bpm,
                ffmpeg_exe=ffmpeg_exe,
                force=force,
            )
        )
    return paths


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    parser = argparse.ArgumentParser(
        description="Generate original copyright-safe background music."
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join("assets", "audio"),
        help="Directory for generated tracks (default: assets/audio)",
    )
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate tracks even when they already exist",
    )
    args = parser.parse_args()

    ffmpeg_exe = None
    try:
        from utils import get_ffmpeg_exe

        ffmpeg_exe = get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - environment-dependent
        log.warning("FFmpeg not available; WAV files will be used: %s", exc)

    for path in ensure_original_audio(
        args.output_dir,
        count=args.count,
        duration=args.duration,
        ffmpeg_exe=ffmpeg_exe,
        force=args.force,
    ):
        print(path)


if __name__ == "__main__":
    main()
