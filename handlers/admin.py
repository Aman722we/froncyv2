"""
Admin handlers for FroncyBot.
Includes the /addjob command to manually curate jobs,
and /send + /broadcast to message individual or all users.
"""
import telegram
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from loguru import logger
from config import settings
from db.manual_jobs import add_manual_job
from db.users import get_all_users

WAITING_FOR_JOB_TEXT = 1


async def addjob_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the /addjob flow (Admin only)."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested /addjob. Admin ID is {settings.ADMIN_TELEGRAM_ID}")
    if user_id != settings.ADMIN_TELEGRAM_ID:
        logger.warning(f"Unauthorized access to /addjob by {user_id}")
        return ConversationHandler.END

    await update.message.reply_text(
        "📝 <b>Add Manual Job</b>\n\n"
        "Send me the job details exactly in this format:\n\n"
        "React Developer - Oracle\n"
        "Job link: https://wellfound-react-remote-us\n"
        "📍 Remote - US | 6 month Internship | 25K/Month\n"
        "🎓 2025/2026 | 2-4 YOE  (batches optional, YOE can be range like 2-4 or single like 1+)\n"
        "🏷 Typescript, React, Next.Js, CSS, Git\n"
        "⏰ 22d ago  (Optional)\n\n"
        "Type /cancel to abort.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return WAITING_FOR_JOB_TEXT


async def parse_and_add_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parse the admin's message and insert into the DB."""
    text = update.message.text.strip()
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    if len(lines) < 5:
        await update.message.reply_text(
            "⚠️ <b>Not enough lines.</b>\n\n"
            "The job needs to be at least 5 lines long.\n"
            "👉 <b>Paste the corrected job again</b>, or type /cancel to abort.",
            parse_mode="HTML"
        )
        return WAITING_FOR_JOB_TEXT

    try:
        # Line 1: Title - Company
        title_company = lines[0].split("-", 1)
        title = title_company[0].strip()
        company = title_company[1].strip() if len(title_company) > 1 else "Unknown"

        # Line 2: URL
        url_line = lines[1]
        url = url_line.replace("Job link:", "").strip()

        # Line 3: Location | Job Type | Salary
        loc_type_sal = lines[2].replace("📍", "").split("|")
        location = loc_type_sal[0].strip() if len(loc_type_sal) > 0 else "Remote"
        
        job_type_str = loc_type_sal[1].strip() if len(loc_type_sal) > 1 else "Fulltime"
        job_type = "internship" if "intern" in job_type_str.lower() else "fulltime"
        duration = job_type_str if job_type == "internship" else None
        
        salary = loc_type_sal[2].strip() if len(loc_type_sal) > 2 else "Not disclosed"

        # Line 4: Batches | YOE
        batch_yoe = lines[3].replace("🎓", "").split("|")
        batch_str = batch_yoe[0].strip()
        
        yoe_str = "0"
        if len(batch_yoe) > 1:
            yoe_str = batch_yoe[1].strip()
        elif "yoe" in batch_str.lower():
            yoe_str = batch_str
            batch_str = ""

        batches = []
        if batch_str:
            parts = batch_str.split("/")
            for p in parts:
                p = p.strip()
                if p.isdigit():
                    batches.append(int(p))
        
        import re
        min_yoe = 0
        yoe_digits = re.findall(r'\d+', yoe_str)
        if yoe_digits:
            min_yoe = int(yoe_digits[0])  # Take the minimum (first) number in a range like "2-4"

        # Line 5: Skills
        skills_str = lines[4].replace("🏷", "").strip()
        skills = [s.strip() for s in skills_str.split(",")]

        # Line 6: Time (Optional)
        posted_at = None
        if len(lines) > 5 and "⏰" in lines[5]:
            time_str = lines[5].replace("⏰", "").replace("ago", "").replace("(Optional)", "").strip()
            from datetime import datetime, timedelta, timezone
            try:
                num = int(''.join(filter(str.isdigit, time_str)))
                if 'd' in time_str:
                    posted_at = datetime.now(timezone.utc) - timedelta(days=num)
                elif 'h' in time_str:
                    posted_at = datetime.now(timezone.utc) - timedelta(hours=num)
            except Exception:
                pass

        # Insert DB
        data = {
            "title": title,
            "company": company,
            "url": url,
            "location": location,
            "salary": salary,
            "job_type": job_type,
            "duration": duration,
            "skills": skills,
            "min_yoe": min_yoe,
            "eligible_batches": batches,
            "added_by": update.effective_user.id,
            "posted_at": posted_at
        }
        
        job_id = await add_manual_job(data)

        await update.message.reply_text(
            f"✅ <b>Job Added successfully!</b>\n"
            f"ID: {job_id}\n"
            f"{title} @ {company}",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    except telegram.error.TimedOut:
        logger.warning("Telegram timeout while replying to /addjob, but job might be saved.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error parsing manual job: {e}")
        await update.message.reply_text(
            f"⚠️ <b>Format Error:</b> {str(e)}\n\n"
            "Please check the formatting (make sure there are | dividers, etc).\n"
            "👉 <b>Paste the corrected job again</b>, or type /cancel to abort.",
            parse_mode="HTML"
        )
        return WAITING_FOR_JOB_TEXT


async def send_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a direct message to a user. Format: /send <telegram_id> <message>"""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/send <telegram_id> <message>`", parse_mode="MarkdownV2")
        return

    try:
        target_id = int(context.args[0])
        message_text = " ".join(context.args[1:])
        
        await context.bot.send_message(
            chat_id=target_id,
            text=message_text
        )
        await update.message.reply_text(f"✅ Message sent successfully to `{target_id}`.", parse_mode="MarkdownV2")
    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID format.")
    except Exception as e:
        logger.error(f"Error sending message to {target_id}: {e}")
        await update.message.reply_text(f"❌ Failed to send message: {e}")


async def cancel_addjob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel /addjob."""
    await update.message.reply_text("❌ Cancelled adding job.")
    return ConversationHandler.END


def get_addjob_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("addjob", addjob_start)],
        states={
            WAITING_FOR_JOB_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, parse_and_add_job)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_addjob)],
    )


