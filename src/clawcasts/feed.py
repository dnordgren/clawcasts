from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from feedgen.feed import FeedGenerator

from .state import Episode, Manifest


def config_path() -> Path:
    override = os.environ.get("CLAWCASTS_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "clawcasts" / "config.toml"


def build_rss(manifest: Manifest, channel: dict, public_base: str) -> bytes:
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.id(channel.get("link", public_base))
    fg.title(channel["title"])
    fg.link(href=channel.get("link", public_base), rel="alternate")
    if channel.get("description"):
        fg.description(channel["description"])
    else:
        fg.description(channel["title"])
    fg.language("en")

    author = channel.get("author")
    if author:
        fg.author(name=author)
    fg.podcast.itunes_author(author or "clawcasts")
    if author and channel.get("email"):
        fg.podcast.itunes_owner(name=author, email=channel["email"])
    fg.podcast.itunes_block(True)

    now = datetime.now(timezone.utc)
    anchor = now
    for episode in manifest.episodes:
        fe = fg.add_entry()
        fe.id(episode.guid)
        fe.title(episode.title)
        if episode.description:
            fe.description(episode.description)
        else:
            fe.description(episode.title)

        audio_url = episode.audio_url
        if not audio_url and episode.local_path:
            name = Path(episode.local_path).name
            audio_url = f"{public_base}/media/{episode.guid}/{name}"
        if not audio_url:
            continue
        size = episode.file_size_bytes or 0
        fe.enclosure(audio_url, str(size), episode.mime_type)
        duration = _format_duration(episode.duration_seconds)
        if duration:
            fe.podcast.itunes_duration(duration)

        published = episode.pubdate_published
        floor = (datetime.fromisoformat(published) + timedelta(seconds=1)
                 if published else None)
        slot = anchor - timedelta(minutes=len(manifest.episodes))
        pubdate = max(slot, floor) if floor else slot
        if pubdate > now:
            pubdate = now
        fe.pubDate(pubdate)
        anchor = pubdate - timedelta(seconds=1)

    return fg.rss_str(pretty=True)


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
