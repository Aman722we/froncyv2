"""
Upgrade and Payment handlers — dynamic pricing with early adopter scarcity.
"""
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from loguru import logger

from db.users import get_user
from db.connection import get_pool
from services.payment_service import create_subscription_link
from services.pricing_service import get_current_pricing
from utils import keyboards, messages
from utils.helpers import escape_md


async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /upgrade — show dynamic pricing based on early adopter status."""
    user_id = update.effective_user.id
    user = await get_user(user_id)

    if not user:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Please /start first.")
        else:
            await update.message.reply_text("Please /start first.")
        return

    plan = user.get("plan", "free")
    if plan == "pro":
        msg = escape_md("✅ You're already on Pro!")
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg, parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(msg, parse_mode="MarkdownV2")
        return

    # Get dynamic pricing
    db_pool = get_pool()
    pricing = await get_current_pricing(db_pool)

    if pricing["is_early_adopter_active"]:
        msg = messages.upgrade_early_adopter_message(pricing)
        btn_label = f"💳 Lock in ₹{pricing['current_price']}/mo Now"
    else:
        msg = messages.upgrade_regular_message(pricing)
        btn_label = f"💳 Upgrade to Pro — ₹{pricing['current_price']}/mo"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(btn_label, callback_data="upgrade_pro")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
    ])

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2")


async def checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send Razorpay payment link with current dynamic price."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    db_pool = get_pool()
    pricing = await get_current_pricing(db_pool)

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Plans", callback_data="menu_upgrade")]
    ])

    try:
        await query.edit_message_text("⏳ Generating secure payment link...")

        is_early = pricing["is_early_adopter_active"]
        amount = pricing["current_price"]

        url = await create_subscription_link(
            plan="pro",
            telegram_id=user_id,
            db_pool=db_pool,
            amount=amount,
            is_early_adopter=is_early,
        )

        if url:
            price_label = f"₹{amount}"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💳 Pay {price_label} — Tap Here", url=url)],
                [InlineKeyboardButton("🔙 Back to Plans", callback_data="menu_upgrade")]
            ])
            await query.edit_message_text(
                f"✅ *Your payment link is ready\\!*\n\n"
                f"Tap the button below to upgrade to *Pro* securely via Razorpay\\.\n\n"
                "Your account upgrades automatically within 1 minute of payment\\.",
                reply_markup=kb,
                parse_mode="MarkdownV2"
            )
        else:
            await query.edit_message_text(
                "❌ Could not generate a payment link\\. Please try again\\.",
                reply_markup=back_kb,
                parse_mode="MarkdownV2"
            )

    except Exception as e:
        logger.error(f"checkout_handler crashed for user={user_id}: {e}")
        try:
            await query.edit_message_text(
                "❌ Something went wrong\\. Please try again\\.",
                reply_markup=back_kb,
                parse_mode="MarkdownV2"
            )
        except Exception:
            pass
