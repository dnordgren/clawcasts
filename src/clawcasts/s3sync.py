"""S3 upload and CloudFront invalidation. Stub until M1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SyncPlan:
    uploads: list[str]
    rss_objects: list[str]
    invalidations: list[str]


def plan(bucket: str, prefix: str, changed_media: list[str]) -> SyncPlan:
    """Compute the S3 keys and invalidations a sync would perform."""
    return SyncPlan(
        uploads=[f"s3://{bucket}/{prefix}/media/{p}" for p in changed_media],
        rss_objects=[f"s3://{bucket}/{prefix}/queue.xml",
                     f"s3://{bucket}/{prefix}/archive.xml"],
        invalidations=[f"/{prefix}/*.xml"],
    )


def execute(plan: SyncPlan, dry_run: bool = True) -> None:
    if dry_run:
        return
    raise NotImplementedError("sync upload is not implemented yet (M1).")
