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
        "⏰ 22d ago  (Optional)\n"
        "👤 Founder | John Doe | john@company.com | https://linkedin.com/in/johndoe  (Optional — for Apply Smart)\n\n"
        "<b>👤 Format:</b> Role | Name | Email | LinkedIn URL\n"
        "All 👤 fields after Name are optional. Include as many as you have.\n\n"
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

        # Line 7: Hiring Manager (Optional) — for Apply Smart
        # Format: 👤 Role | Name | email | linkedin_url
        hm_role_val = hm_name_val = hm_email_val = hm_linkedin_val = None
        for line in lines[5:]:
            if "👤" in line:
                hm_raw = line.replace("👤", "").strip()
                hm_parts = [p.strip() for p in hm_raw.split("|")]
                if len(hm_parts) >= 1:
                    hm_role_val = hm_parts[0] or None
                if len(hm_parts) >= 2:
                    hm_name_val = hm_parts[1] or None
                if len(hm_parts) >= 3:
                    val = hm_parts[2]
                    if "@" in val:
                        hm_email_val = val
                    elif "linkedin" in val.lower():
                        hm_linkedin_val = val
                if len(hm_parts) >= 4:
                    val = hm_parts[3]
                    if "linkedin" in val.lower():
                        hm_linkedin_val = val
                    elif "@" in val:
                        hm_email_val = val
                break

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
            "posted_at": posted_at,
            "hm_name": hm_name_val,
            "hm_role": hm_role_val,
            "hm_email": hm_email_val,
            "hm_linkedin": hm_linkedin_val,
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
    """/broadcast <message> - Send a message to all users of THIS bot (tenant-scoped)."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "📢 <b>Usage:</b> /broadcast &lt;message&gt;\n\n"
            "Example:\n<code>/broadcast 🚀 New features just dropped! Check the bot now.</code>\n\n"
            "Broadcasts are scoped to <b>this bot's users only</b>.",
            parse_mode="HTML"
        )
        return

    message_text = " ".join(context.args)
    
    # Get the bot_id for this tenant from context (injected by the pre-processor)
    bot_id = context.bot_data.get("bot_id")
    all_user_ids = await get_all_users(bot_id=bot_id)

    if not all_user_ids:
        await update.message.reply_text("❌ No onboarded users found for this bot.")
        return

    bot_label = f"bot_id={bot_id}" if bot_id else "all bots (super-admin)"
    status_msg = await update.message.reply_text(
        f"📢 Broadcasting to <b>{len(all_user_ids)}</b> users ({bot_label})...",
        parse_mode="HTML"
    )

    sent = 0
    failed = 0
    blocked = 0

    import asyncio
    from telegram.error import Forbidden, RetryAfter

    for tid in all_user_ids:
        try:
            await context.bot.send_message(chat_id=tid, text=message_text)
            sent += 1
            await asyncio.sleep(0.05)  # 20 messages per second max to avoid rate limits
        except Forbidden:
            blocked += 1
        except RetryAfter as e:
            logger.warning(f"Rate limited by Telegram. Sleeping for {e.retry_after} seconds...")
            await asyncio.sleep(e.retry_after)
            try:
                await context.bot.send_message(chat_id=tid, text=message_text)
                sent += 1
            except Exception:
                failed += 1
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


async def badresumes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/badresumes — Admin only. Show queue of users needing a manual resume fix."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    from db.users import get_users_needing_manual_resume

    queue = await get_users_needing_manual_resume()

    if not queue:
        await update.message.reply_text(
            "✅ <b>No pending manual resume fixes!</b>\n\nThe queue is empty.",
            parse_mode="HTML"
        )
        return

    lines = [f"🛠 <b>Manual Resume Fix Queue</b> — {len(queue)} user(s)\n"]
    for i, u in enumerate(queue, 1):
        uname = f"@{u['username']}" if u.get("username") else "(no username)"
        name = u.get("first_name", "Unknown")
        file = u.get("resume_filename", "N/A")
        uid = u["telegram_id"]
        lines.append(
            f"{i}. <b>{name}</b> {uname}\n"
            f"   🆔 <code>{uid}</code>\n"
            f"   📄 {file}\n"
            f"   📥 /getresume {uid}\n"
            f"   📤 /fixresume {uid}"
        )

    await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")


async def getresume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/getresume <user_id> — Admin only. Download the raw broken PDF for a specific user."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b> /getresume &lt;user_id&gt;\n\n"
            "Example:\n<code>/getresume 1384292160</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. It must be a number.")
        return

    from db.users import get_raw_resume_bytes
    bot_id = context.bot_data.get('bot_id', 1)
    raw_bytes, filename = await get_raw_resume_bytes(target_id, bot_id=bot_id)
    
    if not raw_bytes:
        await update.message.reply_text("❌ No raw resume found for this user in the database.")
        return

    await update.message.reply_document(
        document=raw_bytes,
        filename=filename or f"resume_{target_id}.pdf",
        caption=f"Here is the broken resume for user <code>{target_id}</code>.",
        parse_mode="HTML"
    )


async def fixresume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fixresume <user_id> — Admin only. Upload a fixed PDF for a specific user."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b> /fixresume &lt;user_id&gt;\n\n"
            "Example:\n<code>/fixresume 1384292160</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. It must be a number.")
        return

    # Put admin in the upload state with the target user set
    context.user_data["waiting_for_fixresume_upload"] = True
    context.user_data["fixresume_target_user_id"] = target_id

    from db.users import get_user
    bot_id = context.bot_data.get('bot_id', 1)
    target = await get_user(target_id, bot_id=bot_id)
    if not target:
        await update.message.reply_text("❌ User not found on this bot.")
        return
    name = target.get("first_name", "Unknown") if target else "Unknown"
    filename = target.get("resume_filename", "N/A") if target else "N/A"

    await update.message.reply_text(
        f"📎 <b>Fix Resume for {name}</b> (<code>{target_id}</code>)\n"
        f"📄 Current file: {filename}\n\n"
        "Now send me the <b>fixed PDF</b>. I'll save it to their profile and notify them automatically.",
        parse_mode="HTML"
    )
    logger.info(f"Admin initiated manual resume fix for user {target_id}")


async def addbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addbot <token> <guru_name> [split%] — Admin only. Register a new Creator bot."""
    user_id = update.effective_user.id
    logger.info(f"/addbot received from user_id={user_id}, ADMIN_TELEGRAM_ID={settings.ADMIN_TELEGRAM_ID}")
    if user_id != settings.ADMIN_TELEGRAM_ID:
        logger.warning(f"/addbot rejected: user {user_id} is not admin ({settings.ADMIN_TELEGRAM_ID})")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚙️ <b>Usage:</b> /addbot &lt;token&gt; &lt;creator_name&gt; [split_pct]\n\n"
            "Example:\n"
            "<code>/addbot 1234567890:ABCDEFGH CodeWithRahul 50</code>\n\n"
            "• <b>token</b>: Telegram bot token from BotFather\n"
            "• <b>creator_name</b>: Display name for the Creator\n"
            "• <b>split_pct</b>: Revenue split % for Creator (default: 50)",
            parse_mode="HTML",
        )
        return

    new_token = args[0]
    guru_name = args[1]
    split_pct = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 50

    await update.message.reply_text(f"⏳ Registering bot for <b>{guru_name}</b>...", parse_mode="HTML")

    try:
        # 1. Fetch bot info from Telegram to get the username
        from telegram import Bot
        temp_bot = Bot(token=new_token)
        bot_info = await temp_bot.get_me()
        bot_username = bot_info.username

        # 2. Register in DB
        from db.bots import register_bot
        bot_cfg = await register_bot(
            bot_token=new_token,
            bot_username=bot_username,
            guru_name=guru_name,
            split_percentage=split_pct,
        )
        bot_id = bot_cfg["id"]

        # 3. Boot the PTB Application in-memory
        from bot import build_bot
        from bot_registry import add_bot, get_app_for_token
        from config import settings as _s
        
        app = await add_bot(new_token, bot_id, build_fn=build_bot)

        # 4. Set Telegram webhook
        if _s.ENVIRONMENT == "production":
            import os
            webhook_base = _s.WEBHOOK_URL or os.getenv("RAILWAY_PUBLIC_DOMAIN") or ""
            if webhook_base:
                webhook_base = webhook_base if webhook_base.startswith("http") else f"https://{webhook_base}"
                await app.bot.set_webhook(url=f"{webhook_base.rstrip('/')}/webhook/{new_token}")

        await update.message.reply_text(
            f"✅ <b>Creator Bot Registered!</b>\n\n"
            f"🤖 @{bot_username}\n"
            f"👤 Creator: {guru_name}\n"
            f"💸 Revenue Split: {split_pct}% to Creator\n"
            f"🆔 bot_id: {bot_id}\n\n"
            f"Webhook is set. The bot is live! 🚀\n\n"
            f"<b>Next step:</b> Ask the Creator for their Telegram ID, then run:\n"
            f"<code>/setcreator {bot_id} &lt;their_telegram_id&gt;</code>",
            parse_mode="HTML",
        )
        logger.info(f"Admin registered new Guru bot @{bot_username} (bot_id={bot_id})")

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to register bot: <code>{e}</code>", parse_mode="HTML")
        logger.error(f"addbot_command failed: {e}", exc_info=True)


