"""
CRUD operations for community job submissions.
"""
from loguru import logger
from db.connection import get_pool


async def create_submission(telegram_id: int, url: str) -> int:
    """Insert a new pending submission. Returns the new submission ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO user_submissions (telegram_id, url) VALUES ($1, $2) RETURNING id",
            telegram_id, url
        )
        return row["id"]


async def get_submission(submission_id: int) -> dict | None:
    """Fetch a single submission by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_submissions WHERE id = $1", submission_id
        )
        return dict(row) if row else None


async def check_url_status(normalized_url: str) -> dict | None:
    """Check if a normalized URL is already in the system (pending, approved, or live).
    Returns {"status": "live", "job_id": id} if live.
    Returns {"status": "pending"} if pending in user_submissions.
    Returns None if brand new.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Check manual_jobs first (live)
        # We use LIKE '%normalized_url%' because manual_jobs urls might not be perfectly normalized
        # But wait, it's safer to exact match if we normalize upon entry, or use LIKE
        # Actually, let's just exact match since we're passing in normalized URL, and we'll normalize existing ones on the fly or just match loosely.
        # For simplicity, we'll check if the stored url contains the normalized_url (which has stripped http/www)
        live_job = await conn.fetchrow(
            "SELECT id FROM manual_jobs WHERE url ILIKE $1 LIMIT 1", f"%{normalized_url}%"
        )
        if live_job:
            return {"status": "live", "job_id": live_job["id"]}

        # Check pending submissions
        pending = await conn.fetchval(
            "SELECT id FROM user_submissions WHERE url ILIKE $1 AND status IN ('pending','approved') LIMIT 1",
            f"%{normalized_url}%"
        )
        if pending:
            return {"status": "pending"}

        return None


async def mark_submission_rejected(submission_id: int) -> None:
    """Mark a submission as rejected."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_submissions SET status='rejected', reviewed_at=NOW() WHERE id=$1",
            submission_id
        )


async def mark_submission_approved(submission_id: int, manual_job_id: int) -> None:
    """Mark a submission as approved, linking it to the resulting manual_job."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_submissions SET status='approved', reviewed_at=NOW(), manual_job_id=$1 WHERE id=$2",
            manual_job_id, submission_id
        )


async def get_pending_submissions(limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Fetch pending submissions with pagination. Returns (submissions, total_count)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM user_submissions WHERE status='pending'")
        rows = await conn.fetch(
            "SELECT * FROM user_submissions WHERE status='pending' ORDER BY submitted_at ASC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(row) for row in rows], total
