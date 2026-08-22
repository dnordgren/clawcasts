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
   - Only ever bump pubDates forward, never backward, to avoid clients
     resurfacing played episodes.
   - Queue position 0 is newest. On sync, positions map to descending
     timestamps anchored at now, clamped to be monotonic with each
     episode's previous published pubDate.
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

1. **M0 (this scaffold).** State model, local commands fully working,
   `sync` generates RSS locally and prints the upload plan. Remote stubs.
2. **M1.** S3 upload + RSS publish + CloudFront invalidation. Real
   `sync`. AWS creds from environment or `~/.aws`.
3. **M2.** `narrate` wired to Kokoro; duration/file-size extraction
   (mutagen or ffprobe); artwork.
4. **M3.** `import-feed` / `--from-rss` episode lifting; OPML export;
   optional cron-friendly `sync` daemon notes.

## Open questions

- Pocket Casts refresh cadence: does it honor short TTL without explicit
  ping? (It has no public ping API; invalidation covers us.)
- Chapter markers (`podcast:chapters`) for narrated docs — later.
- Whether archive feed should also drop episodes older than N months.
