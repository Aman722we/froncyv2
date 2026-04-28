"""
APScheduler setup — job scraping, daily alerts, and counter resets.
Runs in the same asyncio event loop as the bot.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from services.job_scraper import scrape_all_sources
from db.jobs import upsert_jobs, deactivate_old_jobs


scheduler = AsyncIOScheduler()

# Store reference to bot application for sending alerts
_bot_app = None


def set_bot_app(app):
    """Store bot application reference for sending alert messages."""
    global _bot_app
    _bot_app = app


async def _run_scraper():
    """Background task: scrape all job sources and upsert into DB."""
    try:
        logger.info("⏰ Scheduled job scraper starting...")
        jobs = await scrape_all_sources()
        if jobs:
            inserted = await upsert_jobs(jobs)
            logger.info(f"✅ Scraper complete: {inserted} new jobs from {len(jobs)} total")
        else:
            logger.warning("⚠️ Scraper returned 0 jobs")
    except Exception as e:
        logger.error(f"❌ Scheduled scraper failed: {e}")


async def _send_daily_alerts():
    """Background task: send daily job digest to all users at their alert time."""
    try:
        from db.connection import get_pool
        from db.jobs import get_matching_jobs

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
                       experience_level, batch_year
                FROM users
                WHERE is_onboarded = TRUE AND alert_time = $1
                """,
                current_time_str
            )

        if not _bot_app:
            logger.warning("Bot app not set — cannot send alerts")
            return

        sent_count = 0
        for user in users:
            try:
                skills = user["skills"] or []
                location = user["location_pref"] or "remote"
                plan = user["plan"] or "free"
                # Trial and pro get same job limit (20)
                limit = 5 if plan == "free" else 20

                jobs = await get_matching_jobs(skills, location, limit=limit)
                if not jobs:
                    continue

                # Build a proper user dict that format_job_list_message expects
                user_dict = {
                    "telegram_id": user["telegram_id"],
                    "skills": skills,
                    "location_pref": location,
                    "plan": plan,
                    "experience_level": user["experience_level"] or "0",
                    "batch_year": user["batch_year"],
                }

                # Format alert message
                from utils.messages import format_job_list_message
                from utils import keyboards
                msg = format_job_list_message(jobs, plan, len(jobs), user=user_dict)
                kb = keyboards.job_list_keyboard(jobs, plan, total_count=len(jobs), page=1)

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





async def _cleanup_old_jobs():
    """Deactivate jobs older than 30 days."""
    try:
        count = await deactivate_old_jobs(days=30)
        logger.info(f"🧹 Cleaned up {count} old jobs")
    except Exception as e:
        logger.error(f"Job cleanup failed: {e}")


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


from datetime import datetime

def start_scheduler():
    """Start all scheduled jobs."""
    # Job scraper — every 2 hours, starting immediately
    scheduler.add_job(
        _run_scraper,
        IntervalTrigger(hours=2),
        id="scrape_jobs",
        name="Scrape all job sources",
        replace_existing=True,
        next_run_time=datetime.now()
    )

    # Daily alerts — Runs every 10 minutes to support more granular alert times like 15:10
    scheduler.add_job(
        _send_daily_alerts,
        CronTrigger(minute="0,10,20,30,40,50"),
        id="daily_alerts",
        name="Send daily job alerts based on user settings",
        replace_existing=True,
    )



    # Cleanup old jobs — weekly on Sunday
    scheduler.add_job(
        _cleanup_old_jobs,
        CronTrigger(day_of_week="sun", hour=4),
        id="cleanup_jobs",
        name="Deactivate old jobs",
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

    scheduler.start()
    logger.info("📅 Scheduler started with jobs")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("📅 Scheduler stopped")
