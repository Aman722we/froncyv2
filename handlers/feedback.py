from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from loguru import logger

from config import settings
from utils.helpers import escape_md

WAITING_FOR_FEEDBACK = 1

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the feedback conversation."""
    await update.message.reply_text(
        "📝 *Send Feedback or Report a Bug*\n\n"
        "Please type your feedback, suggestion, or bug report below in a single message\\.\n\n"
        "Type /cancel if you changed your mind\\.",
        parse_mode="MarkdownV2",
    )
    return WAITING_FOR_FEEDBACK

async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the feedback and forward to admin."""
    user = update.effective_user
    feedback_text = update.message.text

    if not feedback_text:
        await update.message.reply_text("Please send a text message\\.", parse_mode="MarkdownV2")
        return WAITING_FOR_FEEDBACK

    # Construct the admin message
    admin_id = settings.ADMIN_TELEGRAM_ID
    if admin_id:
        try:
            username = f"@{user.username}" if user.username else "No Username"
            first_name = user.first_name or "Unknown"
            msg = (
                f"🚨 *New Feedback Received*\n\n"
                f"*From:* {escape_md(first_name)} \\({escape_md(username)}\\)\n"
                f"*ID:* `{user.id}`\n\n"
                f"*Message:*\n{escape_md(feedback_text)}"
            )
            await context.bot.send_message(
                chat_id=admin_id,
                text=msg,
                parse_mode="MarkdownV2"
            )
        except Exception as e:
            logger.error(f"Failed to send feedback to admin {admin_id}: {e}")

    await update.message.reply_text(
        "✅ *Thank you\\!*\n\n"
        "Your feedback has been sent directly to the developer\\. We appreciate your help in making ApplixyBot better\\!",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END

async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the feedback conversation."""
    await update.message.reply_text("Feedback cancelled. Let me know if you need anything else!")
    return ConversationHandler.END

def get_feedback_handler() -> ConversationHandler:
    """Returns the ConversationHandler for the feedback flow."""
    return ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_command)],
        states={
            WAITING_FOR_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_feedback)],
    )
