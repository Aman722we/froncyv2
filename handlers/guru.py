"""
handlers/guru.py -- Guru Dashboard

Commands accessible to the Guru (the influencer who owns the bot).
The Guru is identified by their telegram_id stored in bots.guru_telegram_id.

Commands:
  /guruanalytics  -- Read-only audience stats + estimated monthly payout
  /gurubcast       -- Broadcast a message to their bot's audience only
  /guruhelp        -- Show all available Guru commands
"""
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import Forbidden, RetryAfter
from loguru import logger

from config import settings
from db.bots import is_guru_of_bot, get_guru_stats
from db.users import get_all_users


async def _check_guru_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Guard function: returns bot_id if the user is an authorised Guru OR the super admin.
    Returns None and replies with an error if access is denied.
    """
    user_id = update.effective_user.id
    bot_id  = context.bot_data.get("bot_id", 1)

    # Super admin always has access
    if user_id == settings.ADMIN_TELEGRAM_ID:
        return bot_id

    # Check if the user is the registered Guru for this specific bot
    if await is_guru_of_bot(user_id, bot_id):
        return bot_id

    # Silently ignore -- do not reveal that these commands exist
    return None


async def guruhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/guruhelp -- List all commands available to the Guru."""
    bot_id = await _check_guru_access(update, context)
    if bot_id is None:
        return

    await update.message.reply_text(
        "🎛️ <b>Your Guru Dashboard Commands</b>\n\n"
        "/guruanalytics — View your audience stats and estimated payout\n"
        "/gurubcast &lt;message&gt; — Send a message to all your bot's users\n"
        "/guruhelp — Show this help menu",
        parse_mode="HTML",
    )


async def guruanalytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/guruanalytics -- Show read-only audience stats + estimated monthly payout."""
    bot_id = await _check_guru_access(update, context)
    if bot_id is None:
        return

    await update.message.reply_text("⏳ Fetching your dashboard...", parse_mode="HTML")

    try:
        stats = await get_guru_stats(bot_id)
    except Exception as e:
        logger.error(f"get_guru_stats failed for bot_id={bot_id}: {e}")
        await update.message.reply_text("❌ Could not load stats. Try again in a moment.")
        return

    guru_name      = stats.get("guru_name", "Guru")
    total          = stats.get("total_users", 0)
    onboarded      = stats.get("onboarded_users", 0)
    with_resume    = stats.get("with_resume", 0)
    free_users     = stats.get("free_users", 0)
    trial_users    = stats.get("trial_users", 0)
    pro_users      = stats.get("pro_users", 0)
    split_pct      = stats.get("split_pct", 50)
    current_price  = stats.get("current_price", 199)
    total_revenue  = stats.get("total_revenue", 0)
    guru_payout    = stats.get("guru_payout", 0.0)

    # Format payout (exact, no rounding as requested)
    payout_str = f"₹{guru_payout:.2f}" if guru_payout != int(guru_payout) else f"₹{int(guru_payout)}"

    msg = (
        f"📊 <b>{guru_name} — Audience Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 <b>Users</b>\n"
        f"  • Total registered  : <b>{total}</b>\n"
        f"  • Completed setup   : <b>{onboarded}</b>\n"
        f"  • Uploaded resume   : <b>{with_resume}</b>\n\n"
        "💳 <b>Plan Breakdown</b>\n"
        f"  • Free              : <b>{free_users}</b>\n"
        f"  • Trial             : <b>{trial_users}</b>\n"
        f"  • Pro               : <b>{pro_users}</b>\n\n"
        "💰 <b>Revenue (This Month)</b>\n"
        f"  • Pro price         : ₹{current_price}/mo\n"
        f"  • Total generated   : ₹{total_revenue}\n"
        f"  • Your share ({split_pct}%) : <b>{payout_str}</b>\n\n"
        "<i>Payout is transferred at the end of each month.</i>"
    )

    await update.message.reply_text(msg, parse_mode="HTML")


async def gurubcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/gurubcast <message> -- Broadcast to all users of this Guru's bot."""
    bot_id = await _check_guru_access(update, context)
    if bot_id is None:
        return

    if not context.args:
        await update.message.reply_text(
            "📢 <b>Usage:</b> /gurubcast &lt;message&gt;\n\n"
            "Example:\n"
            "<code>/gurubcast 🎬 New React tutorial just dropped! Check it out now.</code>\n\n"
            "Your message will be sent to <b>all users of your bot</b>.",
            parse_mode="HTML",
        )
        return

    message_text = " ".join(context.args)
    all_user_ids = await get_all_users(bot_id=bot_id)

    if not all_user_ids:
        await update.message.reply_text("❌ No users have joined your bot yet.")
        return

    status_msg = await update.message.reply_text(
        f"📢 Sending to <b>{len(all_user_ids)}</b> users...",
        parse_mode="HTML",
    )

    sent    = 0
    failed  = 0
    blocked = 0

    for tid in all_user_ids:
        try:
            await context.bot.send_message(chat_id=tid, text=message_text)
            sent += 1
            await asyncio.sleep(0.05)  # Stay within Telegram's 20 msg/sec limit
        except Forbidden:
            blocked += 1
        except RetryAfter as e:
            logger.warning(f"Guru broadcast rate-limited, sleeping {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            try:
                await context.bot.send_message(chat_id=tid, text=message_text)
                sent += 1
            except Exception:
                failed += 1
        except Exception as e:
            logger.warning(f"Guru broadcast failed for {tid}: {e}")
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>Broadcast complete!</b>\n\n"
        f"📨 Sent    : <b>{sent}</b>\n"
        f"🚫 Blocked : <b>{blocked}</b>\n"
        f"❌ Failed  : <b>{failed}</b>",
        parse_mode="HTML",
    )
    logger.info(f"Guru broadcast (bot_id={bot_id}) done. Sent={sent}, Blocked={blocked}, Failed={failed}")
