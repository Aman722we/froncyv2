"""
Job CRUD operations — upsert, matching, bookmarking, and application logging.
"""
import hashlib
from datetime import datetime, timezone
from loguru import logger
from db.connection import get_pool


def hash_url(url: str) -> str:
    """Generate MD5 hash of a URL for deduplication."""
    return hashlib.md5(url.strip().lower().encode()).hexdigest()


async def upsert_jobs(jobs_list: list[dict]) -> int:
    """
    Bulk upsert jobs with dedup on url_hash.
    Each job dict: {title, company, url, location, salary, skills, source, portal_type, posted_at}
    Returns number of new jobs inserted.
    """
    if not jobs_list:
        return 0

    pool = get_pool()
    inserted = 0

    async with pool.acquire() as conn:
        for job in jobs_list:
            url_h = hash_url(job["url"])
            try:
                result = await conn.execute(
                    """
                    INSERT INTO jobs (url_hash, title, company, url, location, salary, skills, experience_required, job_type, duration, source, portal_type, posted_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (url_hash) DO UPDATE SET
                        is_active = TRUE,
                        scraped_at = NOW()
                    """,
                    url_h,
                    job.get("title", "Untitled"),
                    job.get("company"),
                    job["url"],
                    job.get("location"),
                    job.get("salary"),
                    job.get("skills", []),
                    job.get("experience_required"),
                    job.get("job_type", "full-time"),
                    job.get("duration"),
                    job.get("source"),
                    job.get("portal_type", "other"),
                    job.get("posted_at"),
                )
                if "INSERT" in result:
                    inserted += 1
            except Exception as e:
                logger.error(f"Failed to upsert job: {job.get('title')} — {e}")

    logger.info(f"Upserted {len(jobs_list)} jobs, {inserted} new")
    return inserted


async def get_matching_jobs(
    skills: list[str],
    location: str = "remote",
    limit: int = 5,
    offset: int = 0,
    telegram_id: int | None = None,
) -> list[dict]:
    """
    Get jobs matching user skills and location preference.
    Excludes jobs the user has already applied to.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Build location filter
        location_filter = ""
        if location == "remote":
            location_filter = "AND (LOWER(location) LIKE '%remote%' OR location IS NULL)"
        elif location == "india":
            location_filter = "AND (LOWER(location) LIKE '%india%' OR LOWER(location) LIKE '%bangalore%' OR LOWER(location) LIKE '%mumbai%' OR LOWER(location) LIKE '%delhi%' OR LOWER(location) LIKE '%hyderabad%' OR LOWER(location) LIKE '%pune%' OR LOWER(location) LIKE '%chennai%' OR LOWER(location) LIKE '%remote%' OR location IS NULL)"
        # 'both' = no location filter

        # Exclude already-applied jobs if we have user context
        applied_filter = ""
        if telegram_id:
            applied_filter = f"AND id NOT IN (SELECT job_id FROM applications WHERE telegram_id = {telegram_id})"

        # Convert skills to lowercase for matching and normalize
        skills_lower = []
        if skills:
            for s in skills:
                sl = s.lower()
                if sl == "next.js": sl = "nextjs"
                skills_lower.append(sl)

        if skills_lower:
            rows = await conn.fetch(
                f"""
                SELECT * FROM jobs
                WHERE is_active = TRUE
                AND skills && $1::text[]
                {location_filter}
                {applied_filter}
                ORDER BY scraped_at DESC, id DESC
                LIMIT $2 OFFSET $3
                """,
                skills_lower,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT * FROM jobs
                WHERE is_active = TRUE
                {location_filter}
                {applied_filter}
                ORDER BY scraped_at DESC, id DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )

        return [dict(row) for row in rows]


async def count_matching_jobs(skills: list[str], location: str = "remote", telegram_id: int | None = None) -> int:
    """Count total matching jobs for display, excluding already-applied ones."""
    pool = get_pool()
    async with pool.acquire() as conn:
        skills_lower = []
        if skills:
            for s in skills:
                sl = s.lower()
                if sl == "next.js": sl = "nextjs"
                skills_lower.append(sl)

        location_filter = ""
        if location == "remote":
            location_filter = "AND (LOWER(location) LIKE '%remote%' OR location IS NULL)"
        elif location == "india":
            location_filter = "AND (LOWER(location) LIKE '%india%' OR LOWER(location) LIKE '%bangalore%' OR LOWER(location) LIKE '%mumbai%' OR LOWER(location) LIKE '%delhi%' OR LOWER(location) LIKE '%hyderabad%' OR LOWER(location) LIKE '%pune%' OR LOWER(location) LIKE '%chennai%' OR LOWER(location) LIKE '%remote%' OR location IS NULL)"

        applied_filter = ""
        if telegram_id:
            applied_filter = f"AND id NOT IN (SELECT job_id FROM applications WHERE telegram_id = {telegram_id})"

        if skills_lower:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) as cnt FROM jobs WHERE is_active = TRUE AND skills && $1::text[] {location_filter} {applied_filter}",
                skills_lower,
            )
        else:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) as cnt FROM jobs WHERE is_active = TRUE {location_filter} {applied_filter}"
            )
        return row["cnt"] if row else 0


async def get_job_by_id(job_id: int) -> dict | None:
    """Get a single job by its ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
        return dict(row) if row else None


