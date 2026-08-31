"""
db/bots.py -- Multi-Tenant Bot Registry (Database Layer)

Each row in the `bots` table represents one Guru's Telegram bot.
This module provides CRUD operations for the bots table.
"""
from loguru import logger
from db.connection import get_pool


async def get_all_active_bots() -> list[dict]:
    """Fetch all active bot configurations from the DB (used at startup)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM bots WHERE is_active = TRUE ORDER BY id ASC"
        )
        return [dict(r) for r in rows]


async def get_bot_by_token(token: str) -> dict | None:
    """Look up a bot configuration by its Telegram token."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bots WHERE bot_token = $1 AND is_active = TRUE", token
        )
        return dict(row) if row else None


async def get_bot_by_id(bot_id: int) -> dict | None:
    """Look up a bot configuration by its internal integer ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bots WHERE id = $1", bot_id
        )
        return dict(row) if row else None


async def register_bot(
    bot_token: str,
    bot_username: str,
    guru_name: str,
    split_percentage: int = 50,
    razorpay_account_id: str = "",
) -> dict:
    """Register a new Guru bot in the database. Returns the new row."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO bots (bot_token, bot_username, guru_name, split_percentage, razorpay_account_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (bot_token) DO UPDATE
              SET guru_name = EXCLUDED.guru_name,
                  split_percentage = EXCLUDED.split_percentage,
                  is_active = TRUE
            RETURNING *
            """,
            bot_token, bot_username, guru_name, split_percentage, razorpay_account_id
        )
        return dict(row)


async def deactivate_bot(bot_token: str) -> bool:
    """Soft-delete a bot (set is_active = FALSE). Returns True if found."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE bots SET is_active = FALSE WHERE bot_token = $1", bot_token
        )
        return result.endswith("1")


async def set_guru_telegram_id(bot_id: int, guru_telegram_id: int) -> bool:
    """Link a Guru's personal Telegram ID to their bot so they can access the dashboard."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE bots SET guru_telegram_id = $1 WHERE id = $2",
            guru_telegram_id, bot_id
        )
        return result.endswith("1")


async def is_guru_of_bot(telegram_id: int, bot_id: int) -> bool:
    """Check if the given telegram_id is the registered Guru for this bot."""
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT 1 FROM bots WHERE id = $1 AND guru_telegram_id = $2 AND is_active = TRUE",
            bot_id, telegram_id
        )
        return val is not None


async def get_guru_stats(bot_id: int) -> dict:
    """
    Return analytics stats for a Guru's bot audience.
    Used by the /guruanalytics command to build the Guru Dashboard.
    
    Also calculates the Estimated Monthly Payout by reading:
      - Pro user count (from users table, scoped to bot_id)
      - Current price (from pricing_config)
      - Guru's split % (from bots table)
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # ── User counts (all scoped to this bot's audience) ────────────────────
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                                        AS total_users,
                COUNT(*) FILTER (WHERE is_onboarded = TRUE)                    AS onboarded_users,
                COUNT(*) FILTER (WHERE resume_text IS NOT NULL)                 AS with_resume,
                COUNT(*) FILTER (WHERE plan = 'free'
                                   AND (is_trial IS NOT TRUE
                                        OR trial_expires_at < NOW()))           AS free_users,
                COUNT(*) FILTER (WHERE is_trial = TRUE
                                   AND trial_expires_at > NOW())                AS trial_users,
                COUNT(*) FILTER (WHERE plan = 'pro')                            AS pro_users
            FROM users
            WHERE bot_id = $1
              AND (is_deleted IS NOT TRUE)
            """,
            bot_id
        )

        # ── Bot config (split %) ───────────────────────────────────────────────
        bot_cfg = await conn.fetchrow(
            "SELECT guru_name, split_percentage FROM bots WHERE id = $1", bot_id
        )

        # ── Current pro price from pricing_config ─────────────────────────────
        pricing = await conn.fetchrow(
            "SELECT early_adopter_price, regular_price, early_adopter_active FROM pricing_config LIMIT 1"
        )

    stats = dict(row)

    # ── Payout calculation ─────────────────────────────────────────────────────
    split_pct     = (bot_cfg["split_percentage"] if bot_cfg else 50) / 100
    is_early      = pricing["early_adopter_active"] if pricing else False
    current_price = pricing["early_adopter_price"] if (pricing and is_early) else (pricing["regular_price"] if pricing else 199)
    pro_count     = stats["pro_users"] or 0

    total_revenue  = pro_count * current_price          # e.g. 10 * 199 = 1990
    guru_payout    = total_revenue * split_pct          # e.g. 1990 * 0.50 = 995.0

    stats["guru_name"]       = bot_cfg["guru_name"] if bot_cfg else "Guru"
    stats["split_pct"]       = int(split_pct * 100)
    stats["current_price"]   = current_price
    stats["total_revenue"]   = total_revenue
    stats["guru_payout"]     = guru_payout              # exact float, no rounding

    return stats
