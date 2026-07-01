"""
Main Menu handler — /menu command and back_menu callback.
"""
from telegram import Update
from telegram.ext import ContextTypes
from utils import keyboards, messages
from db.users import get_user
from db.connection import get_pool
from services.pricing_service import get_current_pricing


async def _get_upgrade_price() -> int | None:
    """Helper to get current upgrade price from DB."""
    try:
        pricing = await get_current_pricing(get_pool())
        return pricing.get("current_price")
    except Exception:
        return None


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /menu command."""
    user = await get_user(update.effective_user.id)
    plan = user.get("plan", "free") if user else "free"
    upgrade_price = await _get_upgrade_price() if plan not in ("pro",) else None

    await update.message.reply_text(
        messages.main_menu(user),
        reply_markup=keyboards.main_menu_keyboard(plan, upgrade_price=upgrade_price),
        parse_mode="MarkdownV2",
    )


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Back to Menu' callback button."""
    query = update.callback_query
    await query.answer()
    user = await get_user(update.effective_user.id)
    plan = user.get("plan", "free") if user else "free"
    upgrade_price = await _get_upgrade_price() if plan not in ("pro",) else None

    await query.edit_message_text(
        messages.main_menu(user),
        reply_markup=keyboards.main_menu_keyboard(plan, upgrade_price=upgrade_price),
        parse_mode="MarkdownV2",
    )
