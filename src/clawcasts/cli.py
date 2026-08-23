from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click

from . import __version__
from . import feed as feedgen_mod
from .state import (ARCHIVE, QUEUE, Episode, Manifest, STATUS_PENDING_AUDIO,
                    STATUS_PUBLISHED, STATUS_READY, state_dir, transfer)


@click.group()
@click.version_option(__version__, prog_name="clawcasts")
def main() -> None:
    """Personal podcast queue and archive feeds on S3/CloudFront."""


@main.command()
def init() -> None:
    """Create the config directory with an example config."""
    path = feedgen_mod.config_path()
    if path.exists():
        click.echo(f"Config already exists: {path}")
        return
    example = "\n".join([
        "# clawcasts infrastructure config",
        "bucket = \"my-podcast-bucket\"",
        "public_base = \"https://cdn.example.com\"",
        "distribution_id = \"E1234ABCDEF\"",
        "region = \"us-east-1\"",
        "profile = \"clawcasts\"",
        "",
        "[queue]",
        'title = "Derek\'s Queue"',
        'link = "https://example.com"',
        'author = "Derek Nordgren"',
        'email = ""',
        "",
        "[archive]",
        'title = "Derek\'s Archive"',
        'link = "https://example.com"',
        'author = "Derek Nordgren"',
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example + "\n")
    click.echo(f"Wrote example config: {path}")


def _remote_size(url: str) -> int | None:
    import urllib.request

    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "clawcasts/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            length = resp.headers.get("Content-Length")
            return int(length) if length else None
    except OSError:
        return None


_IMAGE_URL = re.compile(r"^https?://", re.IGNORECASE)


def _apply_image(episode: Episode, value: str) -> None:
    """Set episode artwork from an http(s) URL or a local file path."""
    if _IMAGE_URL.match(value):
        episode.image_url = value
        return
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise click.ClickException(f"Artwork file not found: {path}")
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise click.ClickException(
            "Artwork must be a .jpg, .jpeg, or .png file.")
    episode.image_path = str(path)


@main.command()
@click.option("--title", required=True)
@click.option("--url", help="Remote audio URL for an externally hosted episode.")
@click.option("--file", "local_file", type=click.Path(exists=True),
              help="Local audio file to publish later.")
@click.option("--description", default="")
@click.option("--image", default=None,
              help="Episode artwork: http(s) URL or local image file.")
@click.option("--feed", default=QUEUE, type=click.Choice([QUEUE, ARCHIVE]))
@click.option("--position", type=int, default=None,
              help="Insert at this queue position (default: end).")
def add(title: str, url: str | None, local_file: str | None,
        description: str, image: str | None, feed: str,
        position: int | None) -> None:
    """Add an episode to a feed."""
    if not url and not local_file:
        raise click.UsageError("Provide --url or --file.")
    kwargs = {"title": title, "description": description}
    if url:
        size = _remote_size(url)
        episode = Episode.create(source_kind="rss",
                                 source_detail={"url": url},
                                 audio_url=url, status=STATUS_READY,
                                 file_size_bytes=size, **kwargs)
        if size is None:
            click.echo("Warning: could not determine remote file size.", err=True)
    else:
        path = Path(local_file).resolve()
        duration = _probe_duration(path)
        episode = Episode.create(
            source_kind="narration", local_path=str(path),
            duration_seconds=duration,
            file_size_bytes=path.stat().st_size,
            status=STATUS_READY, **kwargs)
    if image:
        _apply_image(episode, image)
    manifest = Manifest.load(feed)
    pos = manifest.add(episode, position)
    path = manifest.save()
    short = episode.guid[:8]
    click.echo(f"Added [{pos}] {title} ({short}) to '{feed}'")
    click.echo(f"Manifest: {path}")


@main.command("list")
@click.option("--feed", default=QUEUE, type=click.Choice([QUEUE, ARCHIVE]))
def list_cmd(feed: str) -> None:
    """List episodes in a feed."""
    manifest = Manifest.load(feed)
    if not manifest.episodes:
        click.echo(f"Feed '{feed}' is empty.")
        return
    for i, ep in enumerate(manifest.episodes):
        dur = f" {ep.duration_seconds}s" if ep.duration_seconds else ""
        click.echo(f"{i:3}  {ep.guid[:8]}  {ep.status:<14} {ep.title}{dur}")


@main.command()
@click.argument("prefix")
@click.option("--feed", default=QUEUE, type=click.Choice([QUEUE, ARCHIVE]))
def remove(prefix: str, feed: str) -> None:
    """Remove an episode from a feed by guid prefix."""
    manifest = Manifest.load(feed)
    episode = _find(manifest, prefix)
    manifest.remove(episode)
    manifest.save()
    click.echo(f"Removed '{episode.title}' ({episode.guid[:8]}) from '{feed}'")


@main.command()
@click.argument("prefix")
@click.option("--to", "position", type=int, default=None,
              help="Move to this position (0 = top of queue).")
@click.option("--before", "before", default=None,
              help="Place before this other guid prefix.")
@click.option("--after", "after", default=None,
              help="Place after this other guid prefix.")
@click.option("--feed", default=QUEUE, type=click.Choice([QUEUE, ARCHIVE]))
def move(prefix: str, position: int | None, before: str | None,
         after: str | None, feed: str) -> None:
    """Reorder an episode within a feed."""
    given = sum(x is not None for x in (position, before, after))
    if given != 1:
        raise click.UsageError("Use exactly one of --to, --before, --after.")
    manifest = Manifest.load(feed)
    episode = _find(manifest, prefix)
    if position is not None:
        new_pos = manifest.move(episode, position)
    else:
        other_prefix = before or after
        other = _find(manifest, other_prefix)
        current = manifest.episodes.index(other)
        target = current if before else current + 1
        new_pos = manifest.move(episode, target)
    manifest.save()
    click.echo(f"'{episode.title}' moved to position {new_pos} in '{feed}'")


@main.command()
@click.argument("prefix")
@click.option("--image", default=None,
              help="Episode artwork: http(s) URL or local image file.")
@click.option("--clear", is_flag=True, default=False,
              help="Remove the episode's artwork override.")
def artwork(prefix: str, image: str | None, clear: bool) -> None:
    """Set or clear artwork on an existing episode."""
    if (image is None) != bool(clear):
        raise click.UsageError("Use exactly one of --image or --clear.")
    for feed in (QUEUE, ARCHIVE):
        manifest = Manifest.load(feed)
        try:
            episode = manifest.find(prefix)
        except LookupError:
            continue
        if clear:
            episode.image_url = None
            episode.image_path = None
        else:
            _apply_image(episode, image)
        manifest.save()
        click.echo(f"Artwork updated for '{episode.title}' "
                   f"({episode.guid[:8]}) in '{feed}'")
        return
    raise click.ClickException(
        f"No episode with guid prefix '{prefix}' in '{QUEUE}' or '{ARCHIVE}'")


@main.command("mark-listened")
@click.argument("prefix")
def mark_listened(prefix: str) -> None:
    """Move an episode from the queue to the archive feed."""
    episode = transfer(QUEUE, ARCHIVE, prefix)
    click.echo(f"Archived '{episode.title}' ({episode.guid[:8]})")


@main.command("mark-new")
@click.argument("prefix")
def mark_new(prefix: str) -> None:
    """Move an episode from the archive back to the queue."""
    episode = transfer(ARCHIVE, QUEUE, prefix)
    click.echo(f"Returned '{episode.title}' ({episode.guid[:8]}) to queue")


@main.command()
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--out", "out_dir", type=click.Path(), default=None,
              help="Directory for locally generated RSS (default: <state>/out).")
