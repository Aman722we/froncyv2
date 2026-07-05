"""
APScheduler setup — daily alerts, evening digest, weekly scorecard.
Scraping has been removed. All jobs are manually curated via the admin panel.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from utils.error_alert import send_error_alert
from db.connection import get_pool


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

        # Get current time in IST (e.g. "13:00")
        ist = ZoneInfo('Asia/Kolkata')
        now_ist = datetime.now(ist)
        # ⚠️ TEST MODE: round to nearest 5-minute slot (normally 10)
        minute = (now_ist.minute // 5) * 5
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

                # Freshness count since the user's last alert reset time
                from db.manual_jobs import count_new_jobs_since
                new_jobs = await count_new_jobs_since(user_record.get("jobs_reset_at"))

                # Format alert message with the new Daily Feed UI
                from utils.messages import format_daily_feed_message
                from utils import keyboards

                msg = format_daily_feed_message(jobs, plan, total_active_jobs, user=user_dict, new_jobs=new_jobs)
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
    """Friday scorecard: rich weekly stats for ALL onboarded users.
    Shows jobs viewed, saved, applied this week + top skill gap tip."""
    try:
        from db.connection import get_pool
        from db.tracker import get_weekly_scorecard
        from db.manual_jobs import get_manual_jobs
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        from utils.messages import escape_md

        logger.info("📊 Sending Friday scorecard...")
        pool = get_pool()

        async with pool.acquire() as conn:
            users = await conn.fetch(
                """SELECT telegram_id, skills, first_name
                   FROM users
                   WHERE is_onboarded = TRUE
                   AND (is_deleted IS NULL OR is_deleted = FALSE)"""
            )

        if not _bot_app:
            return

        # Pre-load sample jobs for skill gap analysis (once, shared across all users)
        try:
            sample_jobs = await get_manual_jobs(limit=30)
        except Exception:
            sample_jobs = []

        sent = 0
        for u in users:
            telegram_id = u["telegram_id"]
            first_name  = escape_md(u["first_name"] or "there")
            user_skills  = {s.lower() for s in (u["skills"] or [])}
            try:
                stats = await get_weekly_scorecard(telegram_id)
                viewed  = stats["viewed"]
                saved   = stats["saved"]
                applied = stats["applied"]

                # Skip users who weren't active at all this week
                if viewed == 0 and saved == 0 and applied == 0:
                    continue

                # ── Skill gap tip ────────────────────────────────────────
                skill_tip_line = ""
                try:
                    missing: dict[str, int] = {}
                    for job in sample_jobs:
                        for sk in [s.lower() for s in (job.get("skills") or [])]:
                            if sk not in user_skills:
                                missing[sk] = missing.get(sk, 0) + 1
                    if missing and sample_jobs:
                        top_sk, cnt = max(missing.items(), key=lambda x: x[1])
                        pct = round((cnt / len(sample_jobs)) * 100)
                        if pct >= 30:
                            skill_tip_line = (
                                f"\n💡 *Skill Insight:* {pct}% of current openings require "
                                rf"*{escape_md(top_sk.title())}*\. "
                                r"Adding it could unlock significantly more matches\."
                            )
                except Exception:
                    pass

                # ── Build scorecard message ──────────────────────────────
                msg = (
                    rf"📊 *Hey {first_name}\! Your Week in Review* 🎯\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    f"👀 *{viewed}* jobs viewed\n"
                    f"💾 *{saved}* jobs saved\n"
                    f"✅ *{applied}* applications tracked\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                )

                if applied >= 5:
                    msg += "\n" r"🔥 *Incredible hustle this week\! Keep it up\.* 🚀"
                elif applied >= 2:
                    msg += "\n" r"💪 *Solid week\! Consistency is what gets you hired\.*"
                elif applied == 1:
                    msg += "\n" r"🌱 *Good start\! Try to track 3\+ applications next week\.*"
                else:
                    msg += "\n" r"👋 *Don't forget to track your applications\! Every tap counts\.*"

                msg += skill_tip_line

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📅 Open Daily Feed",  callback_data="menu_daily")],
                    [InlineKeyboardButton("📋 Open Tracker",     callback_data="tracker")],
                ])

                await _bot_app.bot.send_message(
                    chat_id=telegram_id,
                    text=msg,
                    parse_mode="MarkdownV2",
                    reply_markup=kb
                )
                sent += 1
            except Exception as e:
                logger.error(f"Failed to send Friday scorecard to {telegram_id}: {e}")

        logger.info(f"📊 Friday scorecard sent to {sent} users.")

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



async def _send_evening_digest():
    """Daily 6:30 PM IST consolidated digest.
    Bundles saved jobs reminders (#5 Unfinished Business) AND due follow-ups
    into a SINGLE message per user — replaces the old hourly _process_reminders."""
    try:
        from db.jobs import get_saved_jobs, get_users_with_saved_jobs
        from db.tracker import get_due_followups, mark_reminders_sent
        from utils.messages import escape_md
        from utils.keyboards import saved_jobs_keyboard
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton

        logger.info("🌆 Running 6:30 PM evening digest...")

        if not _bot_app:
            logger.warning("Bot app not set — cannot send evening digest")
            return

        pool = get_pool()

        # Collect ALL users who have either saved jobs OR due follow-ups
        async with pool.acquire() as conn:
            candidate_rows = await conn.fetch(
                """
                SELECT DISTINCT u.telegram_id
                FROM users u
                WHERE u.is_onboarded = TRUE
                  AND (u.is_deleted IS NULL OR u.is_deleted = FALSE)
                  AND (
                      EXISTS (SELECT 1 FROM saved_jobs sj WHERE sj.telegram_id = u.telegram_id)
                   OR EXISTS (SELECT 1 FROM reminders r WHERE r.telegram_id = u.telegram_id AND r.sent = FALSE AND r.remind_at <= NOW())
                  )
                """
            )

        sent_count = 0
        for row in candidate_rows:
            telegram_id = row["telegram_id"]
            try:
                saved_jobs = await get_saved_jobs(telegram_id)
                followups  = await get_due_followups(telegram_id)

                if not saved_jobs and not followups:
                    continue

                lines = ["👋 *Hey\\! Here's your evening checklist:*\n"]

                # ── Section 1: Jobs to apply ─────────────────────────────
                if saved_jobs:
                    lines.append("\n🔥 *Jobs to apply for:*")
                    for i, job in enumerate(saved_jobs[:10], 1):
                        title   = escape_md(job.get("title",   "Unknown"))
                        company = escape_md(job.get("company", "Unknown"))
                        lines.append(f"{i}\\. *{title}* — {company}")

                # ── Section 2: Follow-ups due ────────────────────────────
                if followups:
                    lines.append("\n⏰ *Follow\\-ups due today:*")
                    for f in followups:
                        title   = escape_md(f.get("title",   "Unknown"))
                        company = escape_md(f.get("company", "Unknown"))
                        lines.append(f"• *{title}* — {company}")
                    lines.append("_Consider sending a quick follow\\-up email to stand out\\!_")

                lines.append("\n_Tap a job to view or remove it\\._")
                msg = "\n".join(lines)

                # Use saved_jobs_keyboard so each job has a view + delete button
                kb = saved_jobs_keyboard(saved_jobs) if saved_jobs else InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Open Tracker", callback_data="tracker")]
                ])

                await _bot_app.bot.send_message(
                    chat_id=telegram_id,
                    text=msg,
                    reply_markup=kb,
                    parse_mode="MarkdownV2",
                )

                # Mark those follow-up reminders as sent
                if followups:
                    await mark_reminders_sent([f["id"] for f in followups])

                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send evening digest to {telegram_id}: {e}")

        logger.info(f"🌆 Evening digest sent to {sent_count} users")

    except Exception as e:
        logger.error(f"❌ Evening digest failed: {e}")
        if _bot_app:
            try:
                await send_error_alert(_bot_app.bot, "Scheduler — _send_evening_digest", e)
            except Exception:
                pass


from datetime import datetime

def start_scheduler():
    """Start all scheduled jobs."""
    # ⚠️ TEST MODE on develop: all jobs fire every 5 minutes for rapid testing.
    # Revert to production times before merging to main.

    # Daily alerts — every 5 min (TEST: normally every 10 min)
    scheduler.add_job(
        _send_daily_alerts,
        CronTrigger(minute="*/5"),
        id="daily_alerts",
        name="[TEST] Send daily job alerts every 5 min",
        replace_existing=True,
    )

    # Evening Digest — 07:37 UTC = 1:07 PM IST (TEST)
    scheduler.add_job(
        _send_evening_digest,
        CronTrigger(hour=7, minute=37),
        id="evening_digest",
        name="[TEST] Evening digest at 1:07 PM IST",
        replace_existing=True,
    )

    # Friday Scorecard — 07:42 UTC = 1:12 PM IST (TEST, fires daily not just Fridays)
    scheduler.add_job(
        _send_weekly_digest,
        CronTrigger(hour=7, minute=42),
        id="weekly_digest",
        name="[TEST] Friday scorecard at 1:12 PM IST",
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

    scheduler.start()
    logger.info("📅 Scheduler started — ⚠️ TEST MODE (5-min intervals)")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("📅 Scheduler stopped")
