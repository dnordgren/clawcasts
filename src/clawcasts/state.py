from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

QUEUE = "queue"
ARCHIVE = "archive"

STATUS_PENDING_AUDIO = "pending-audio"
STATUS_READY = "ready"
STATUS_PUBLISHED = "published"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Episode:
    guid: str
    title: str
    description: str = ""
    author: str | None = None
    content_html: str = ""
    image_url: str | None = None
    image_path: str | None = None
    chapters_url: str | None = None
    chapters_path: str | None = None
    link: str | None = None
    source_kind: str = "narration"  # narration | rss
    source_detail: dict = field(default_factory=dict)
    audio_url: str | None = None
    local_path: str | None = None
    duration_seconds: int | None = None
    file_size_bytes: int | None = None
    mime_type: str = "audio/mpeg"
    pubdate_published: str | None = None
    added_at: str = field(default_factory=now_iso)
    status: str = STATUS_PENDING_AUDIO

    @classmethod
    def create(cls, title: str, **kwargs) -> "Episode":
        return cls(guid=str(uuid.uuid4()), title=title, **kwargs)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Episode":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def state_dir() -> Path:
    override = os.environ.get("CLAWCASTS_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))
    return Path(base) / "clawcasts"


def manifest_path(feed: str) -> Path:
    return state_dir() / f"{feed}.json"


@dataclass
class Manifest:
    feed: str
    episodes: list[Episode] = field(default_factory=list)

    @classmethod
    def load(cls, feed: str) -> "Manifest":
        path = manifest_path(feed)
        if not path.exists():
            return cls(feed=feed)
        data = json.loads(path.read_text())
        episodes = [Episode.from_dict(e) for e in data.get("episodes", [])]
        return cls(feed=feed, episodes=episodes)

    def save(self) -> Path:
        path = manifest_path(self.feed)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {"version": 1, "feed": self.feed,
                   "updated_at": now_iso(),
                   "episodes": [e.to_dict() for e in self.episodes]}
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(path)
        return path

    def find(self, prefix: str) -> Episode:
        matches = [e for e in self.episodes if e.guid.startswith(prefix)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise LookupError(f"ambiguous guid prefix '{prefix}' matches {len(matches)} episodes")
        raise LookupError(f"no episode with guid prefix '{prefix}' in '{self.feed}'")

    def add(self, episode: Episode, position: int | None = None) -> int:
        if position is None or position >= len(self.episodes):
            self.episodes.append(episode)
        else:
            self.episodes.insert(max(position, 0), episode)
        return self.episodes.index(episode)

    def remove(self, episode: Episode) -> None:
        self.episodes.remove(episode)

    def move(self, episode: Episode, position: int) -> int:
        self.episodes.remove(episode)
        position = max(0, min(position, len(self.episodes)))
        self.episodes.insert(position, episode)
        return position


def transfer(feed_from: str, feed_to: str, prefix: str) -> Episode:
    src = Manifest.load(feed_from)
    dst = Manifest.load(feed_to)
    episode = src.find(prefix)
    src.remove(episode)
    dst.add(episode)
    src.save()
    dst.save()
    return episode