async def setcreator_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setcreator <bot_id> <creator_telegram_id> — Admin only. Link a Creator's Telegram ID to their bot.

    This gives the Creator access to /dashboard and /broadcast inside their bot.

    Usage:
      /setcreator 2 987654321
    """
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    args = context.args
    if not args or len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text(
            "⚙️ <b>Usage:</b> /setcreator &lt;bot_id&gt; &lt;creator_telegram_id&gt;\n\n"
            "Example:\n<code>/setcreator 2 987654321</code>\n\n"
            "Get the Creator's Telegram ID by asking them to forward a message to @userinfobot.",
            parse_mode="HTML",
        )
        return

    bot_id          = int(args[0])
    creator_tg_id   = int(args[1])

    from db.bots import set_guru_telegram_id, get_bot_by_id
    bot_cfg = await get_bot_by_id(bot_id)
    if not bot_cfg:
        await update.message.reply_text(f"❌ No bot found with bot_id={bot_id}.")
        return

    success = await set_guru_telegram_id(bot_id, creator_tg_id)
    if success:
        await update.message.reply_text(
            f"✅ <b>Creator linked!</b>\n\n"
            f"Bot: @{bot_cfg['bot_username']} (id={bot_id})\n"
            f"Creator Telegram ID: <code>{creator_tg_id}</code>\n\n"
            f"The Creator can now use <b>/dashboard</b>, <b>/broadcast</b>, and <b>/creator</b> inside their bot.",
            parse_mode="HTML",
        )
        logger.info(f"Admin linked creator_telegram_id={creator_tg_id} to bot_id={bot_id}")
    else:
        await update.message.reply_text(f"❌ Failed to link. Check that bot_id={bot_id} exists.")



async def delsource_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delsource <id> - Delete a career source."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return
        
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /delsource <id>")
        return
        
    source_id = int(args[0])
    from db.connection import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM career_sources WHERE id = $1", source_id)
        if res == "DELETE 1":
            await update.message.reply_text(f"\u2705 Deleted source {source_id}")
        else:
            await update.message.reply_text(f"\u274C Source {source_id} not found.")

async def addsource_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addsource <provider> <board_token> <Company Name> — Add a career source to monitor."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return
    
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "<b>Usage:</b> /addsource <provider> <board_token> <Company Name>\n\n"
            "<b>Providers:</b> GREENHOUSE, LEVER, ASHBY\n\n"
            "<b>Examples:</b>\n"
            "<code>/addsource GREENHOUSE gatherai Gather AI</code>\n"
            "<code>/addsource LEVER notion Notion</code>\n"
            "<code>/addsource ASHBY linear Linear</code>",
            parse_mode="HTML"
        )
        return
    
    provider = args[0].upper()
    if provider not in ("GREENHOUSE", "LEVER", "ASHBY"):
        await update.message.reply_text(f"❌ Unknown provider: <code>{provider}</code>. Use GREENHOUSE, LEVER, or ASHBY.", parse_mode="HTML")
        return
    
    board_token = args[1].lower()
    company_name = " ".join(args[2:])
    
    from db.career_sources import add_career_source
    new_id = await add_career_source(company_name, provider, board_token)
    await update.message.reply_text(
        f"✅ <b>Source added!</b>\n\n"
        f"<b>ID:</b> {new_id}\n"
        f"<b>Company:</b> {company_name}\n"
        f"<b>Provider:</b> {provider}\n"
        f"<b>Token:</b> <code>{board_token}</code>\n\n"
        f"Use /listsources to verify, or /syncnow to test immediately.",
        parse_mode="HTML"
    )
    logger.info(f"Admin added career source: {company_name} ({provider}/{board_token})")



async def bulkadd_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/bulkadd <list of sources> - Bulk add up to 50 sources at once.
    Format per line: PROVIDER board_token Company Name
    """
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return
        
    text = update.message.text
    # Remove the command itself
    lines = text.split("\n")[1:]
    
    if not lines or len(lines) == 0:
        await update.message.reply_text(
            "<b>Usage:</b> /bulkadd\n"
            "GREENHOUSE doordash DoorDash\n"
            "LEVER notion Notion\n"
            "ASHBY linear Linear\n\n"
            "<i>(Paste up to 50 lines at once)</i>",
            parse_mode="HTML"
        )
        return
        
    if len(lines) > 50:
        await update.message.reply_text("?O Please submit a maximum of 50 companies at a time to avoid rate limits.")
        return

    from db.career_sources import add_career_source, source_already_exists
    
    success_count = 0
    skipped_count = 0
    errors = []
    
    msg = await update.message.reply_text("⏳ Processing bulk add...")
    
    for i, line in enumerate(lines):
        parts = line.strip().split()
        if not parts:
            continue
            
        if len(parts) < 3:
            errors.append(f"Line {i+1}: Invalid format -> {line[:20]}")
            continue
            
        provider = parts[0].upper()
        if provider not in ("GREENHOUSE", "LEVER", "ASHBY"):
            errors.append(f"Line {i+1}: Unknown provider {provider}")
            continue
            
        board_token = parts[1].lower()
        company_name = " ".join(parts[2:])
        
        try:
            if await source_already_exists(provider, board_token):
                skipped_count += 1
                continue
                
            from services.career_fetcher import verify_board_token
            is_valid = await verify_board_token(provider, board_token)
            if not is_valid:
                errors.append(f"Line {i+1}: 404 Not Found (Invalid token)")
                continue
                
            await add_career_source(company_name, provider, board_token)
            success_count += 1
        except Exception as e:
            errors.append(f"Line {i+1}: DB Error -> {str(e)[:30]}")
            
    summary = (
        f"<b>⚡ Bulk Add Complete</b>\n\n"
        f"✅ Added: {success_count}\n"
        f"⏩ Skipped (already exist): {skipped_count}\n"
        f"❌ Failed: {len(errors)}\n"
    )
    if errors:
        summary += "\n<b>Errors:</b>\n" + "\n".join(f"- {e}" for e in errors[:15])
        if len(errors) > 15:
            summary += f"\n...and {len(errors)-15} more."
            
    await msg.edit_text(summary, parse_mode="HTML")
    logger.info(f"Admin bulk added {success_count} sources ({skipped_count} skipped, {len(errors)} errors)")

