"""
User CRUD operations for PostgreSQL.
"""
from datetime import datetime, timezone
from loguru import logger
from db.connection import get_pool


async def get_or_create_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> dict:
    """Get existing user or create a new one. Returns user record as dict."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Try to get existing user
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1", telegram_id
        )
        if row:
            return dict(row)

        # Create new user
        row = await conn.fetchrow(
            """
            INSERT INTO users (telegram_id, username, first_name)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            telegram_id,
            username,
            first_name,
        )
        logger.info(f"New user created: {telegram_id} ({first_name})")
        return dict(row)


async def get_user(telegram_id: int) -> dict | None:
    """Get user by telegram_id. Returns None if not found."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1", telegram_id
        )
        return dict(row) if row else None


async def update_user_profile(
    telegram_id: int,
    skills: list[str] | None = None,
    location_pref: str | None = None,
    alert_time: str | None = None,
    experience_level: str | None = None,
    batch_year: int | None = None,
    role_pref: str | None = None,
) -> dict:
    """Update user profile fields. Only updates non-None values."""
    pool = get_pool()
    updates = []
    values = []
    param_idx = 1

    if skills is not None:
        param_idx += 1
        updates.append(f"skills = ${param_idx}")
        values.append(skills)

    if experience_level is not None:
        param_idx += 1
        updates.append(f"experience_level = ${param_idx}")
        values.append(experience_level)

    if role_pref is not None:
        param_idx += 1
        updates.append(f"role_pref = ${param_idx}")
        values.append(role_pref)

    if location_pref is not None:
        param_idx += 1
        updates.append(f"location_pref = ${param_idx}")
        values.append(location_pref)

    if alert_time is not None:
        param_idx += 1
        updates.append(f"alert_time = ${param_idx}")
        values.append(alert_time)

    if batch_year is not None:
        param_idx += 1
        updates.append(f"batch_year = ${param_idx}")
        values.append(batch_year)

    if not updates:
        return await get_user(telegram_id)

    updates.append("updated_at = NOW()")
    sql = f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = $1 RETURNING *"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, telegram_id, *values)
        return dict(row) if row else None


async def update_resume(
    telegram_id: int, resume_text: str, filename: str
) -> dict:
    """Store extracted resume text and filename."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET resume_text = $2, resume_filename = $3, updated_at = NOW()
            WHERE telegram_id = $1
            RETURNING *
            """,
            telegram_id,
            resume_text,
            filename,
        )
        return dict(row) if row else None


async def set_onboarded(telegram_id: int) -> None:
    """Mark user as having completed onboarding."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_onboarded = TRUE, updated_at = NOW() WHERE telegram_id = $1",
            telegram_id,
        )