def sync(dry_run: bool, out_dir: str | None) -> None:
    """Generate RSS and print (or execute) the upload plan."""
    from .s3sync import build_plan, execute

    cfg_path = feedgen_mod.config_path()
    if not cfg_path.exists():
        raise click.ClickException(
            f"No config at {cfg_path}. Run 'clawcasts init' first.")
    cfg = _load_toml(cfg_path)
    if not cfg.get("bucket") or not cfg.get("public_base"):
        raise click.ClickException(
            "Config needs 'bucket' and 'public_base' set.")

    out_root = Path(out_dir) if out_dir else state_dir() / "out"
    out_root.mkdir(parents=True, exist_ok=True)

    base = cfg["public_base"].rstrip("/")
    manifests = {name: Manifest.load(name) for name in (QUEUE, ARCHIVE)}

    media: list[tuple[str, str]] = []
    for manifest in manifests.values():
        for ep in manifest.episodes:
            if ep.local_path and not ep.audio_url:
                path = Path(ep.local_path)
                if not path.exists():
                    raise click.ClickException(
                        f"Missing audio for '{ep.title}': {path}")
                if not ep.file_size_bytes:
                    ep.file_size_bytes = path.stat().st_size
                media.append((str(path), f"media/{ep.guid}/{path.name}"))
            if ep.image_path and not ep.image_url:
                image = Path(ep.image_path)
                if not image.exists():
                    raise click.ClickException(
                        f"Missing artwork for '{ep.title}': {image}")
                media.append((str(image),
                              f"media/{ep.guid}/{image.name}"))

    rss: dict[str, bytes] = {}
    for name, manifest in manifests.items():
        channel = dict(cfg.get(name, {}))
        channel.setdefault("title", name.capitalize())
        xml = feedgen_mod.build_rss(manifest, channel, base)
        rss[f"{name}.xml"] = xml
        target = out_root / f"{name}.xml"
        target.write_bytes(xml)

    sync_plan = build_plan(cfg, media, rss)
    for line in sync_plan.describe():
        click.echo(line)
    if dry_run:
        click.echo("Dry run. Re-run without --dry-run to publish.")
        return

    execute(sync_plan, dry_run=False, profile_cfg=cfg)
    for name, manifest in manifests.items():
        for ep in manifest.episodes:
            changed = False
            if ep.local_path and not ep.audio_url and \
                    ep.status == STATUS_READY:
                ep.audio_url = \
                    f"{base}/media/{ep.guid}/{Path(ep.local_path).name}"
                ep.status = STATUS_PUBLISHED
                changed = True
            if ep.image_path and not ep.image_url:
                ep.image_url = \
                    f"{base}/media/{ep.guid}/{Path(ep.image_path).name}"
                changed = True
            if changed:
                manifest.save()
    click.echo(f"Published {len(media)} media file(s) and "
               f"{len(rss)} feed(s) to s3://{cfg['bucket']}/")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "episode"


