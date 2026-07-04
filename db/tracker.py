from loguru import logger
from db.connection import get_pool
from datetime import datetime
import json

async def add_application(telegram_id: int, job_id: int) -> bool:
    """Add a job to applications. Return True if added, False if already exists.
    Auto-removes the job from saved_jobs if it was saved there."""
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

            # Auto-cleanup: remove from saved_jobs (both scraped and manual)
            try:
                await conn.execute(
                    "DELETE FROM saved_jobs WHERE telegram_id = $1 AND job_id = $2",
                    telegram_id, job_id
                )
                await conn.execute(
                    "DELETE FROM saved_jobs WHERE telegram_id = $1 AND manual_job_id = $2",
                    telegram_id, job_id
                )
            except Exception as e:
                logger.warning(f"Could not auto-remove from saved_jobs (non-critical): {e}")

            return True
        except Exception as e:
            logger.error(f"Error adding application: {e}")
            return False

async def get_applications(telegram_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
    """Get applications for a user — covers both scraped jobs and manual jobs."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id as app_id, a.status, a.applied_at,
                   j.id as job_id, j.title, j.company, j.location, j.url
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.telegram_id = $1

            UNION ALL

            SELECT a.id as app_id, a.status, a.applied_at,
                   mj.id as job_id, mj.title, mj.company, mj.location, mj.url
            FROM applications a
            JOIN manual_jobs mj ON a.job_id = mj.id
            WHERE a.telegram_id = $1

            ORDER BY applied_at DESC
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
            
            UNION ALL
            
            SELECT a.id as app_id, a.status, a.applied_at,
                   mj.id as job_id, mj.title, mj.company, mj.location, mj.url
            FROM applications a
            JOIN manual_jobs mj ON a.job_id = mj.id
            WHERE a.telegram_id = $1 AND a.id = $2
            """,
            telegram_id, app_id
        )
        return dict(row) if row else None


# ─────────────────────────────────────────────
# Retention & Activity Tracking
# ─────────────────────────────────────────────

async def log_daily_active(telegram_id: int) -> None:
    """
    Silently mark a user as active today.
    Uses INSERT ... ON CONFLICT DO NOTHING so it is safe to call on every
    single bot interaction without creating duplicates.
    """
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO daily_active_users (telegram_id, active_date)
                VALUES ($1, CURRENT_DATE)
                ON CONFLICT (telegram_id, active_date) DO NOTHING
                """,
                telegram_id
            )
    except Exception as e:
        logger.warning(f"Could not log daily active (non-critical): {e}")


async def log_link_click(telegram_id: int, job_id: int | None) -> None:
    """Log an Apply/Open Link click for a job."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO link_clicks (telegram_id, job_id) VALUES ($1, $2)",
                telegram_id, job_id
            )
    except Exception as e:
        logger.warning(f"Could not log link click (non-critical): {e}")


async def get_retention_stats() -> dict:
    """
    Calculate DAU, WAU, returning users, and cohort-based D7/D30 retention.
    D7 = what % of users who joined exactly 7 days ago are active today.
    D30 = what % of users who joined exactly 30 days ago are active today.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        dau = await conn.fetchval(
            "SELECT COUNT(DISTINCT telegram_id) FROM daily_active_users WHERE active_date = CURRENT_DATE"
        )
        wau = await conn.fetchval(
            "SELECT COUNT(DISTINCT telegram_id) FROM daily_active_users WHERE active_date >= CURRENT_DATE - INTERVAL '7 days'"
        )
        returning = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT telegram_id) FROM daily_active_users
            WHERE active_date = CURRENT_DATE
              AND telegram_id IN (
                  SELECT telegram_id FROM daily_active_users
                  WHERE active_date < CURRENT_DATE
              )
            """
        )
        d7_cohort_total = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE created_at::date = CURRENT_DATE - INTERVAL '7 days' AND is_deleted IS NOT TRUE"
        )
        d7_cohort_active = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT telegram_id) FROM daily_active_users
            WHERE active_date = CURRENT_DATE
              AND telegram_id IN (
                  SELECT telegram_id FROM users
                  WHERE created_at::date = CURRENT_DATE - INTERVAL '7 days'
              )
            """
        )
        d30_cohort_total = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE created_at::date = CURRENT_DATE - INTERVAL '30 days' AND is_deleted IS NOT TRUE"
        )
        d30_cohort_active = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT telegram_id) FROM daily_active_users
            WHERE active_date = CURRENT_DATE
              AND telegram_id IN (
                  SELECT telegram_id FROM users
                  WHERE created_at::date = CURRENT_DATE - INTERVAL '30 days'
              )
            """
        )

    def pct(active, total):
        if not total:
            return "N/A (no cohort yet)"
        return f"{round((active / total) * 100)}%  ({active}/{total})"

    return {
        "dau":       dau or 0,
        "wau":       wau or 0,
        "returning": returning or 0,
        "d7":        pct(d7_cohort_active, d7_cohort_total),
        "d30":       pct(d30_cohort_active, d30_cohort_total),
    }