async def increment_cover_letter_count(telegram_id: int) -> int:
    """Increment cover letter counter. Returns new count."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Check if monthly reset is needed
        user = await conn.fetchrow(
            "SELECT cover_letters_used, cover_letters_reset FROM users WHERE telegram_id = $1",
            telegram_id,
        )
        if user:
            reset_date = user["cover_letters_reset"]
            now = datetime.now(timezone.utc)
            if reset_date and (now.month != reset_date.month or now.year != reset_date.year):
                # New month — reset counter
                await conn.execute(
                    """
                    UPDATE users SET cover_letters_used = 0,
                    cover_letters_reset = NOW() WHERE telegram_id = $1
                    """,
                    telegram_id,
                )

        row = await conn.fetchrow(
            """
            UPDATE users
            SET cover_letters_used = cover_letters_used + 1, updated_at = NOW()
            WHERE telegram_id = $1
            RETURNING cover_letters_used
            """,
            telegram_id,
        )
        return row["cover_letters_used"] if row else 0

async def increment_cover_letters_today(telegram_id: int) -> int:
    """Increment daily cover letter counter. Returns new count."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET cover_letters_today = cover_letters_today + 1, updated_at = NOW()
            WHERE telegram_id = $1
            RETURNING cover_letters_today
            """,
            telegram_id,
        )
        return row["cover_letters_today"] if row else 0


async def increment_jobs_seen(telegram_id: int, count: int) -> int:
    """Increment daily jobs_seen_today. Returns new count."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET jobs_seen_today = jobs_seen_today + $2, updated_at = NOW()
            WHERE telegram_id = $1
            RETURNING jobs_seen_today
            """,
            telegram_id,
            count
        )
        return row["jobs_seen_today"] if row else 0





async def update_user_plan(
    telegram_id: int, plan: str, expires_at: datetime | None = None
) -> dict:
    """Update user subscription plan."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET plan = $2, plan_expires_at = $3, updated_at = NOW()
            WHERE telegram_id = $1
            RETURNING *
            """,
            telegram_id,
            plan,
            expires_at,
        )
        logger.info(f"User {telegram_id} upgraded to {plan}")
        return dict(row) if row else None


async def update_user_subscription(
    telegram_id: int, plan: str, expires_at: datetime | None,
    customer_id: str = None, subscription_id: str = None, status: str = 'active'
) -> dict:
    """Update user subscription and razorpay details."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET plan = $2, 
                plan_expires_at = COALESCE($3, plan_expires_at), 
                razorpay_customer_id = COALESCE($4, razorpay_customer_id),
                razorpay_subscription_id = COALESCE($5, razorpay_subscription_id),
                subscription_status = $6,
                is_trial = FALSE,
                updated_at = NOW()
            WHERE telegram_id = $1
            RETURNING *
            """,
            telegram_id, plan, expires_at, customer_id, subscription_id, status
        )
        logger.info(f"User {telegram_id} subscription updated to {status} (Plan: {plan})")
        return dict(row) if row else None


async def reset_monthly_counters() -> int:
    """Reset cover letter counters for all users. Returns count of users reset."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE users
            SET cover_letters_used = 0, cover_letters_reset = NOW()
            """
        )
        count = int(result.split()[-1])
        logger.info(f"Monthly counters reset for {count} users")
        return count





async def soft_delete_user(telegram_id: int) -> bool:
    """Soft delete user account to prevent trial abuse."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET is_deleted = TRUE WHERE telegram_id = $1", telegram_id
        )
        deleted = result == "UPDATE 1"
        if deleted:
            logger.info(f"User {telegram_id} soft deleted")
        return deleted

async def restore_user(telegram_id: int) -> bool:
    """Restore a soft-deleted user account."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET is_deleted = FALSE WHERE telegram_id = $1", telegram_id
        )
        restored = result == "UPDATE 1"
        if restored:
            logger.info(f"User {telegram_id} account restored")
        return restored


async def check_ats_limit(telegram_id: int, plan: str) -> tuple[bool, int]:
    """
    Check if user can run an ATS analysis.
    Free: 1/day. Pro: 5/day. Pro+: unlimited.
    Returns (can_run: bool, checks_used_today: int).
    """
    if plan in ("proplus", "premium"):
        return True, 0

    # Trial users get same ATS checks as Pro (5/day)
    daily_limit = 5 if plan in ("pro", "trial") else 1
    pool = get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ats_checks_today, ats_checks_reset FROM users WHERE telegram_id = $1",
            telegram_id
        )
        if not row:
            return True, 0

        from datetime import date
        today = date.today()
        reset_date = row["ats_checks_reset"]

        # Reset counter if it's a new day
        if reset_date is None or reset_date < today:
            await conn.execute(
                "UPDATE users SET ats_checks_today = 0, ats_checks_reset = $1 WHERE telegram_id = $2",
                today, telegram_id
            )
            return True, 0

        used = row["ats_checks_today"] or 0
        return used < daily_limit, used


async def increment_ats_check(telegram_id: int) -> None:
    """Increment user's daily ATS check counter."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET ats_checks_today = COALESCE(ats_checks_today, 0) + 1,
                ats_checks_reset = CURRENT_DATE
            WHERE telegram_id = $1
            """,
            telegram_id
        )


async def get_all_users() -> list[int]:
    """Return telegram_ids of all onboarded users (for broadcast)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT telegram_id FROM users WHERE is_onboarded = TRUE"
        )
        return [row["telegram_id"] for row in rows]


async def downgrade_expired_trials() -> None:
    """Downgrade users with expired trials back to the 'free' plan."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE users
            SET plan = 'free'
            WHERE plan = 'trial'
              AND is_trial = TRUE
              AND trial_expires_at <= NOW()
            """
        )
        # result is a string like 'UPDATE N'
        updated_count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
        if updated_count > 0:
            logger.info(f"Downgraded {updated_count} expired trials to free plan.")
