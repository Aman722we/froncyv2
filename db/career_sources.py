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
    """Update last_checked_at and optionally last_successful_check_at."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if success:
            await conn.execute(
                """
                UPDATE career_sources
                SET last_checked_at = NOW(), last_successful_check_at = NOW(), last_error = NULL
                WHERE id = $1
                """,
                source_id
            )
        else:
            await conn.execute(
                """
                UPDATE career_sources
                SET last_checked_at = NOW(), last_error = $2
                WHERE id = $1
                """,
                source_id, error
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
