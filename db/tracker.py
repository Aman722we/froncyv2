from loguru import logger
from db.connection import get_pool
from datetime import datetime
import json

async def add_application(telegram_id: int, job_id: int) -> bool:
    """Add a job to applications. Return True if added, False if already exists."""
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            # Check if already tracked
            existing = await conn.fetchval(
                "SELECT id FROM applications WHERE telegram_id = $1 AND job_id = $2",
                telegram_id, job_id
            )
            if existing:
                return False

            # Insert the application
            app_id = await conn.fetchval(
                """
                INSERT INTO applications (telegram_id, job_id, status)
                VALUES ($1, $2, 'applied')
                RETURNING id
                """,
                telegram_id,
                job_id
            )

            # Schedule a follow-up reminder 3 days from now
            try:
                await conn.execute(
                    """
                    INSERT INTO reminders (telegram_id, application_id, remind_at, reminder_type)
                    VALUES ($1, $2, NOW() + INTERVAL '3 days', 'followup')
                    """,
                    telegram_id,
                    app_id
                )
            except Exception as e:
                logger.warning(f"Could not create reminder (non-critical): {e}")

            return True
        except Exception as e:
            logger.error(f"Error adding application: {e}")
            return False

async def get_applications(telegram_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
    """Get active applications for a user with job details."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id as app_id, a.status, a.applied_at,
                   j.id as job_id, j.title, j.company, j.location, j.url
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.telegram_id = $1
            ORDER BY a.applied_at DESC
            LIMIT $2 OFFSET $3
            """,
            telegram_id, limit, offset
        )
        return [dict(r) for r in rows]

async def count_applications(telegram_id: int) -> int:
    """Total applications count."""
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT count(*) FROM applications WHERE telegram_id = $1",
            telegram_id
        )
        return val or 0

async def get_weekly_stats(telegram_id: int) -> dict:
    """Get statistics for the past 7 days."""
    pool = get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT count(*) FROM applications 
            WHERE telegram_id = $1 
            AND applied_at >= NOW() - INTERVAL '7 days'
            """,
            telegram_id
        )
        return {"weekly_apps": count or 0}

async def update_application_status(telegram_id: int, app_id: int, new_status: str) -> bool:
    """Update status of a tracked application."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE applications SET status = $1 WHERE id = $2 AND telegram_id = $3",
            new_status, app_id, telegram_id
        )
        return result == "UPDATE 1"

async def log_ai_usage(telegram_id: int, feature_type: str) -> None:
    """Log a single AI feature use event (cover_letter or ats_check)."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO ai_usage_logs (telegram_id, feature_type) VALUES ($1, $2)",
                telegram_id, feature_type
            )
    except Exception as e:
        logger.warning(f"Could not log AI usage (non-critical): {e}")


async def get_ai_usage_stats() -> dict:
    """Get cover letter and ATS check counts: today, this week, this month, total."""
    pool = get_pool()
    async with pool.acquire() as conn:
        for feature in ("cover_letter", "ats_check"):
            pass  # Pre-warm

        rows = await conn.fetch(
            """
            SELECT
                feature_type,
                COUNT(*) FILTER (WHERE created_at >= NOW() AT TIME ZONE 'UTC' - INTERVAL '1 day' 
                                  AND created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC'))
                    AS today,
                COUNT(*) FILTER (WHERE created_at >= NOW() AT TIME ZONE 'UTC' - INTERVAL '7 days') AS week,
                COUNT(*) FILTER (WHERE created_at >= NOW() AT TIME ZONE 'UTC' - INTERVAL '30 days') AS month,
                COUNT(*) AS total
            FROM ai_usage_logs
            GROUP BY feature_type
            """
        )

    result = {
        "cover_letter": {"today": 0, "week": 0, "month": 0, "total": 0},
        "ats_check":    {"today": 0, "week": 0, "month": 0, "total": 0},
    }
    for row in rows:
        ft = row["feature_type"]
        if ft in result:
            result[ft] = {
                "today": row["today"],
                "week":  row["week"],
                "month": row["month"],
                "total": row["total"],
            }
    return result


async def get_application_funnel_stats() -> dict:
    """Get counts of all application statuses across all users (admin view)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM applications")
        rows = await conn.fetch(
            "SELECT status, COUNT(*) AS cnt FROM applications GROUP BY status"
        )
    stats = {"total": total or 0, "applied": 0, "interviewing": 0, "rejected": 0, "offer": 0}
    for row in rows:
        s = row["status"]
        if s in stats:
            stats[s] = row["cnt"]
    return stats


async def get_application_by_id(telegram_id: int, app_id: int) -> dict | None:

    """Get a specific application for managing."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT a.id as app_id, a.status, a.applied_at,
                   j.id as job_id, j.title, j.company, j.location, j.url
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.telegram_id = $1 AND a.id = $2
            """,
            telegram_id, app_id
        )
        return dict(row) if row else None
