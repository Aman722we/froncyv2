"""
Froncy V2 — Safe Telegram Delivery Wrapper & Blocked User Defense (RFC-002).
Handles Telegram API rate limits, permanent block errors, and auto-pruning.
"""
import asyncio
from datetime import datetime, timezone
from loguru import logger
from telegram import Bot, Message
from telegram.error import Forbidden, RetryAfter, TelegramError
from db.connection import get_pool


async def safe_send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: str | None = None,
    reply_markup=None,
    disable_notification: bool = False,
    disable_web_page_preview: bool = True,
    bot_id: int = 1,
) -> Message | None:
    """
    Safely sends a message to a user.
    - Intercepts Forbidden errors ('bot was blocked by the user' / 'user is deactivated')
      and sets is_blocked = TRUE to immediately exclude the user from future queries.
    - Handles RetryAfter by waiting up to 5s and retrying once.
    - Never raises unhandled exceptions to the caller.
    """
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_notification=disable_notification,
            disable_web_page_preview=disable_web_page_preview,
        )
    except Forbidden as e:
        err_msg = str(e).lower()
        if "blocked by the user" in err_msg or "deactivated" in err_msg:
            logger.info(f"🚫 User {chat_id} blocked bot (or account deactivated). Marking is_blocked = TRUE.")
            await mark_user_blocked(chat_id)
        else:
            logger.warning(f"Forbidden error sending to {chat_id}: {e}")
        return None
    except RetryAfter as e:
        retry_secs = min(5, float(e.retry_after))
        logger.warning(f"Telegram Rate Limit hit for {chat_id}. Sleeping {retry_secs}s before retry...")
        await asyncio.sleep(retry_secs)
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_notification=disable_notification,
                disable_web_page_preview=disable_web_page_preview,
            )
        except Exception as retry_err:
            logger.error(f"Retry failed sending to {chat_id}: {retry_err}")
            return None
    except Exception as e:
        logger.warning(f"Failed to send message to {chat_id}: {e}")
        return None


async def mark_user_blocked(telegram_id: int) -> None:
    """Mark a user as blocked so they are excluded upstream from all scheduled loops."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET is_blocked = TRUE, blocked_at = NOW()
                WHERE telegram_id = $1
                """,
                telegram_id
            )
    except Exception as e:
        logger.error(f"Failed to mark user {telegram_id} as blocked: {e}")


async def mark_user_unblocked(telegram_id: int) -> None:
    """Restore a user's active status when they interact with the bot again."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET is_blocked = FALSE, blocked_at = NULL
                WHERE telegram_id = $1 AND is_blocked = TRUE
                """,
                telegram_id
            )
    except Exception as e:
        logger.error(f"Failed to unmark blocked user {telegram_id}: {e}")
