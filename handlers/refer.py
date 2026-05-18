"""
/refer command handler.
Generates and shows the user's personal referral link with stats.
"""
import html
from telegram import Update
from telegram.ext import ContextTypes

from config import settings
from db.connection import get_pool
from services.referral_service import get_referral_stats, REFERRAL_BONUS_DAYS, REFERRAL_MAX_DAYS

BOT_USERNAME = "ApplixyBot"


async def refer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /refer — show user's referral link and stats."""
    user_id = update.effective_user.id
    pool = get_pool()

    stats = await get_referral_stats(user_id, pool)
    referrals_made   = stats["referrals_made"]
    bonus_days       = stats["bonus_days_earned"]
    days_left_cap    = stats["days_until_cap"]
    at_cap           = stats["at_cap"]

    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

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
        f"you earn <b>{REFERRAL_BONUS_DAYS} free Pro days</b> instantly!\n\n"
        f"🔗 <b>Your referral link:</b>\n"
        f"<code>{link}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Your Stats</b>\n"
        f"  • Friends referred : <b>{referrals_made}</b>\n"
        f"  • Bonus days earned: <b>{bonus_days}</b>\n"
        f"  {cap_note}\n\n"
        "💡 <i>Tap the link above to copy it, then share via WhatsApp or DM!</i>"
    )

    await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
