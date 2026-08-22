"""Parse external podcast feeds for episode metadata."""

from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"

USER_AGENT = "clawcasts/0.1"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _duration_to_seconds(text: str | None) -> int | None:
    if not text:
        return None
    parts = [int(p) for p in text.strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts
    return hours * 3600 + minutes * 60 + seconds


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_channel(feed_url: str) -> dict:
    """Return channel artwork/title plus a list of episode dicts."""
    root = ET.fromstring(_fetch(feed_url))
    channel = root.find("channel")
    if channel is None:
        raise ValueError(f"No <channel> element in {feed_url}")

    art_el = channel.find(f"{ITUNES}image")
    result = {
        "title": channel.findtext("title", "").strip(),
        "artwork_url": art_el.get("href") if art_el is not None else None,
        "items": [],
    }

    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        art_item = item.find(f"{ITUNES}image")
        result["items"].append({
            "guid": (item.findtext("guid") or "").strip(),
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip() or None,
            "pubdate_source": (item.findtext("pubDate") or "").strip(),
            "enclosure_url": enclosure.get("url") if enclosure is not None else None,
            "file_size_bytes": (int(enclosure.get("length"))
                                if enclosure is not None
                                and enclosure.get("length", "").isdigit()
                                else None),
            "mime_type": (enclosure.get("type")
                          if enclosure is not None else None) or "audio/mpeg",
            "description": (_strip_html(item.findtext("description") or "")
                            or None),
            "content_html": ((item.findtext(f"{CONTENT}encoded") or "").strip()
                             or None),
            "image_url": (art_item.get("href") if art_item is not None
                          else None),
            "duration_seconds": _duration_to_seconds(
                item.findtext(f"{ITUNES}duration")),
        })
    return result


def find_item(channel: dict, query: str) -> dict:
    matches = [i for i in channel["items"]
               if i["enclosure_url"]
               and query.lower() in i["title"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        titles = "\n  ".join(m["title"] for m in matches)
        raise LookupError(
            f"'{query}' matches {len(matches)} episodes:\n  {titles}")
    raise LookupError(f"No episode matching '{query}' with an audio "
                      f"enclosure in '{channel['title']}'")
