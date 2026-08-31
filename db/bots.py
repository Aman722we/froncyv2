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
