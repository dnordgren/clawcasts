"""Kokoro narration pipeline: document text to mp3.

Requires the optional `narrate` extra (`uv sync --extra narrate`) and
ffmpeg on PATH. Model weights are downloaded once to a cache directory
(override with CLAWCASTS_KOKORO_DIR).
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import wave
from pathlib import Path

import click

from .audio import encode_mp3

MODEL_URL = ("https://github.com/thewh1teagle/kokoro-onnx/releases/"
             "download/model-files-v1.1/kokoro-v1.0.onnx")
VOICES_URL = ("https://github.com/thewh1teagle/kokoro-onnx/releases/"
              "download/model-files-v1.1/voices-v1.0.bin")
SAMPLE_RATE = 24000
CHUNK_CHARS = 1200


class NarrateError(RuntimeError):
    """Narration cannot proceed."""


def kokoro_dir() -> Path:
    override = os.environ.get("CLAWCASTS_KOKORO_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    return Path(base) / "clawcasts" / "kokoro"


def _model_paths(cfg: dict | None) -> tuple[Path, Path]:
    cfg = cfg or {}
    d = kokoro_dir()
    model = Path(cfg["model_path"]) if cfg.get("model_path") else d / "kokoro-v1.0.onnx"
    voices = Path(cfg["voices_path"]) if cfg.get("voices_path") else d / "voices-v1.0.bin"
    return model, voices


def _download(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    click.echo(f"Downloading {label} to {dest} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "clawcasts/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp, part.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
            done += len(block)
            if total:
                click.echo(f"\r  {done / 1_048_576:.0f} / {total / 1_048_576:.0f} MB",
                           nl=False)
    click.echo("")
    part.replace(dest)


def ensure_models(cfg: dict | None = None) -> tuple[Path, Path]:
    """Return (model_path, voices_path), downloading them if missing."""
    model, voices = _model_paths(cfg)
    if not model.exists():
        _download(MODEL_URL, model, "Kokoro model (~310 MB)")
    if not voices.exists():
        _download(VOICES_URL, voices, "voice data (~27 MB)")
    return model, voices


_FRONT_MATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
_FENCED_CODE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST_MARKER = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"\*{1,3}([^*]+)\*{1,3}|_{1,3}([^_]+)_{1,3}")
_INLINE_CODE = re.compile(r"`([^`]*)`")


def markdown_to_text(md: str) -> str:
    """Reduce markdown to plain prose suitable for narration."""
    md = _FRONT_MATTER.sub("", md)
    md = _FENCED_CODE.sub("", md)
    md = _IMAGE.sub("", md)
    md = _LINK.sub(r"\1", md)
    md = _HTML_TAG.sub(" ", md)
    md = _HEADING.sub("", md)
    md = _LIST_MARKER.sub(r"\1", md)
    md = _EMPHASIS.sub(lambda m: m.group(1) or m.group(2), md)
    md = _INLINE_CODE.sub(r"\1", md)
    md = re.sub(r"^>+\s?", "", md, flags=re.MULTILINE)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def document_text(path: str | Path) -> str:
    """Read a .md or .txt document and return narration-ready text."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in {".md", ".markdown"}:
        text = markdown_to_text(raw)
    else:
        text = raw.strip()
    if not text:
        raise NarrateError(f"No narratable text found in {p}")
    return text


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split text into paragraph-based chunks under `limit` characters."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        for piece in _hard_wrap(para, limit):
            if current and len(current) + len(piece) + 2 > limit:
                chunks.append(current)
                current = piece
            elif current:
                current += "\n\n" + piece
            else:
                current = piece
    if current:
        chunks.append(current)
    return chunks


