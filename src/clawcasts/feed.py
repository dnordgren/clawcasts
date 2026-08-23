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
    if channel.get("artwork"):
        fg.podcast.itunes_image(channel["artwork"])
        fg.logo(channel["artwork"])
        fg.image(url=channel["artwork"], title=fg.title(),
                 link=channel.get("link", public_base))

    now = datetime.now(timezone.utc)
    for i, episode in enumerate(manifest.episodes):
        fe = fg.add_entry()
        fe.id(episode.guid)
        fe.title(episode.title)

        pubdate = now - timedelta(minutes=(i + 1))
        episode.pubdate_published = pubdate.isoformat()

        audio_url = episode.audio_url
        if not audio_url and episode.local_path:
            name = Path(episode.local_path).name
            audio_url = f"{public_base}/media/{episode.guid}/{name}"
        if not audio_url:
            continue
        size = episode.file_size_bytes or 0
        fe.enclosure(audio_url, str(size), episode.mime_type)
        if episode.link:
            fe.link(href=episode.link)
        if episode.content_html:
            fe.content(episode.content_html)
        if episode.description:
            fe.description(episode.description)
        else:
            fe.description(episode.title)
        image_url = episode_image_url(episode, public_base)
        if image_url:
            fe.podcast.itunes_image(image_url)
        duration = _format_duration(episode.duration_seconds)
        if duration:
            fe.podcast.itunes_duration(duration)
        fe.pubDate(pubdate)

    return fg.rss_str(pretty=True)


def episode_image_url(episode: Episode, public_base: str) -> str | None:
    """Resolve an episode's artwork URL from override or local file."""
    if episode.image_url:
        return episode.image_url
    if episode.image_path:
        name = Path(episode.image_path).name
        return f"{public_base}/media/{episode.guid}/{name}"
    return None


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
