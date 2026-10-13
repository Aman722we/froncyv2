"""
/refer command handler.
Generates and shows the user's personal referral link with stats.
Supports both /refer command and menu_refer callback button.
"""
import html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import settings
from db.connection import get_pool
from services.referral_service import get_referral_stats, REFERRAL_BONUS_DAYS, REFERRAL_MAX_DAYS

BOT_USERNAME = "FroncyJobsBot"


async def _build_refer_message(user_id: int, bot_username: str, bot_id: int = 1) -> tuple[str, InlineKeyboardMarkup]:
    """Build the referral message and keyboard for a user."""
    pool = get_pool()
    stats = await get_referral_stats(user_id, pool, bot_id=bot_id)

    referrals_made = stats["referrals_made"]
    bonus_days     = stats["bonus_days_earned"]
    days_left_cap  = stats["days_until_cap"]
    at_cap         = stats["at_cap"]

    link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    if at_cap:
        cap_note = (
            f"🏆 You've reached the maximum <b>{REFERRAL_MAX_DAYS} bonus days</b>! "
            f"Great work spreading the word."
        )
    else:
        cap_note = (
            f"You can earn up to <b>{days_left_cap} more days</b> "
            f"({REFERRAL_MAX_DAYS} day max total)."
        )

    msg = (
        "🎁 <b>Refer a Friend — Earn Free Pro Days!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Share your personal link below. When a friend joins and <b>completes setup</b>, "
        f"you unlock <b>{REFERRAL_BONUS_DAYS} free Pro days</b> instantly!\n\n"
        f"⭐️ <b>What Pro Trial unlocks for you:</b>\n"
        f"  • 8 high-match jobs in your Daily Feed\n"
        f"  • Instant job alerts when new matches drop\n"
        f"  • Browse all active jobs with match scores & filters\n"
        f"  • AI Cover letters\n\n"
        f"🔗 <b>Your referral link:</b>\n"
        f"<code>{link}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Your Stats</b>\n"
        f"  • Friends referred : <b>{referrals_made}</b>\n"
        f"  • Bonus days earned: <b>{bonus_days}</b>\n"
        f"  {cap_note}\n\n"
        "💡 <i>Tap the link above to copy it, or tap the button below to share directly!</i>"
    )

    from urllib.parse import quote
    share_text = quote("Hey! Check out this bot to get instant job alerts and a curated daily tech job feed 🚀")
    share_url = f"https://t.me/share/url?url={quote(link)}&text={share_text}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 Share with Friends", url=share_url)],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
    ])

    return msg, kb


async def refer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /refer command."""
    user_id = update.effective_user.id
    bot_id = context.bot_data.get('bot_id', 1)
    username = context.bot.username
    if not username:
        try:
            me = await context.bot.get_me()
            username = me.username
        except Exception:
            username = BOT_USERNAME
    msg, kb = await _build_refer_message(user_id, username, bot_id=bot_id)
    await update.message.reply_text(
        msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb
    )


async def refer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu_refer callback from main menu button."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    bot_id = context.bot_data.get('bot_id', 1)
    username = context.bot.username
    if not username:
        try:
            me = await context.bot.get_me()
            username = me.username
        except Exception:
            username = BOT_USERNAME
    msg, kb = await _build_refer_message(user_id, username, bot_id=bot_id)
    await query.edit_message_text(
        msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb
    )