async def get_click_stats() -> dict:
    """Get job link click counts: today, this week, this month, total."""
    pool = get_pool()
    async with pool.acquire() as conn:
        today = await conn.fetchval(
            "SELECT COUNT(*) FROM link_clicks WHERE clicked_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')"
        )
        week = await conn.fetchval(
            "SELECT COUNT(*) FROM link_clicks WHERE clicked_at >= NOW() - INTERVAL '7 days'"
        )
        month = await conn.fetchval(
            "SELECT COUNT(*) FROM link_clicks WHERE clicked_at >= NOW() - INTERVAL '30 days'"
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM link_clicks")

    return {
        "today": today or 0,
        "week":  week  or 0,
        "month": month or 0,
        "total": total or 0,
    }


async def get_weekly_scorecard(telegram_id: int) -> dict:
    """Return this week's activity stats for a user.
    Used by the Friday Scorecard digest.
    Returns: jobs_viewed, jobs_saved, jobs_applied this week."""
    pool = get_pool()
    async with pool.acquire() as conn:
        jobs_viewed = await conn.fetchval(
            """SELECT COUNT(*) FROM user_seen_jobs
               WHERE telegram_id = $1 AND seen_at >= NOW() - INTERVAL '7 days'""",
            telegram_id
        ) or 0

        jobs_saved = await conn.fetchval(
            """SELECT COUNT(*) FROM saved_jobs
               WHERE telegram_id = $1 AND saved_at >= NOW() - INTERVAL '7 days'""",
            telegram_id
        ) or 0

        jobs_applied = await conn.fetchval(
            """SELECT COUNT(*) FROM applications
               WHERE telegram_id = $1 AND applied_at >= NOW() - INTERVAL '7 days'""",
            telegram_id
        ) or 0

    return {
        "viewed":  int(jobs_viewed),
        "saved":   int(jobs_saved),
        "applied": int(jobs_applied),
    }


async def get_due_followups(telegram_id: int) -> list[dict]:
    """Return all follow-up reminders due today for this user (sent=FALSE).
    Used by the 6:30 PM evening consolidation digest."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.id, r.application_id,
                   COALESCE(j.title,  mj.title)   AS title,
                   COALESCE(j.company, mj.company) AS company,
                   a.applied_at
            FROM reminders r
            JOIN applications a ON r.application_id = a.id
            LEFT JOIN jobs j       ON a.job_id = j.id
            LEFT JOIN manual_jobs mj ON a.job_id = mj.id
            WHERE r.telegram_id = $1
              AND r.sent = FALSE
              AND r.remind_at <= NOW()
            ORDER BY r.remind_at
            """,
            telegram_id
        )
        return [dict(r) for r in rows]


async def mark_reminders_sent(reminder_ids: list[int]) -> None:
    """Mark a list of reminder IDs as sent."""
    if not reminder_ids:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reminders SET sent = TRUE WHERE id = ANY($1::int[])",
            reminder_ids
        )
