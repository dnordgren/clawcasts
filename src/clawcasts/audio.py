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


def concat_mp3(paths: list[Path], out_path: Path) -> None:
    """Concatenate mp3 files losslessly, replacing any existing output.

    All inputs must share codec and sample rate; stream copy is used so
    no re-encode happens.
    """
    require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_path = out_path.with_suffix(".concat.txt")
    lines = [f"file '{str(p.resolve()).replace(chr(39), chr(39) * 2)}'\n"
             for p in paths]
    list_path.write_text("".join(lines))
    try:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(list_path),
               "-c", "copy", str(out_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise AudioToolError(
                f"ffmpeg concat failed: {result.stderr.strip()}")
    finally:
        list_path.unlink(missing_ok=True)


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