def _probe_duration(path: Path) -> int | None:
    from .audio import probe_duration_seconds

    duration = probe_duration_seconds(path)
    if duration is None:
        click.echo("Warning: ffprobe unavailable; duration not set.", err=True)
    return duration


@main.command()
@click.argument("doc", type=click.Path(exists=True))
@click.option("--title", required=True)
@click.option("--voice", default="af_heart", show_default=True,
              help="Kokoro voice name (see Kokoro-82M VOICES.md).")
@click.option("--speed", type=float, default=1.0, show_default=True)
@click.option("--lang", default="en-us", show_default=True)
@click.option("--description", required=True,
              help="Brief summary of the episode; becomes the RSS "
                   "description.")
@click.option("--image", default=None,
              help="Episode artwork: http(s) URL or local image file.")
def narrate(doc: str, title: str, voice: str, speed: float, lang: str,
            description: str, image: str | None) -> None:
    """Narrate a document via Kokoro and add it to the top of the queue.

    The calling agent must supply --description as a brief summary of
    the transcript.
    """
    from .audio import AudioToolError
    from .narrate import NarrateError
    from .narrate import narrate as run_narration

    cfg = {}
    cfg_path = feedgen_mod.config_path()
    if cfg_path.exists():
        cfg = _load_toml(cfg_path)
    narrate_cfg = dict(cfg.get("narrate", {}))
    artist = (cfg.get(QUEUE, {}) or {}).get("author", "")

    episode = Episode.create(title=title, description=description,
                             source_kind="narration")
    if image:
        _apply_image(episode, image)
    out_path = (state_dir() / "audio" /
                f"{_slugify(title)}-{episode.guid[:8]}.mp3")

    try:
        run_narration(doc, str(out_path), voice=voice, speed=speed,
                      lang=lang, title=title, artist=artist,
                      cfg=narrate_cfg)
    except (NarrateError, AudioToolError) as exc:
        raise click.ClickException(str(exc))

    audio = Path(out_path)
    episode.local_path = str(audio.resolve())
    episode.duration_seconds = _probe_duration(audio)
    episode.file_size_bytes = audio.stat().st_size
    episode.status = STATUS_READY

    manifest = Manifest.load(QUEUE)
    manifest.add(episode, 0)
    manifest.save()
    minutes = (episode.duration_seconds or 0) // 60
    size_mb = (episode.file_size_bytes or 0) / 1_048_576
    click.echo(f"Added [0] {title} ({episode.guid[:8]}, "
               f"~{minutes}m, {size_mb:.1f} MB) to '{QUEUE}'")
    click.echo(f"Audio: {episode.local_path}")