async def listsources_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listsources — List all configured career sources."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return
    
    from db.career_sources import get_all_career_sources
    sources = await get_all_career_sources()
    
    if not sources:
        await update.message.reply_text("No career sources configured yet. Use /addsource to add one.")
        return
    
    from datetime import timezone, datetime
    now = datetime.now(timezone.utc)
    
    lines = [f"<b>📡 Career Sources ({len(sources)} total)</b>\n"]
    for s in sources:
        status = "🟢" if s["is_active"] else "🔴"
        last_check = s["last_checked_at"]
        last_ok = s["last_successful_check_at"]
        err = s["last_error"]
        
        if last_check:
            mins = int((now - last_check.replace(tzinfo=timezone.utc) if last_check.tzinfo is None else (now - last_check)).total_seconds() / 60)
            check_str = f"{mins}m ago"
        else:
            check_str = "never"
        
        lines.append(
            f"{status} <b>{s['company_name']}</b> [{s['provider']}]\n"
            f"   Token: <code>{s['board_token']}</code> | ID: {s['id']}\n"
            f"   Last checked: {check_str}"
            + (f" | ⚠️ {err[:60]}" if err else "")
        )
    
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 3800:
            await update.message.reply_text(chunk, parse_mode="HTML")
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk:
        await update.message.reply_text(chunk, parse_mode="HTML")