async def save_job(telegram_id: int, job_id: int) -> bool:
    """Bookmark a job for a user. Returns True if saved, False if already saved."""
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO saved_jobs (telegram_id, job_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                telegram_id,
                job_id,
            )
            return True
        except Exception as e:
            logger.error(f"Save job error: {e}")
            return False


async def unsave_job(telegram_id: int, job_id: int) -> bool:
    """Remove a bookmark."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM saved_jobs WHERE telegram_id = $1 AND job_id = $2",
            telegram_id,
            job_id,
        )
        return result == "DELETE 1"


async def save_manual_job(telegram_id: int, manual_job_id: int) -> bool:
    """Bookmark a manual job. Returns True if saved, False if already saved."""
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO saved_jobs (telegram_id, manual_job_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                telegram_id,
                manual_job_id,
            )
            return True
        except Exception as e:
            logger.error(f"Save manual job error: {e}")
            return False


async def unsave_manual_job(telegram_id: int, manual_job_id: int) -> bool:
    """Remove a manual job bookmark."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM saved_jobs WHERE telegram_id = $1 AND manual_job_id = $2",
            telegram_id,
            manual_job_id,
        )
        return result == "DELETE 1"


async def get_saved_jobs(telegram_id: int) -> list[dict]:
    """Get all saved/bookmarked jobs for a user (both scraped and manual)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Scraped jobs
        scraped_rows = await conn.fetch(
            """
            SELECT j.*, sj.saved_at, FALSE AS is_manual
            FROM saved_jobs sj
            JOIN jobs j ON sj.job_id = j.id
            WHERE sj.telegram_id = $1 AND sj.job_id IS NOT NULL
            ORDER BY sj.saved_at DESC
            """,
            telegram_id,
        )
        # Manual jobs
        manual_rows = await conn.fetch(
            """
            SELECT mj.*, sj.saved_at, TRUE AS is_manual
            FROM saved_jobs sj
            JOIN manual_jobs mj ON sj.manual_job_id = mj.id
            WHERE sj.telegram_id = $1 AND sj.manual_job_id IS NOT NULL
            ORDER BY sj.saved_at DESC
            """,
            telegram_id,
        )
        combined = [dict(r) for r in scraped_rows] + [dict(r) for r in manual_rows]
        combined.sort(key=lambda x: x["saved_at"], reverse=True)
        return combined


async def log_application(
    telegram_id: int, job_id: int, status: str, portal_type: str = None, error_msg: str = None
) -> int:
    """Log an auto-apply attempt. Returns application ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO applications (telegram_id, job_id, status, portal_type, error_msg)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            telegram_id,
            job_id,
            status,
            portal_type,
            error_msg,
        )
        return row["id"] if row else 0


async def deactivate_old_jobs(days: int = 30) -> int:
    """Mark jobs older than N days as inactive."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE jobs SET is_active = FALSE
            WHERE scraped_at < NOW() - INTERVAL '1 day' * $1
            AND is_active = TRUE
            """,
            days,
        )
        count = int(result.split()[-1])
        logger.info(f"Deactivated {count} old jobs (>{days} days)")
        return count


async def get_users_with_saved_jobs() -> list[dict]:
    """Return all users who have at least one saved job.
    Used by the daily 6:30 PM reminder scheduler."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT sj.telegram_id
            FROM saved_jobs sj
            JOIN users u ON sj.telegram_id = u.telegram_id
            WHERE u.is_onboarded = TRUE
            AND (u.is_deleted IS NULL OR u.is_deleted = FALSE)
            """
        )
        return [dict(r) for r in rows]
