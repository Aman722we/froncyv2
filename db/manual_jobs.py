"""
CRUD operations for manually curated jobs.
"""
from datetime import datetime
from loguru import logger
from db.connection import get_pool


async def add_manual_job(data: dict) -> int:
    """
    Insert a new manually curated job.
    data keys: title, company, url, location, salary, job_type, duration,
               skills (list[str]), min_yoe (int), eligible_batches (list[int]),
               added_by (int telegram_id), posted_at (datetime optional)
    Returns: new job ID
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO manual_jobs (
                title, company, url, location, salary, job_type, duration,
                skills, min_yoe, eligible_batches, added_by, posted_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING id
            """,
            data["title"],
            data["company"],
            data["url"],
            data.get("location"),
            data.get("salary"),
            data.get("job_type", "fulltime"),
            data.get("duration"),
            [s.lower() for s in data.get("skills", [])],
            data.get("min_yoe", 0),
            data.get("eligible_batches", []),
            data.get("added_by"),
            data.get("posted_at") or datetime.utcnow(),
        )
        job_id = row["id"]
        logger.info(f"Manual job added: ID={job_id} — {data['title']} @ {data['company']}")
        return job_id


async def get_manual_jobs(
    skills: list[str] | None = None,
    location: str = "both",
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """
    Fetch ALL active manual jobs, sorted newest first.
    Admin-curated jobs are always shown to every user regardless of skills or location.
    Match scoring is handled in Python separately.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM manual_jobs
            WHERE is_active = TRUE
            ORDER BY posted_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

        result = []
        for row in rows:
            d = dict(row)
            d["is_manual"] = True
            result.append(d)
        return result


async def get_personalized_manual_jobs(user: dict, limit: int = 12) -> list[dict]:
    """
    Fetch all active manual jobs, score them based on user skills/experience/batch,
    and return the top matching jobs.
    """
    # Fetch a reasonable number of recent jobs to score (e.g., top 100 recent)
    all_jobs = await get_manual_jobs(limit=100, offset=0)
    if not all_jobs:
        return []

    from utils.messages import compute_manual_job_match
    
    # Optional role filtering if the user has a filter active in the context
    # But since this function signature only takes 'user' dict right now,
    # we'll do the role filtering in handlers/jobs.py if needed, or we can add filters to this function signature later.
    
    for job in all_jobs:
        details = compute_manual_job_match(user, job)
        job["_match_score"] = details["score"]

    # Sort by score (DESC), then by posted date (DESC)
    all_jobs.sort(key=lambda j: (j["_match_score"], j["posted_at"]), reverse=True)
    
    return all_jobs[:limit]





async def count_manual_jobs() -> int:
    """Return total count of active manual jobs (for pagination)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM manual_jobs WHERE is_active = TRUE")
        return row["cnt"] if row else 0


async def get_manual_job_by_id(job_id: int) -> dict | None:
    """Get a single manual job by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM manual_jobs WHERE id = $1", job_id
        )
        if row:
            d = dict(row)
            d["is_manual"] = True
            return d
        return None


async def deactivate_manual_job(job_id: int) -> bool:
    """Soft-delete a manual job (sets is_active = FALSE)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE manual_jobs SET is_active = FALSE WHERE id = $1",
            job_id,
        )
        return result == "UPDATE 1"


async def list_manual_jobs_admin() -> list[dict]:
    """List all active manual jobs for admin review."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, company, job_type, posted_at, is_active FROM manual_jobs ORDER BY posted_at DESC LIMIT 50"
        )
        return [dict(row) for row in rows]