async def send_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/send <user_id> <message> — Admin only. DM a specific user from the bot."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return  # Silently ignore unauthorized users

    # Usage check
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b> /send &lt;user_id&gt; &lt;message&gt;\n\n"
            "Example:\n<code>/send 7963303313 Hey! The bug is now fixed.</code>",
            parse_mode="HTML"
        )
        return

    # Parse target ID and message
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. It must be a number.")
        return

    message_text = " ".join(context.args[1:])

    # Send the message
    try:
        await context.bot.send_message(chat_id=target_id, text=message_text)
        await update.message.reply_text(
            f"✅ Message sent successfully to <code>{target_id}</code>!",
            parse_mode="HTML"
        )
        logger.info(f"Admin sent message to {target_id}: {message_text}")
    except telegram.error.Forbidden:
        await update.message.reply_text(
            f"❌ Failed: User <code>{target_id}</code> has <b>blocked the bot</b> or never started it.",
            parse_mode="HTML"
        )
    except telegram.error.BadRequest as e:
        await update.message.reply_text(f"❌ Bad request: {e}")
    except Exception as e:
        logger.error(f"Error sending message to {target_id}: {e}")
        await update.message.reply_text(f"❌ Unexpected error: {e}")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/broadcast <message> — Admin only. Send a message to ALL onboarded users."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b> /broadcast &lt;message&gt;\n\n"
            "Example:\n<code>/broadcast 🎉 New features just dropped! Check the bot now.</code>",
            parse_mode="HTML"
        )
        return

    message_text = " ".join(context.args)
    all_user_ids = await get_all_users()

    if not all_user_ids:
        await update.message.reply_text("⚠️ No onboarded users found in the database.")
        return

    status_msg = await update.message.reply_text(
        f"📤 Broadcasting to <b>{len(all_user_ids)}</b> users...",
        parse_mode="HTML"
    )

    sent = 0
    failed = 0
    blocked = 0

    for tid in all_user_ids:
        try:
            await context.bot.send_message(chat_id=tid, text=message_text)
            sent += 1
        except telegram.error.Forbidden:
            blocked += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {tid}: {e}")
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>Broadcast complete!</b>\n\n"
        f"📨 Sent: <b>{sent}</b>\n"
        f"🚫 Blocked: <b>{blocked}</b>\n"
        f"❌ Failed: <b>{failed}</b>",
        parse_mode="HTML"
    )
    logger.info(f"Broadcast done. Sent={sent}, Blocked={blocked}, Failed={failed}")