@main.command()
@click.argument("rss_url")
@click.option("--limit", default=15, help="Max episodes to list.")
def import_feed(rss_url: str, limit: int) -> None:
    """List episodes available to lift from an external RSS feed."""
    from .rsssource import fetch_channel

    channel = fetch_channel(rss_url)
    click.echo(f"Feed: {channel['title']} "
               f"({len(channel['items'])} items)")
    shown = 0
    for i, item in enumerate(channel["items"]):
        if not item["enclosure_url"] or shown >= limit:
            continue
        dur = item["duration_seconds"]
        dur_s = f"{dur // 60}m" if dur else "?"
        date = (item["pubdate_source"] or "")[:16]
        click.echo(f"{i:4}  [{dur_s:>5}] {date}  {item['title'][:70]}")
        shown += 1


@main.command("add-from-feed")
@click.argument("rss_url")
@click.option("--match", required=True,
              help="Case-insensitive substring of the episode title.")
@click.option("--feed", default=QUEUE, type=click.Choice([QUEUE, ARCHIVE]))
@click.option("--position", type=int, default=None,
              help="Insert at this queue position (default: end).")
def add_from_feed(rss_url: str, match: str, feed: str,
                  position: int | None) -> None:
    """Add an external episode with full metadata from its source feed."""
    from .rsssource import fetch_channel, find_item

    channel = fetch_channel(rss_url)
    try:
        item = find_item(channel, match)
    except LookupError as exc:
        raise click.ClickException(str(exc))
    episode = Episode.create(
        title=item["title"],
        description=item["description"] or "",
        content_html=item["content_html"] or "",
        image_url=item["image_url"],
        link=item["link"],
        source_kind="rss",
        source_detail={"feed": rss_url, "guid": item["guid"]},
        audio_url=item["enclosure_url"],
        duration_seconds=item["duration_seconds"],
        file_size_bytes=item["file_size_bytes"]
        or _remote_size(item["enclosure_url"]),
        mime_type=item["mime_type"],
        status=STATUS_READY,
    )
    manifest = Manifest.load(feed)
    pos = manifest.add(episode, position)
    manifest.save()
    short = episode.guid[:8]
    size_mb = (episode.file_size_bytes or 0) / 1_048_576
    click.echo(f"Added [{pos}] {item['title'][:60]} ({short}, "
               f"{size_mb:.0f} MB) to '{feed}'")


@main.command("export-opml")
@click.option("--out", "out_path", type=click.Path(), default=None,
              help="Write OPML to this file (default: stdout).")
def export_opml(out_path: str | None) -> None:
    """Export queue and archive feed URLs as OPML for a podcatcher."""
    from .opml import build_opml

    cfg_path = feedgen_mod.config_path()
    if not cfg_path.exists():
        raise click.ClickException(
            f"No config at {cfg_path}. Run 'clawcasts init' first.")
    cfg = _load_toml(cfg_path)
    base = (cfg.get("public_base") or "").rstrip("/")
    if not base:
        raise click.ClickException("Config needs 'public_base' set.")
    outlines = []
    for name in (QUEUE, ARCHIVE):
        channel = cfg.get(name, {})
        title = channel.get("title", name.capitalize())
        outlines.append((title, f"{base}/{name}.xml"))
    xml = build_opml("clawcasts", outlines)
    if out_path:
        Path(out_path).write_bytes(xml)
        click.echo(f"Wrote {out_path}")
    else:
        click.echo(xml.decode(), nl=False)


def _load_toml(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        raise click.ClickException("Python 3.11+ required (tomllib).")
    return tomllib.loads(path.read_text())


def _find(manifest: Manifest, prefix: str):
    try:
        return manifest.find(prefix)
    except LookupError as exc:
        raise click.ClickException(str(exc))


if __name__ == "__main__":
    main(sys.argv[1:])
