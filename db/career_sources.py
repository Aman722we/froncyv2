"""
CRUD for career_sources table — the manually curated list of companies to monitor.
"""
from loguru import logger
from db.connection import get_pool


async def add_career_source(company_name: str, provider: str, board_token: str, careers_url: str = None) -> int:
    """Add a new company to monitor. Returns new ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO career_sources (company_name, provider, board_token, careers_url)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            company_name, provider.upper(), board_token.lower(), careers_url
        )
        return row["id"]


async def get_active_career_sources() -> list[dict]:
    """Return all active company sources to monitor."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM career_sources WHERE is_active = TRUE ORDER BY company_name"
        )
        return [dict(r) for r in rows]


async def get_all_career_sources() -> list[dict]:
    """Return all company sources (for admin listing)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM career_sources ORDER BY is_active DESC, company_name"
        )
        return [dict(r) for r in rows]


async def update_source_check(source_id: int, success: bool, error: str = None) -> None:
    """Update last_checked_at, last_successful_check_at, and operational RFC-005 health columns."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if success:
            await conn.execute(
                """
                UPDATE career_sources
                SET last_checked_at = NOW(), 
                    last_successful_check_at = NOW(), 
                    last_error = NULL,
                    consecutive_fetch_failures = 0,
                    last_fetch_status = 'ok'
                WHERE id = $1
                """,
                source_id
            )
        else:
            status_desc = f"error_{error[:20]}" if error else "error"
            await conn.execute(
                """
                UPDATE career_sources
                SET last_checked_at = NOW(), 
                    last_error = $2,
                    consecutive_fetch_failures = consecutive_fetch_failures + 1,
                    last_fetch_status = $3
                WHERE id = $1
                """,
                source_id, error, status_desc[:30]
            )


async def toggle_source(source_id: int, is_active: bool) -> bool:
    """Enable or disable a source."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE career_sources SET is_active = $2 WHERE id = $1",
            source_id, is_active
        )
        return result == "UPDATE 1"


async def job_already_exists(provider: str, external_id: str) -> bool:
    """Check if a job from this provider with this external ID already exists."""
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT 1 FROM manual_jobs WHERE source_provider = $1 AND source_external_id = $2",
            provider.upper(), str(external_id)
        )
        return val is not None

async def source_already_exists(provider: str, board_token: str) -> bool:
    """Check if a source is already in the database."""
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT 1 FROM career_sources WHERE provider = $1 AND board_token = $2",
            provider.upper(), board_token.lower()
        )
        return val is not None


_SUMMARY_CACHE: dict = {"ts": 0.0, "data": None}


def invalidate_tracked_companies_cache() -> None:
    """Clear the cached tracked companies summary."""
    _SUMMARY_CACHE["ts"] = 0.0
    _SUMMARY_CACHE["data"] = None


async def get_tracked_companies_summary(cache_ttl_seconds: int = 3600) -> dict:
    """
    Return exact count & real sample names of active, successfully-fetched career sources.
    Cached in-memory for 1 hour to avoid repeated DB queries on menu opens.
    """
    import time

    now = time.monotonic()
    if _SUMMARY_CACHE["data"] is not None and (now - _SUMMARY_CACHE["ts"]) < cache_ttl_seconds:
        return _SUMMARY_CACHE["data"]

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT company_name, last_successful_check_at
            FROM career_sources
            WHERE is_active = TRUE
              AND last_successful_check_at IS NOT NULL
              AND company_name IS NOT NULL
              AND TRIM(company_name) <> ''
            ORDER BY last_successful_check_at DESC
            """
        )

    seen_lower: set[str] = set()
    unique_names: list[str] = []
    for r in rows:
        name = (r["company_name"] or "").strip()
        key = name.lower()
        if name and key not in seen_lower:
            seen_lower.add(key)
            unique_names.append(name)

    result = {
        "count": len(unique_names),
        "samples": unique_names[:8],
    }
    _SUMMARY_CACHE["ts"] = now
    _SUMMARY_CACHE["data"] = result
    return result
