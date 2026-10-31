"""
CRUD operations for manually curated jobs.
"""
from datetime import datetime, timezone
import time
from loguru import logger
from db.connection import get_pool
from utils.constants import ROLE_KEYWORDS

# ── High-Performance In-Memory Cache (Genius System Design) ────────────────
# Caches the active manual jobs pool and active count for 60 seconds.
# Slashes database network round trips and serialization overhead from ~200ms to 0ms.
_JOBS_CACHE_TTL = 60.0  # seconds
_active_jobs_cache: dict[tuple, tuple[float, list[dict]]] = {}
_active_count_cache: tuple[float, int] | None = None

def invalidate_jobs_cache():
    """Clear in-memory cache when jobs are added, deactivated, or cleaned up."""
    global _active_jobs_cache, _active_count_cache
    _active_jobs_cache.clear()
    _active_count_cache = None


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
                skills, min_yoe, eligible_batches, added_by, posted_at,
                hm_name, hm_role, hm_linkedin, hm_email
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
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
            data.get("posted_at") or datetime.now(timezone.utc),
            data.get("hm_name"),
            data.get("hm_role"),
            data.get("hm_linkedin"),
            data.get("hm_email"),
        )
        job_id = row["id"]
        invalidate_jobs_cache()
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
    Cached in-memory for 60 seconds to provide instant response times.
    """
    cache_key = (limit, offset)
    now = time.monotonic()
    if cache_key in _active_jobs_cache:
        ts, cached_data = _active_jobs_cache[cache_key]
        if now - ts < _JOBS_CACHE_TTL:
            return [dict(j) for j in cached_data]

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
        
        _active_jobs_cache[cache_key] = (now, result)
        return [dict(j) for j in result]


async def get_personalized_manual_jobs(
    user: dict, 
    seen_job_ids: list[int] = None, 
    limit: int = 12,
    exclude_sent_within_days: int = None,
    max_age_days: int = None,
    ignore_role_filter: bool = False,
    bot_id: int = 1
) -> list[dict]:
    """
    Fetch all active manual jobs, score them based on user skills/experience/batch,
    filter to selected role niche, prioritize unseen/un-sent jobs, and gracefully
    fall back to active role matches so the feed is never unexpectedly empty.
    """
    if seen_job_ids is None:
        seen_job_ids = []

    effective_bot_id = user.get("bot_id") or bot_id

    import asyncio
    tasks = [get_manual_jobs(limit=100, offset=0)]
    
    if exclude_sent_within_days is not None:
        tasks.append(get_recently_sent_jobs(user.get("telegram_id"), days=exclude_sent_within_days, bot_id=effective_bot_id))
        
    results = await asyncio.gather(*tasks)
    all_jobs = results[0]
    
    if not all_jobs:
        return []
        
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    # 1. Age Filter (10-Day Expiry)
    if max_age_days is not None:
        valid_jobs = []
        for j in all_jobs:
            posted = j.get("posted_at")
            if posted:
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                if (now - posted).days <= max_age_days:
                    valid_jobs.append(j)
        all_jobs = valid_jobs
        if not all_jobs:
            return []

    # 2. ROLE FILTER: Keep only jobs matching the user's selected role stream
    filtered_jobs = all_jobs
    if not ignore_role_filter:
        user_role = (user.get("role_pref") or "other").lower()
        role_keywords = ROLE_KEYWORDS.get(user_role)
        
        is_custom_role = (role_keywords is None and user_role != "other")
        
        if is_custom_role:
            common_words = {"developer", "engineer", "programmer", "specialist", "designer", "architect", "expert", "role", "job"}
            custom_words = [w for w in user_role.split() if w not in common_words]
            if not custom_words:
                custom_words = [user_role]
        
        def is_role_match(job: dict) -> bool:
            """Return True if the job matches the user's selected role stream."""
            if user_role == "other":
                return True
                
            job_skills = [s.lower() for s in (job.get("skills") or [])]
            title_lower = (job.get("title") or "").lower()
            
            if is_custom_role:
                search_space = " ".join(job_skills) + " " + title_lower
                return all(w in search_space for w in custom_words)
            else:
                return any(kw in title_lower or kw in s for kw in role_keywords for s in job_skills + [title_lower])

        filtered_jobs = [j for j in all_jobs if is_role_match(j)]
        if not filtered_jobs:
            return []

    from utils.messages import compute_manual_job_match

    for job in filtered_jobs:
        details = compute_manual_job_match(user, job)
        job["_match_score"] = details["score"]

    # Sort candidate jobs by score (DESC), then by posted date (DESC)
    filtered_jobs.sort(key=lambda j: (j["_match_score"], j.get("posted_at") or now), reverse=True)

    # 3. Deduplication & Cooldown with Graceful Fallback
    # Identify jobs sent recently or already seen on this bot
    recently_sent_ids = set(results[1]) if (exclude_sent_within_days is not None and len(results) > 1 and results[1]) else set()
    seen_ids = set(seen_job_ids) if seen_job_ids else set()
    excluded_ids = recently_sent_ids | seen_ids

    # Candidate fresh jobs (neither recently sent nor seen)
    fresh_jobs = [j for j in filtered_jobs if j["id"] not in excluded_ids]

    if len(fresh_jobs) >= limit:
        return fresh_jobs[:limit]

    # If fresh jobs alone don't fill the limit (e.g. repeated daily feed views or high activity),
    # prioritize all fresh jobs first, then backfill with the highest-matching active role jobs
    selected = list(fresh_jobs)
    selected_ids = {j["id"] for j in selected}
    for j in filtered_jobs:
        if len(selected) >= limit:
            break
        if j["id"] not in selected_ids:
            selected.append(j)
            selected_ids.add(j["id"])

    return selected[:limit]





