# clawcasts

Personal podcast feed manager. Maintains a listen queue (and an archive
feed) as RSS on S3/CloudFront, consumable by any podcatcher such as
Pocket Casts.

## Goals

- One command-line binary, `clawcasts`, that owns all deterministic work.
- Thin OpenClaw skill that documents the commands and Derek's setup only.
- Two RSS channels: `queue` (listen queue) and `archive` (listened).
  Both share the same media objects in S3; they differ only in manifest.
- Episodes come from two sources: local audio narrated via Kokoro, or
  episodes lifted from existing hosted RSS feeds.

## Architecture decisions

1. **CLI separate from OpenClaw.** Lives here, installed on PATH. The
   skill wraps it. Config lives with the CLI under `~/.config/clawcasts/`
   so credentials never enter vault context.
2. **Sync is the single write path.** `add`, `remove`, `move`,
   `mark-listened` mutate local state only. `sync` diffs state against a
   published-state snapshot, uploads changed media, regenerates RSS, and
   invalidates CloudFront. Idempotent; supports `--dry-run`. A failed
   narration never half-publishes a feed.
3. **Stable GUIDs.** Each episode gets a UUID at `add` time that never
   changes. Clients key on GUID, so edits and reorders do not create
   phantom episodes.
4. **Ordering is pubDate ordering.** Podcatchers sort by pubDate, so
   "reorder" means rewriting pubDates on sync. Rules:
   - Queue position 0 is newest: position `i` gets `now - (i+1) minute`.
   - pubDates are rewritten from scratch on every sync (GUIDs keep
     played state stable in clients; ordering always matches the
     manifest exactly).
5. **Archive is a second channel**, not deletion. `mark-listened` moves
   the episode between manifests. Media files stay put.
6. **Caching strategy.** RSS XML gets near-zero TTL (or a CloudFront
   invalidation per sync); media objects get long TTLs.

## State model

Per-feed manifest JSON in `~/.local/share/clawcasts/<feed>.json`
(override with `CLAWCASTS_STATE_DIR`). Episode fields:

| Field | Purpose |
| --- | --- |
| `guid` | Stable UUID, assigned at add time |
| `title`, `description` | Episode metadata |
| `source` | `narration` (local doc) or `rss` (external episode) plus origin details |
| `audio_url` | Remote URL, set after first successful upload |
| `duration_seconds`, `file_size_bytes`, `mime_type` | Required for valid iTunes RSS |
| `pubdate_published` | Last pubDate clients saw; null until first sync |
| `status` | `pending-audio`, `ready`, `published` |

Infra config in `~/.config/clawcasts/config.toml`: bucket, prefix,
CloudFront distribution/domain, feed channel metadata (title, author,
artwork).

## Commands

```bash
clawcasts init                          # Write example config if missing
clawcasts add --title T (--url URL | --from-rss FEED --episode GUID)
clawcasts remove <guid-prefix>
clawcasts move <guid-prefix> (--before | --after) <other-guid> | --to N
clawcasts list [--feed queue|archive]
clawcasts mark-listened <guid-prefix>   # queue -> archive manifest
clawcasts narrate <doc> --title T       # Kokoro -> mp3 -> add to queue
clawcasts sync [--dry-run]              # Upload + regenerate RSS + invalidate
clawcasts import-feed <rss-url>         # List episodes available to lift
```

## Phases

1. **M0 — DONE.** State model, local commands fully working, `sync`
   generates RSS locally and prints the upload plan.
2. **M1 — DONE, LIVE.** S3 upload + RSS publish + CloudFront
   invalidation. See "Live deployment" below.
3. **M2 — NEXT.** `narrate` wired to Kokoro; duration/file-size
   extraction (mutagen or ffprobe); episode artwork.
4. **M3 — MOSTLY DONE.** `import-feed <rss-url>` lists episodes;
   `add-from-feed <rss-url> --match "<title substring>"` lifts an
   episode with full metadata (description/show notes, episode artwork,
   duration, link, enclosure size). Remaining: optional media copy to
   S3 for episodes whose upstream hosting may vanish; OPML export.
5. **M4 — ideas.** OPML export; prune archive older than N months;
   chapter markers (`podcast:chapters`) for narrated docs; optional
   cron/systemd timer for scheduled syncs on the claw machine.

## Live deployment

- Bucket: `dereknordgren-clawcasts` (us-east-1), no key prefix. Media at
  `media/<guid>/<filename>`; feeds at `/queue.xml` and `/archive.xml`.
- CloudFront distribution `E3SHNCWWKF8OI7`, domain
  `https://d1kmujx7to45cg.cloudfront.net`, OAC-protected origin (objects
  are private; only CloudFront serves them). RSS gets
  `max-age=0, must-revalidate` plus an invalidation of both `.xml` paths
  per sync; media gets `max-age=31536000, immutable`.
- AWS profile: `clawcasts` (IAM user in account 354450307824). Policy is
  scoped to this bucket + distribution; it cannot list buckets or
  distributions but can read them by ID.
- Queue feed (subscribe in Pocket Casts):
  `https://d1kmujx7to45cg.cloudfront.net/queue.xml`
  Archive feed: `https://d1kmujx7to45cg.cloudfront.net/archive.xml`

## Notes for the next agent

- Run everything through the CLI; never hand-edit manifests or RSS.
- Always `sync --dry-run` before `sync`; show Derek the plan first.
- Env overrides for testing: `CLAWCASTS_STATE_DIR`,
  `CLAWCASTS_CONFIG`. Local dev: `uv sync && uv run clawcasts ...`.
- Known behavior: feedgen emits items sorted ascending by pubDate in the
  XML document; clients order by pubDate anyway, so effective queue
  order always matches manifest position 0 = newest.
- External episodes store `source_kind="rss"` with the original URL;
  media is not copied to S3 (bandwidth-cheap, but means deletion of the
  upstream episode breaks playback).
- `mark-listened`/`mark-new` transfer between the two manifests; media
  objects stay put so both feeds can share them.

## Open questions

- Pocket Casts refresh cadence: does it honor short TTL without explicit
  ping? (It has no public ping API; invalidation covers us.)
- Chapter markers (`podcast:chapters`) for narrated docs — later.
- Whether archive feed should also drop episodes older than N months.
