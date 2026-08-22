# clawcasts

Personal podcast listen queue and archive feeds published as RSS on
S3/CloudFront for any podcatcher. See [PLAN.md](PLAN.md) for design
decisions and roadmap.

```bash
uv sync                      # Set up the environment
uv run clawcasts --help      # Or install globally: uv tool install .
```

## Commands

| Command | Purpose |
| --- | --- |
| `clawcasts init` | Write example config to `~/.config/clawcasts/config.toml` |
| `clawcasts add --title T (--url URL \| --file F)` | Add an episode |
| `clawcasts list [--feed queue\|archive]` | List episodes in a feed |
| `clawcasts move <prefix> (--to N \| --before P \| --after P)` | Reorder within a feed |
| `clawcasts remove <prefix>` | Remove from a feed |
| `clawcasts mark-listened <prefix>` | Queue → archive feed |
| `clawcasts mark-new <prefix>` | Archive → queue feed |
| `clawcasts narrate <doc> --title T` | Kokoro narration → queue (M2) |
| `clawcasts sync [--dry-run]` | Generate RSS and upload to S3 |
| `clawcasts import-feed <rss-url>` | Lift episodes from external RSS (M3) |

Episode identity is a stable GUID assigned at `add` time; ordering maps
to `pubDate` on sync, so reorders never create phantom episodes.

## AWS infrastructure

One S3 bucket behind one CloudFront distribution serves both feeds.
The bucket is private; CloudFront reads through Origin Access Control
(OAC). Media objects cache long; `*.xml` uses a short-TTL cache policy.

| Resource | Value |
| --- | --- |
| Account ID | `354450307824` |
| S3 bucket | `dereknordgren-clawcasts` (us-east-1) |
| OAC ID | `E1OYX1FD473VO` |
| Distribution ID | `E3SHNCWWKF8OI7` |
| Feed base URL | `https://d1kmujx7to45cg.cloudfront.net` |
| IAM user | `clawcasts` with managed policy `clawcasts-publish` |

### Cache behavior

- Default (`*`): managed `CachingOptimized` — long TTLs for media.
- `*.xml`: custom policy `clawcasts-rss-short-ttl` (TTL 60 s, max 300 s)
  so podcatchers pick up reorders quickly. `sync` also issues a
  CloudFront invalidation per publish.

### Access setup

The publishing credentials live outside chat context. Create an access
key for the dedicated IAM user and store it in a named profile:

```bash
aws iam create-access-key --user-name clawcasts
# Add to ~/.aws/credentials under [clawcasts]
```

`infra/iam-policy.json` holds the least-privilege policy as code:
`ListBucket`, `GetObject`, `PutObject`, `DeleteObject` scoped to the
bucket, plus `cloudfront:CreateInvalidation` scoped to the distribution.

Note: account IDs, bucket names, and CloudFront domains are not secrets
— they appear in every ARN and public URL. Never commit access keys or
secret keys; those live only in `~/.aws/credentials`.

## Status

M0 scaffold: local state management works end to end; `sync` generates
RSS locally and executes the upload plan. Narration (Kokoro) and
external-feed import are not wired yet — see PLAN.md phases.
