"""
Source Geo Snapshots & Health Database Operations (RFC-005).
Handles append-only snapshot persistence, weekly scheduling with jitter,
and write-minimized operational health updates.
"""
from datetime import datetime, date, timezone
from loguru import logger
from db.connection import get_pool


def is_snapshot_due(source: dict, now_utc: datetime) -> bool:
    """
    Evaluates whether a source is due for an opportunistic weekly snapshot.
    - Sources with last_geo_snapshot_at: due if >= 7 calendar days since last snapshot date.
    - Sources with last_geo_snapshot_at IS NULL (first snapshot):
      Uses a deterministic hour-of-the-week offset (0 to 167 hours) based on source_id:
        offset_hours = (source_id * 17) % 168
      Eligible as soon as source age >= offset_hours.
      If it fails on the target hour, it retries on every subsequent hourly crawl until a snapshot is recorded.
    """
    last_snapshot = source.get("last_geo_snapshot_at")
    if last_snapshot is not None:
        if hasattr(last_snapshot, "date"):
            last_date = last_snapshot.date()
        else:
            last_date = last_snapshot
        return (now_utc.date() - last_date).days >= 7

    # First-ever snapshot for this source: apply deterministic jitter offset
    source_id = source.get("id", 1)
    offset_hours = (source_id * 17) % 168
    created_at = source.get("created_at")
    if created_at is not None:
        if hasattr(created_at, "tzinfo") and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_hours = (now_utc - created_at).total_seconds() / 3600.0
    else:
        # Default fallback: eligible immediately
        age_hours = 168.0

    return age_hours >= offset_hours


async def record_weekly_snapshot(source_id: int, tally: dict, snapshot_date: date) -> None:
    """
    Persists a weekly snapshot to source_geo_snapshots and updates career_sources.
    Executed in a single transaction block for strict atomicity.
    Decision: latest scan on the same UTC date wins (ON CONFLICT DO UPDATE).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Upsert snapshot row
            await conn.execute(
                """
                INSERT INTO source_geo_snapshots (
                    source_id, snapshot_date, scanned_at,
                    total_board_jobs, india_tech_jobs, india_non_tech_jobs,
                    remote_global_jobs, remote_ambiguous_jobs, foreign_jobs, unclassified_jobs
                ) VALUES ($1, $2, NOW(), $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (source_id, snapshot_date) DO UPDATE SET
                    scanned_at              = EXCLUDED.scanned_at,
                    total_board_jobs        = EXCLUDED.total_board_jobs,
                    india_tech_jobs         = EXCLUDED.india_tech_jobs,
                    india_non_tech_jobs     = EXCLUDED.india_non_tech_jobs,
                    remote_global_jobs      = EXCLUDED.remote_global_jobs,
                    remote_ambiguous_jobs   = EXCLUDED.remote_ambiguous_jobs,
                    foreign_jobs            = EXCLUDED.foreign_jobs,
                    unclassified_jobs       = EXCLUDED.unclassified_jobs;
                """,
                source_id,
                snapshot_date,
                tally.get("total_board_jobs", 0),
                tally.get("india_tech_jobs", 0),
                tally.get("india_non_tech_jobs", 0),
                tally.get("remote_global_jobs", 0),
                tally.get("remote_ambiguous_jobs", 0),
                tally.get("foreign_jobs", 0),
                tally.get("unclassified_jobs", 0),
            )

            # 2. Update last_geo_snapshot_at & increment consecutive_empty_snapshots if total == 0
            is_empty = (tally.get("total_board_jobs", 0) == 0)
            await conn.execute(
                """
                UPDATE career_sources
                SET last_geo_snapshot_at = NOW(),
                    consecutive_empty_snapshots = CASE 
                        WHEN $2 = TRUE THEN consecutive_empty_snapshots + 1 
                        ELSE 0 
                    END
                WHERE id = $1;
                """,
                source_id,
                is_empty,
            )


async def maybe_reset_empty_counter(source_id: int, total_board_jobs: int) -> None:
    """
    Write-minimized reset of consecutive_empty_snapshots on hourly crawl.
    Only executes a write if total_board_jobs > 0 AND consecutive_empty_snapshots > 0.
    In the common case (counter is 0), PostgreSQL finds 0 rows -> 0 disk writes.
    """
    if total_board_jobs <= 0:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE career_sources
            SET consecutive_empty_snapshots = 0
            WHERE id = $1 AND consecutive_empty_snapshots > 0;
            """,
            source_id,
        )


async def update_source_fetch_health(source_id: int, success: bool, status_desc: str = "ok") -> None:
    """
    Updates operational health counters.
    Write-minimized:
      - If success=True: Only writes if consecutive_fetch_failures > 0 or last_fetch_status != 'ok'.
        (Common happy path generates 0 DB writes).
      - If success=False: Increments failure counter and records status description.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if success:
            await conn.execute(
                """
                UPDATE career_sources
                SET consecutive_fetch_failures = 0,
                    last_fetch_status = 'ok'
                WHERE id = $1 AND (consecutive_fetch_failures > 0 OR last_fetch_status != 'ok');
                """,
                source_id,
            )
        else:
            await conn.execute(
                """
                UPDATE career_sources
                SET consecutive_fetch_failures = consecutive_fetch_failures + 1,
                    last_fetch_status = $2
                WHERE id = $1;
                """,
                source_id,
                status_desc[:30],
            )


async def maybe_record_weekly_snapshot(
    source: dict,
    tally: dict,
    is_truncated: bool = False,
    now_utc: datetime | None = None,
) -> bool:
    """
    Orchestrates the RFC-005 snapshot recording at the end of a source crawl:
      1. Conditionally resets empty counter if board has active jobs.
      2. If truncated, skips snapshot and logs warning.
      3. Checks if snapshot is due.
      4. Records snapshot inside an atomic transaction.
    Returns True if a snapshot was recorded, False otherwise.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    source_id = source["id"]
    total_jobs = tally.get("total_board_jobs", 0)

    # 1. Reset empty counter if active jobs found
    await maybe_reset_empty_counter(source_id, total_jobs)

    # 2. Truncation guard
    if is_truncated:
        logger.warning(
            f"⚠️ Skipping geo snapshot for source #{source_id} ({source.get('company_name')}) "
            f"due to detected payload truncation ({total_jobs} jobs returned)."
        )
        return False

    # 3. Check if due
    if not is_snapshot_due(source, now_utc):
        return False

    # 4. Record atomic snapshot
    await record_weekly_snapshot(source_id, tally, now_utc.date())
    logger.info(
        f"📸 Geo snapshot saved for source #{source_id} ({source.get('company_name')}): "
        f"{total_jobs} total board jobs ({tally.get('india_tech_jobs', 0)} India Tech, "
        f"{tally.get('remote_global_jobs', 0)} Global Remote, {tally.get('foreign_jobs', 0)} Foreign)"
    )
    return True