async def syncnow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/syncnow [source_id] — Manually trigger a career page sync."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return
    
    from datetime import timezone
    
    args = context.args
    specific_id = int(args[0]) if args and args[0].isdigit() else None
    
    msg = await update.message.reply_text("⚡ Running career sync...")
    
    if specific_id:
        from db.career_sources import get_all_career_sources
        from services.career_sync import sync_one_source
        sources = await get_all_career_sources()
        source = next((s for s in sources if s["id"] == specific_id), None)
        if not source:
            await msg.edit_text(f"❌ No source found with ID {specific_id}")
            return
        summaries = [await sync_one_source(source)]
    else:
        from services.career_sync import run_career_sync
        summaries = await run_career_sync()
    
    if not summaries:
        await msg.edit_text("No active sources to sync. Add some with /addsource.")
        return
    
    total_new = sum(s.get("new", 0) for s in summaries)
    total_errors = sum(1 for s in summaries if s.get("errors", 0) > 0)
    
    lines = [f"<b>⚡ Sync Complete ({len(summaries)} sources)</b>\n"]
    
    # Only show detailed logs for sources that actually had new jobs or errors if there are many sources
    for s in summaries:
        if len(summaries) > 10 and s.get("new", 0) == 0 and s.get("errors", 0) == 0:
            continue
            
        lines.append(
            f"<b>{s['company']}</b>\n"
            f"  Fetched: {s['fetched']} | New: {s['new']} | Dupes: {s['duplicates']} | Errors: {s['errors']}"
        )
    
    lines.append(f"\n🎉 <b>Total new jobs discovered: {total_new}</b>")
    if len(summaries) > 10 and total_new == 0 and total_errors == 0:
        lines.append("<i>(All other sources fetched 0 new jobs without errors.)</i>")
        
    chunk = ""
    first_msg = True
    for line in lines:
        if len(chunk) + len(line) + 1 > 3800:
            if first_msg:
                await msg.edit_text(chunk, parse_mode="HTML")
                first_msg = False
            else:
                await update.message.reply_text(chunk, parse_mode="HTML")
            chunk = line + "\n"
        else:
            chunk += line + "\n"
            
    if chunk:
        if first_msg:
            await msg.edit_text(chunk, parse_mode="HTML")
        else:
            await update.message.reply_text(chunk, parse_mode="HTML")


