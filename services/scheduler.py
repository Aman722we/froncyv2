"""
APScheduler setup — daily alerts, weekly digest, and follow-up reminders.
Scraping has been removed. All jobs are manually curated via the admin panel.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from utils.error_alert import send_error_alert


scheduler = AsyncIOScheduler()

# Store reference to bot application for sending alerts
_bot_app = None


def set_bot_app(app):
    """Store bot application reference for sending alert messages."""
    global _bot_app
    _bot_app = app



async def _send_daily_alerts():
    """Background task: send daily job digest to all users at their alert time."""
    try:
        from db.connection import get_pool

        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Get current time in IST (e.g. "09:00")
        ist = ZoneInfo('Asia/Kolkata')
        now_ist = datetime.now(ist)
        # To make it align perfectly with 10-minute intervals
        minute = (now_ist.minute // 10) * 10
        current_time_str = f"{now_ist.hour:02d}:{minute:02d}"

        logger.info(f"📬 Checking daily job alerts for time slot: {current_time_str} IST...")
        pool = get_pool()

        async with pool.acquire() as conn:
            # Get all users who should receive alerts at this specific hour
            users = await conn.fetch(
                """
                SELECT telegram_id, skills, location_pref, plan,
                       experience_level, batch_year, role_pref, is_trial, trial_expires_at
                FROM users
                WHERE is_onboarded = TRUE AND alert_time = $1
                AND (is_deleted IS NULL OR is_deleted = FALSE)
                """,
                current_time_str
            )

        if not _bot_app:
            logger.warning("Bot app not set — cannot send alerts")
            return

        sent_count = 0
        from db.manual_jobs import get_personalized_manual_jobs, count_manual_jobs
        
        # Total count is needed for the "+X more jobs" footer
        total_active_jobs = await count_manual_jobs()

        from utils.helpers import get_effective_plan

        for user in users:
            try:
                user_record = dict(user)
                plan = get_effective_plan(user_record)
                
                # Build a proper user dict that compute_manual_job_match expects
                user_dict = {
                    "telegram_id": user["telegram_id"],
                    "skills": user["skills"] or [],
                    "location_pref": user["location_pref"] or "remote",
                    "plan": plan,
                    "experience_level": user["experience_level"] or "0",
                    "batch_year": user["batch_year"],
                    "role_pref": user["role_pref"] or "fullstack",
                }

                feed_limit = 8 if plan == "free" else 12
                jobs = await get_personalized_manual_jobs(user_dict, limit=feed_limit)
                if not jobs:
                    continue

                # Format alert message with the new Daily Feed UI
                from utils.messages import format_daily_feed_message
                from utils import keyboards
                
                msg = format_daily_feed_message(jobs, plan, total_active_jobs, user=user_dict)
                kb = keyboards.daily_feed_keyboard(jobs, plan)

                await _bot_app.bot.send_message(
                    chat_id=user["telegram_id"],
                    text=msg,
                    reply_markup=kb,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )
                sent_count += 1

            except Exception as e:
                logger.error(f"Failed to send alert to {user['telegram_id']}: {e}")

        logger.info(f"📬 Daily alerts sent to {sent_count}/{len(users)} users")

    except Exception as e:
        logger.error(f"❌ Daily alert job failed: {e}")
        if _bot_app:
            try:
                await send_error_alert(_bot_app.bot, "Scheduler — _send_daily_alerts", e)
            except Exception:
                pass






async def _process_reminders():
    """Check for pending follow-up reminders and send them."""
    try:
        from db.connection import get_pool
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        from utils.messages import escape_md
        
        logger.info("⏰ Processing follow-up reminders...")
        pool = get_pool()

        async with pool.acquire() as conn:
            reminders = await conn.fetch(
                """
                SELECT r.id, r.telegram_id, r.application_id,
                       a.job_id, j.company, j.title, u.plan
                FROM reminders r
                JOIN applications a ON r.application_id = a.id
                JOIN jobs j ON a.job_id = j.id
                JOIN users u ON r.telegram_id = u.telegram_id
                WHERE r.sent = FALSE AND r.remind_at <= NOW()
                """
            )

        if not _bot_app:
            return

        sent = 0
        async with pool.acquire() as conn:
            for r in reminders:
                if r["plan"] != "pro":
                    await conn.execute("UPDATE reminders SET sent = TRUE WHERE id = $1", r["id"])
                    continue
                    
                msg = (
                    f"⏰ *Follow\\-up Reminder*\n\n"
                    f"It's been 3 days since you applied to *{escape_md(r['company'])}* for the *{escape_md(r['title'])}* role\\.\n\n"
                    "Consider sending a brief follow\\-up message to the hiring manager to reiterate your interest\\."
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 View Application", callback_data=f"job_view_{r['job_id']}")]
                ])
                try:
                    await _bot_app.bot.send_message(
                        chat_id=r["telegram_id"],
                        text=msg,
                        parse_mode="MarkdownV2",
                        reply_markup=kb
                    )
                    await conn.execute("UPDATE reminders SET sent = TRUE WHERE id = $1", r["id"])
                    sent += 1
                except Exception as e:
                    logger.error(f"Failed to send reminder for {r['telegram_id']}: {e}")

        logger.info(f"⏰ Follow-up reminders sent: {sent}")
        
    except Exception as e:
        logger.error(f"❌ Process reminders failed: {e}")
        if _bot_app:
            try:
                await send_error_alert(_bot_app.bot, "Scheduler — _process_reminders", e)
            except Exception:
                pass

async def _send_weekly_digest():
    """Send weekly application digest to PRO users on Fridays."""
    try:
        from db.connection import get_pool
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        
        logger.info("📊 Sending weekly digest...")
        pool = get_pool()
        
        async with pool.acquire() as conn:
            users = await conn.fetch("SELECT telegram_id FROM users WHERE plan = 'pro' AND is_onboarded = TRUE")
            
        if not _bot_app:
            return
            
        sent = 0
        for u in users:
            telegram_id = u["telegram_id"]
            
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    """
                    SELECT count(*) FROM applications 
                    WHERE telegram_id = $1 
                    AND applied_at >= NOW() - INTERVAL '7 days'
                    """,
                    telegram_id
                )
                
            msg = (
                "📊 *Your Weekly Pipeline*\n\n"
                f"You submitted {count or 0} applications this week\\.\n"
                "Review your tracker to plan your follow\\-ups\\!"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Open Tracker", callback_data="tracker")]
            ])
            try:
                await _bot_app.bot.send_message(
                    chat_id=telegram_id,
                    text=msg,
                    parse_mode="MarkdownV2",
                    reply_markup=kb
                )
                sent += 1
            except Exception as e:
                logger.error(f"Failed to send weekly digest to {telegram_id}: {e}")
                
        logger.info(f"📊 Weekly digest sent to {sent} PRO users.")
        
    except Exception as e:
        logger.error(f"❌ Send weekly digest failed: {e}")
        if _bot_app:
            try:
                await send_error_alert(_bot_app.bot, "Scheduler — _send_weekly_digest", e)
            except Exception:
                pass


async def _cleanup_old_manual_jobs():
    """Soft-delete manual jobs older than 30 days."""
    try:
        from db.manual_jobs import cleanup_old_manual_jobs
        logger.info("🧹 Running manual jobs cleanup...")
        deleted = await cleanup_old_manual_jobs(days=30)
        logger.info(f"🧹 Cleanup complete: deactivated {deleted} old manual jobs.")
    except Exception as e:
        logger.error(f"❌ Failed to cleanup old manual jobs: {e}")
        if _bot_app:
            try:
                await send_error_alert(_bot_app.bot, "Scheduler — _cleanup_old_manual_jobs", e)
            except Exception:
                pass


async def _send_saved_jobs_reminder():
    """Daily 6:30 PM IST reminder: nudge users who have saved jobs to apply."""
    try:
        from db.jobs import get_saved_jobs, get_users_with_saved_jobs
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        from utils.messages import escape_md

        logger.info("⏰ Running saved jobs reminder...")

        if not _bot_app:
            logger.warning("Bot app not set — cannot send saved job reminders")
            return

        users = await get_users_with_saved_jobs()
        sent_count = 0

        for user_row in users:
            telegram_id = user_row["telegram_id"]
            try:
                saved_jobs = await get_saved_jobs(telegram_id)
                if not saved_jobs:
                    continue

                # Build message with list of saved jobs
                lines = ["👋 *Hey\\! You asked me to remind you about these jobs:*\n"]
                for i, job in enumerate(saved_jobs[:10], 1):
                    title = escape_md(job.get("title", "Unknown"))
                    company = escape_md(job.get("company", "Unknown"))
                    lines.append(f"{i}\\. *{title}* — {company}")

                lines.append("\n_Tap a job below to view it or remove it from your list\\._")
                msg = "\n".join(lines)

                # Keyboard: view each saved job + back
                from utils.keyboards import saved_jobs_keyboard
                kb = saved_jobs_keyboard(saved_jobs)

                await _bot_app.bot.send_message(
                    chat_id=telegram_id,
                    text=msg,
                    reply_markup=kb,
                    parse_mode="MarkdownV2",
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send saved-jobs reminder to {telegram_id}: {e}")

        logger.info(f"⏰ Saved jobs reminders sent to {sent_count}/{len(users)} users")

    except Exception as e:
        logger.error(f"❌ Saved jobs reminder job failed: {e}")
        if _bot_app:
            try:
                await send_error_alert(_bot_app.bot, "Scheduler — _send_saved_jobs_reminder", e)
            except Exception:
                pass

from datetime import datetime

def start_scheduler():
    """Start all scheduled jobs."""
    # Daily alerts — Runs every 10 minutes to support granular alert times
    scheduler.add_job(
        _send_daily_alerts,
        CronTrigger(minute="0,10,20,30,40,50"),
        id="daily_alerts",
        name="Send daily job alerts based on user settings",
        replace_existing=True,
    )

    # Follow-up reminders — every hour
    scheduler.add_job(
        _process_reminders,
        IntervalTrigger(hours=1),
        id="process_reminders",
        name="Process follow-up reminders",
        replace_existing=True,
    )
    
    # Weekly Application Digest — Fridays 10 AM IST (04:30 UTC)
    scheduler.add_job(
        _send_weekly_digest,
        CronTrigger(day_of_week="fri", hour=4, minute=30),
        id="weekly_digest",
        name="Send weekly application digest",
        replace_existing=True,
    )
    
    # Cleanup old manual jobs — Runs every day at midnight UTC
    scheduler.add_job(
        _cleanup_old_manual_jobs,
        CronTrigger(hour=0, minute=0),
        id="cleanup_manual_jobs",
        name="Deactivate manual jobs older than 30 days",
        replace_existing=True,
    )

    # Saved Jobs Reminder — Daily at 6:30 PM IST (13:00 UTC)
    scheduler.add_job(
        _send_saved_jobs_reminder,
        CronTrigger(hour=13, minute=0),
        id="saved_jobs_reminder",
        name="Daily 6:30 PM reminder for saved jobs",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("📅 Scheduler started with jobs")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("📅 Scheduler stopped")
