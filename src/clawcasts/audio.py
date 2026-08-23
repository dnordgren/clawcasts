"""Audio metadata extraction and mp3 encoding via ffmpeg tools."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AudioToolError(RuntimeError):
    """ffmpeg/ffprobe is missing or failed."""


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise AudioToolError(
                f"'{tool}' not found on PATH. Install ffmpeg "
                "(it provides both ffmpeg and ffprobe)."
            )


def probe_duration_seconds(path: Path) -> int | None:
    """Return audio duration rounded to whole seconds, or None."""
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return round(float(result.stdout.strip()))
    except ValueError:
        return None


def encode_mp3(wav_path: Path, mp3_path: Path, title: str = "",
               artist: str = "", album: str = "") -> None:
    """Encode a WAV file to mp3, replacing any existing output."""
    require_ffmpeg()
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(wav_path), "-codec:a", "libmp3lame", "-qscale:a", "4"]
    if title:
        cmd += ["-metadata", f"title={title}"]
    if artist:
        cmd += ["-metadata", f"artist={artist}"]
    if album:
        cmd += ["-metadata", f"album={album}"]
    cmd.append(str(mp3_path))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioToolError(f"ffmpeg failed: {result.stderr.strip()}")