async def admin_pingjob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to test instant job alert. Usage: /pingjob <user_id> <job_id>"""
    from config import settings
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /pingjob <user_id> <job_id>")
        return

    target_id, job_id = args
    try: target_id, job_id = int(target_id), int(job_id)
    except: return await update.message.reply_text("IDs must be integers")

    from db.connection import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        job_row = await conn.fetchrow("SELECT * FROM manual_jobs WHERE id = $1", job_id)
    
    if not job_row:
        await update.message.reply_text("Job not found")
        return
        
    job = dict(job_row)
    job["is_manual"] = True
    
    from utils.messages import escape_md
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    
    title = escape_md(job.get("title", "New Job"))
    company = escape_md(job.get("company", "Unknown"))
    location = escape_md(job.get("location") or "Remote")
    job_url = job.get("url", "")
    
    salary_line = ""
    salary = job.get("salary")
    if salary and salary.lower() not in ("not disclosed", ""):
        salary_line = f"\n💰 {escape_md(salary)}"

    yoe = job.get("min_yoe")
    yoe_line = ""
    if yoe is not None and yoe > 0:
        yoe_line = f"\n🎓 {yoe}\+ YOE"

    msg = (
        f"🚨 *NEW JOB ALERT*\n\n"
        f"*{title}*\n"
        f"🏢 {company}\n"
        f"📍 {location}"
        f"{salary_line}"
        f"{yoe_line}\n"
        f"🎯 *95% match*\n\n"
        f"⚡️ Direct from company careers\n"
        f"🕐 Detected 0 min ago"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 Apply Now", url=job_url),
            InlineKeyboardButton("👤 Request HR Details", callback_data=f"req_hr_{job_id}"),
        ],
    ])
    
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=msg,
            parse_mode="MarkdownV2",
            reply_markup=kb,
            disable_web_page_preview=True
        )
        await update.message.reply_text("Pinged successfully!")
    except Exception as e:
        await update.message.reply_text(f"Error pinging: {e}")

async def completerequest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/completerequest <req_id> <message to user> - Complete a manual request."""
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "<b>Usage:</b> /completerequest &lt;req_id&gt; &lt;message to user...&gt;\n\n"
            "<b>Example:</b>\n"
            "<code>/completerequest 1 Here is the hiring manager: John Doe (john@okta.com)</code>",
            parse_mode="HTML"
        )
        return

    try:
        req_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Request ID must be a number.")
        return

    reply_text = " ".join(args[1:])
    
    from db.connection import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        req = await conn.fetchrow("SELECT user_id, request_type FROM manual_requests WHERE id = $1", req_id)
        if not req:
            await update.message.reply_text(f"❌ Could not find request #{req_id}.")
            return

        target_user_id = req["user_id"]
        req_type = req["request_type"]
        
        from db.manual_requests import complete_request
        success = await complete_request(req_id)
        if not success:
            await update.message.reply_text("❌ Failed to update request status in DB. Still sending message.")

    try:
        title = "👔 <b>HR Contact Details</b>" if req_type == "HR_CONTACT" else "📄 <b>Resume Review Feedback</b>"
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"{title}\n\n{reply_text}",
            parse_mode="HTML"
        )
        await update.message.reply_text(f"✅ Request #{req_id} marked as complete! Message sent to user <code>{target_user_id}</code>.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send message to user: {e}")