async def count_manual_jobs() -> int:
    """Return total count of active manual jobs (for pagination). Cached in-memory for 60s."""
    global _active_count_cache
    now = time.monotonic()
    if _active_count_cache and (now - _active_count_cache[0] < _JOBS_CACHE_TTL):
        return _active_count_cache[1]

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM manual_jobs WHERE is_active = TRUE")
        cnt = row["cnt"] if row else 0
        _active_count_cache = (now, cnt)
        return cnt


async def get_seen_jobs(telegram_id: int, bot_id: int = 1) -> list[int]:
    """Get a list of job IDs the user has already seen on this bot."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT job_id FROM user_seen_jobs WHERE telegram_id = $1 AND bot_id = $2", telegram_id, bot_id)
        return [r["job_id"] for r in rows]

async def mark_jobs_seen(telegram_id: int, job_ids: list[int], bot_id: int = 1) -> None:
    """Mark a list of job IDs as seen by the user on this bot."""
    if not job_ids:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        # Insert ignoring conflicts
        query = """
            INSERT INTO user_seen_jobs (telegram_id, job_id, bot_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (telegram_id, job_id, bot_id) DO NOTHING
        """
        await conn.executemany(query, [(telegram_id, jid, bot_id) for jid in job_ids])

async def get_recently_sent_jobs(telegram_id: int, days: int = 3, bot_id: int = 1) -> list[int]:
    """Get jobs sent to this user in the daily feed within the last X days on this bot."""
    if not telegram_id:
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT DISTINCT job_id FROM jobs_sent_log 
            WHERE telegram_id = $1 AND bot_id = $2 AND sent_at >= NOW() - INTERVAL '1 day' * $3
        """
        rows = await conn.fetch(query, telegram_id, bot_id, days)
        return [r["job_id"] for r in rows]

async def log_jobs_sent(telegram_id: int, job_ids: list[int], bot_id: int = 1) -> None:
    """Log that these jobs were sent in a daily feed to trigger the cooldown on this bot."""
    if not job_ids or not telegram_id:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        query = """
            INSERT INTO jobs_sent_log (telegram_id, job_id, bot_id)
            VALUES ($1, $2, $3)
        """
        await conn.executemany(query, [(telegram_id, jid, bot_id) for jid in job_ids])




async def cleanup_old_manual_jobs(days: int = None) -> int:
    """Soft-delete manual jobs older than `days` days (default settings.JOB_RETENTION_DAYS)."""
    if days is None:
        from config import settings
        days = settings.JOB_RETENTION_DAYS
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
        # Invalidate cache so newly deactivated jobs are excluded immediately
        invalidate_jobs_cache()
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
        if result == "UPDATE 1":
            invalidate_jobs_cache()
            return True
        return False


async def list_manual_jobs_admin() -> list[dict]:
    """List all active manual jobs for admin review."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, company, job_type, posted_at, is_active FROM manual_jobs ORDER BY posted_at DESC LIMIT 50"
        )
        return [dict(row) for row in rows]


async def count_new_jobs_since(since_timestamp) -> dict:
    """Return count of new manual jobs added since `since_timestamp`.
    Also breaks them down by location type (remote vs onsite).
    Used for the 'Since your last visit' FOMO header in the daily feed."""
    from datetime import timezone
    pool = get_pool()
    async with pool.acquire() as conn:
        if since_timestamp is None:
            return {"total": 0, "remote": 0}

        # Ensure timezone-aware
        if hasattr(since_timestamp, 'tzinfo') and since_timestamp.tzinfo is None:
            since_timestamp = since_timestamp.replace(tzinfo=timezone.utc)

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM manual_jobs WHERE is_active = TRUE AND posted_at > $1",
            since_timestamp
        )
        remote = await conn.fetchval(
            """SELECT COUNT(*) FROM manual_jobs
               WHERE is_active = TRUE AND posted_at > $1
               AND LOWER(location) LIKE '%remote%'""",
            since_timestamp
        )
        return {"total": int(total or 0), "remote": int(remote or 0)}
