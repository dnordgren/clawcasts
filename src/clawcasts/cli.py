from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import __version__
from . import feed as feedgen_mod
from .state import (ARCHIVE, QUEUE, Episode, Manifest, STATUS_PENDING_AUDIO,
                    STATUS_PUBLISHED, STATUS_READY, now_iso, state_dir,
                    transfer)


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


@main.command()
@click.option("--title", required=True)
@click.option("--url", help="Remote audio URL for an externally hosted episode.")
@click.option("--file", "local_file", type=click.Path(exists=True),
              help="Local audio file to publish later.")
@click.option("--description", default="")
@click.option("--feed", default=QUEUE, type=click.Choice([QUEUE, ARCHIVE]))
@click.option("--position", type=int, default=None,
              help="Insert at this queue position (default: end).")
def add(title: str, url: str | None, local_file: str | None,
        description: str, feed: str, position: int | None) -> None:
    """Add an episode to a feed."""
    if not url and not local_file:
        raise click.UsageError("Provide --url or --file.")
    kwargs = {"title": title, "description": description}
    if url:
        episode = Episode.create(source_kind="rss",
                                 source_detail={"url": url},
                                 audio_url=url, status=STATUS_READY, **kwargs)
    else:
        episode = Episode.create(source_kind="narration",
                                 local_path=str(Path(local_file).resolve()),
                                 status=STATUS_READY, **kwargs)
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
            if ep.local_path and not ep.audio_url and \
                    ep.status == STATUS_READY:
                filename = Path(ep.local_path).name
                ep.audio_url = f"{base}/media/{ep.guid}/{filename}"
                ep.status = STATUS_PUBLISHED
        manifest.save()
    click.echo(f"Published {len(media)} media file(s) and "
               f"{len(rss)} feed(s) to s3://{cfg['bucket']}/")


@main.command()
@click.argument("doc", type=click.Path(exists=True))
@click.option("--title", required=True)
@click.option("--voice", default="af_heart")
def narrate(doc: str, title: str, voice: str) -> None:
    """Narrate a document via Kokoro and add it to the queue."""
    from .narrate import narrate as run_narration
    out_path = state_dir() / "audio" / f"{now_iso().replace(':', '')}.mp3"
    result = run_narration(doc, str(out_path), voice=voice)
    add.callback(title=title, url=None, local_file=result, description="",
                 feed=QUEUE, position=0)


@main.command()
@click.argument("rss_url")
def import_feed(rss_url: str) -> None:
    """List episodes available to lift from an external RSS feed."""
    raise NotImplementedError("import-feed is not implemented yet (M3).")


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