def chunk_sections(md: str, limit: int = CHUNK_CHARS,
                   depth: int | None = None
                   ) -> list[tuple[str, str | None]]:
    """Split markdown into (chunk, chapter_title) pairs.

    Chapter titles come from the document's headings; text before the
    first heading (or before any heading at or above `depth`) is paired
    with None. Deeper headings still reset sections but map to their
    nearest ancestor within the depth limit.
    """
    md = _FRONT_MATTER.sub("", md)
    md = _FENCED_CODE.sub("", md)
    pairs: list[tuple[str, str | None]] = []
    stack: list[tuple[int, str]] = []
    body: list[str] = []

    def chapter() -> str | None:
        for level, title in reversed(stack):
            if depth is None or level <= depth:
                return title
        return None

    def flush() -> None:
        text = markdown_to_text("\n".join(body))
        body.clear()
        if not text:
            return
        pairs.extend((c, chapter()) for c in chunk_text(text, limit))

    for line in md.splitlines():
        m = _HEADING_LINE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2)))
        else:
            body.append(line)
    flush()
    return pairs


def _hard_wrap(paragraph: str, limit: int) -> list[str]:
    if len(paragraph) <= limit:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        elif current:
            current += " " + sentence
        else:
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def _load_kokoro(cfg: dict | None):
    try:
        from kokoro_onnx import Kokoro
    except ModuleNotFoundError as exc:
        raise NarrateError(
            "kokoro-onnx is not installed. Run 'uv sync --extra narrate' "
            "(or 'uv tool install --extra narrate .')."
        ) from exc
    model, voices = ensure_models(cfg)
    click.echo(f"Loading Kokoro model from {model.parent} ...")
    return Kokoro(str(model), str(voices))


def narrate(doc_path: str, out_path: str, voice: str = "af_heart",
            speed: float = 1.0, lang: str = "en-us",
            title: str = "", artist: str = "",
            cfg: dict | None = None,
            chapters_depth: int | None = None
            ) -> tuple[str, list[dict]]:
    """Narrate a document to mp3 via Kokoro.

    Returns the output path plus chapter markers derived from the
    document's markdown headings as {"title", "start_time"} dicts with
    start times in seconds.
    """
    p = Path(doc_path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in {".md", ".markdown"}:
        pairs = chunk_sections(raw, depth=chapters_depth)
    else:
        text = raw.strip()
        if not text:
            raise NarrateError(f"No narratable text found in {p}")
        pairs = [(chunk, None) for chunk in chunk_text(text)]
    if not pairs:
        raise NarrateError(f"No narratable text found in {p}")
    kokoro = _load_kokoro(cfg)

    tmp_wav = Path(out_path).with_suffix(".wav.tmp")
    tmp_wav.parent.mkdir(parents=True, exist_ok=True)
    chapters: list[dict] = []
    try:
        import numpy as np

        with wave.open(str(tmp_wav), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            for i, (chunk, chapter) in enumerate(pairs):
                click.echo(f"Synthesizing chunk {i + 1}/{len(pairs)} "
                           f"({len(chunk)} chars) ...")
                start = wav.tell()
                samples, rate = kokoro.create(chunk, voice=voice,
                                              speed=speed, lang=lang)
                if rate != SAMPLE_RATE:
                    raise NarrateError(
                        f"Kokoro returned sample rate {rate}, "
                        f"expected {SAMPLE_RATE}")
                pcm = np.clip(np.asarray(samples), -1.0, 1.0)
                wav.writeframes((pcm * 32767).astype(np.int16).tobytes())
                if chapter and (not chapters
                                or chapters[-1]["title"] != chapter):
                    chapters.append({"title": chapter,
                                     "start_time": start / SAMPLE_RATE})
        encode_mp3(tmp_wav, Path(out_path), title=title, artist=artist)
    finally:
        tmp_wav.unlink(missing_ok=True)
    return out_path, chapters


def write_chapters_json(path: str | Path, chapters: list[dict]) -> Path:
    """Write chapters as Podcasting 2.0 JSON (times in milliseconds)."""
    payload = {
        "version": "1.2.0",
        "chapters": [{"startTime": int(round(c["start_time"] * 1000)),
                      "title": c["title"]} for c in chapters],
    }
    p = Path(path)
    p.write_text(json.dumps(payload, indent=2) + "\n")
    return p
