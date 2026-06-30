"""
CRUD operations for manually curated jobs.
"""
from datetime import datetime
from loguru import logger
from db.connection import get_pool
from utils.constants import FRONTEND_SKILLS, ACTIVE_EXPERIENCE


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


async def get_personalized_manual_jobs(
    user: dict, 
    seen_job_ids: list[int] = None, 
    limit: int = 12,
    exclude_sent_within_days: int = None,
    max_age_days: int = None
) -> list[dict]:
    """
    Fetch all active manual jobs, score them based on user skills/experience/batch,
    filter to frontend/fresher niche, filter out seen_jobs and recently sent jobs, and return the top matching jobs.
    """
    if seen_job_ids is None:
        seen_job_ids = []

    # Fetch a reasonable number of recent jobs to score (e.g., top 100 recent)
    all_jobs = await get_manual_jobs(limit=100, offset=0)
    if not all_jobs:
        return []
        
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    
    # 1. Age Filter (10-Day Expiry)
    if max_age_days is not None:
        valid_jobs = []
        for j in all_jobs:
            posted = j.get("posted_at")
            if posted:
                # Ensure it's aware
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                if (now - posted).days <= max_age_days:
                    valid_jobs.append(j)
        all_jobs = valid_jobs
        if not all_jobs:
            return []

    # 2. Seen Filter (Permanently ignore if they clicked it)
    if seen_job_ids:
        all_jobs = [j for j in all_jobs if j["id"] not in seen_job_ids]
        if not all_jobs:
            return []
            
    # 3. 3-Day Cooldown Filter (Ignore if sent in Daily Feed recently)
    if exclude_sent_within_days is not None:
        recently_sent = await get_recently_sent_jobs(user.get("telegram_id"), days=exclude_sent_within_days)
        if recently_sent:
            all_jobs = [j for j in all_jobs if j["id"] not in recently_sent]
            if not all_jobs:
                return []

    # Filter out jobs the user has already seen
    if seen_job_ids:
        all_jobs = [j for j in all_jobs if j["id"] not in seen_job_ids]
        if not all_jobs:
            return []

    from utils.messages import compute_manual_job_match

    # NICHE FILTER: Keep only frontend-relevant jobs with fresher experience level
    # FUTURE (multi-role): Remove or loosen this filter when expanding
    BACKEND_TITLE_KEYWORDS = [
        "fullstack", "full stack", "full-stack",
        "backend", "back-end", "back end",
        "node.js developer", "node developer",
        "django", "flask", "rails", "laravel",
        "devops", "cloud engineer", "data engineer",
        "machine learning", "ml engineer", "ai engineer",
    ]

    def is_frontend_fresher_job(job: dict) -> bool:
        job_skills = [s.lower() for s in (job.get("skills") or [])]
        has_frontend_skill = any(s in FRONTEND_SKILLS for s in job_skills)
        min_yoe = job.get("min_yoe") or 0
        is_fresher_level = min_yoe <= 1
        # Reject if job title is clearly backend/fullstack
        title_lower = (job.get("title") or "").lower()
        is_backend_title = any(kw in title_lower for kw in BACKEND_TITLE_KEYWORDS)
        return has_frontend_skill and is_fresher_level and not is_backend_title

    filtered_jobs = [j for j in all_jobs if is_frontend_fresher_job(j)]
    if not filtered_jobs:
        # Fallback: if admin hasn't tagged skills yet, show all with min_yoe <= 1
        # but still exclude clearly backend titles
        filtered_jobs = [
            j for j in all_jobs
            if (j.get("min_yoe") or 0) <= 1
            and not any(kw in (j.get("title") or "").lower() for kw in BACKEND_TITLE_KEYWORDS)
        ]

    for job in filtered_jobs:
        details = compute_manual_job_match(user, job)
        job["_match_score"] = details["score"]

    # Sort by score (DESC), then by posted date (DESC)
    filtered_jobs.sort(key=lambda j: (j["_match_score"], j["posted_at"]), reverse=True)

    return filtered_jobs[:limit]





async def count_manual_jobs() -> int:
    """Return total count of active manual jobs (for pagination)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM manual_jobs WHERE is_active = TRUE")
        return row["cnt"] if row else 0


async def get_seen_jobs(telegram_id: int) -> list[int]:
    """Get a list of job IDs the user has already seen."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT job_id FROM user_seen_jobs WHERE telegram_id = $1", telegram_id)
        return [r["job_id"] for r in rows]

async def mark_jobs_seen(telegram_id: int, job_ids: list[int]) -> None:
    """Mark a list of job IDs as seen by the user."""
    if not job_ids:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        # Insert ignoring conflicts
        query = """
            INSERT INTO user_seen_jobs (telegram_id, job_id)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id, job_id) DO NOTHING
        """
        await conn.executemany(query, [(telegram_id, jid) for jid in job_ids])

async def get_recently_sent_jobs(telegram_id: int, days: int = 3) -> list[int]:
    """Get jobs sent to this user in the daily feed within the last X days."""
    if not telegram_id:
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT DISTINCT job_id FROM jobs_sent_log 
            WHERE telegram_id = $1 AND sent_at >= NOW() - INTERVAL '1 day' * $2
        """
        rows = await conn.fetch(query, telegram_id, days)
        return [r["job_id"] for r in rows]

async def log_jobs_sent(telegram_id: int, job_ids: list[int]) -> None:
    """Log that these jobs were sent in a daily feed to trigger the cooldown."""
    if not job_ids or not telegram_id:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        query = """
            INSERT INTO jobs_sent_log (telegram_id, job_id)
            VALUES ($1, $2)
        """
        await conn.executemany(query, [(telegram_id, jid) for jid in job_ids])




async def cleanup_old_manual_jobs(days: int = 30) -> int:
    """Soft-delete manual jobs older than `days` days."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE manual_jobs 
            SET is_active = FALSE 
            WHERE is_active = TRUE AND posted_at < NOW() - INTERVAL '1 day' * $1
            """,
            days
        )
        # result is a string like "UPDATE 5"
        try:
            return int(result.split()[-1])
        except:
            return 0


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
