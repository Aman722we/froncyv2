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


async def _build_refer_message(user_id: int, bot_username: str, bot_id: int = 1, bot_name: str = "Froncy") -> tuple[str, InlineKeyboardMarkup]:
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
        "🎁 <b>Refer a Friend (Earn 5 Free Pro Days!)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Know someone planning a job switch?\n\n"
        f"Share {bot_name} with them. When they join and complete their setup, you unlock <b>5 free Pro days!</b>\n\n"
        "⭐️ <b>What Pro unlocks:</b>\n\n"
        "• 8 personalised, high-match jobs in your Daily Feed\n"
        "• Telegram alerts for new matching opportunities\n"
        "• Jobs discovered directly from 530+ company career pages\n"
        "• Full job match scores and skill-gap analysis\n"
        "• Browse active jobs with advanced filters\n"
        "• Track companies you specifically want to join\n\n"
        f"💡 Keep using LinkedIn and Naukri. {bot_name} gives you an additional source of relevant opportunities, delivered directly to Telegram.\n\n"
        "🔗 <b>Your referral link:</b>\n"
        f"<code>{link}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Your Stats</b>\n\n"
        f"• Friends referred: <b>{referrals_made}</b>\n"
        f"• Bonus days earned: <b>{bonus_days}</b>\n\n"
        f"Earn up to {REFERRAL_MAX_DAYS} free Pro days!\n\n"
        "💡 <i>Share your link with friends who are planning their next career move.</i>"
    )

    from urllib.parse import quote
    share_text = quote(f"Hey! Check out {bot_name} to get instant alerts directly from 530+ company career pages 🚀")
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
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    if not username:
        try:
            me = await context.bot.get_me()
            username = me.username
        except Exception:
            username = BOT_USERNAME
    msg, kb = await _build_refer_message(user_id, username, bot_id=bot_id, bot_name=bot_name)
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
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    if not username:
        try:
            me = await context.bot.get_me()
            username = me.username
        except Exception:
            username = BOT_USERNAME
    msg, kb = await _build_refer_message(user_id, username, bot_id=bot_id, bot_name=bot_name)
    await query.edit_message_text(
        msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb
    )
    await query.edit_message_text(
        msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb
    )
