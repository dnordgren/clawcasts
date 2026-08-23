"""S3 upload and CloudFront invalidation."""

from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass, field
from pathlib import Path

MEDIA_CACHE_CONTROL = "public, max-age=31536000, immutable"
RSS_CACHE_CONTROL = "max-age=0, must-revalidate"


@dataclass
class MediaUpload:
    local_path: Path
    key: str
    content_type: str


@dataclass
class SyncPlan:
    bucket: str
    media: list[MediaUpload] = field(default_factory=list)
    rss_keys: dict[str, bytes] = field(default_factory=dict)
    distribution_id: str | None = None

    def describe(self) -> list[str]:
        lines = ["Upload plan:"]
        lines += [f"  up   s3://{self.bucket}/{m.key}" for m in self.media]
        lines += [f"  rss  s3://{self.bucket}/{k}" for k in self.rss_keys]
        if self.distribution_id:
            inv = ",".join(f"/{k}" for k in self.rss_keys)
            lines.append(f"  inv  {self.distribution_id}: [{inv}]")
        else:
            lines.append("  inv  (none: no distribution_id configured)")
        return lines


def session_for(cfg: dict):
    import boto3

    kwargs = {"region_name": cfg.get("region", "us-east-1")}
    if cfg.get("profile"):
        kwargs["profile_name"] = cfg["profile"]
    return boto3.Session(**kwargs)


def _content_type(path: Path) -> str:
    if path.name.endswith(".chapters.json"):
        return "application/json+chapters"
    guessed = mimetypes.guess_type(path.name)[0]
    return guessed or "audio/mpeg"


def build_plan(cfg: dict, media: list[tuple[str, str]],
               rss: dict[str, bytes]) -> SyncPlan:
    """media: list of (local_path, s3_key)."""
    return SyncPlan(
        bucket=cfg["bucket"],
        media=[MediaUpload(Path(p), k, _content_type(Path(p)))
               for p, k in media],
        rss_keys=rss,
        distribution_id=cfg.get("distribution_id"),
    )


def execute(plan: SyncPlan, dry_run: bool = True,
            profile_cfg: dict | None = None) -> None:
    if dry_run:
        return
    cfg = profile_cfg or {}
    s3 = session_for(cfg).client("s3")

    for m in plan.media:
        extra = {"ContentType": m.content_type,
                 "CacheControl": MEDIA_CACHE_CONTROL}
        s3.upload_file(str(m.local_path), plan.bucket, m.key,
                       ExtraArgs=extra)

    for key, body in plan.rss_keys.items():
        s3.put_object(Bucket=plan.bucket, Key=key, Body=body,
                      ContentType="application/rss+xml",
                      CacheControl=RSS_CACHE_CONTROL)

    if plan.distribution_id:
        cf = session_for(cfg).client("cloudfront")
        cf.create_invalidation(
            DistributionId=plan.distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": len(plan.rss_keys),
                          "Items": [f"/{k}" for k in plan.rss_keys]},
                "CallerReference": f"clawcasts-{uuid.uuid4()}",
            },
        )
