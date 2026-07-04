"""
Jobs handlers — view jobs list, job details, and save/unsave jobs.
"""
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from loguru import logger

from db.users import get_user, increment_jobs_seen
from db.jobs import get_job_by_id, save_job, unsave_job, save_manual_job, unsave_manual_job
from db.manual_jobs import get_manual_jobs, get_manual_job_by_id, count_manual_jobs, get_personalized_manual_jobs
from db.connection import get_pool
from services.reset_service import check_and_reset_daily
from utils.limits import get_limit
from utils import keyboards, messages
from utils.helpers import get_effective_plan


async def daily_feed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /daily_feed command or 'menu_daily' callback."""
    import asyncio
    user_id = update.effective_user.id
    
    from db.manual_jobs import get_personalized_manual_jobs, get_seen_jobs, count_manual_jobs, log_jobs_sent, count_new_jobs_since
    
    # Fire all independent queries in parallel
    user, seen_jobs, total_active_jobs = await asyncio.gather(
        get_user(user_id),
        get_seen_jobs(user_id),
        count_manual_jobs(),
    )
    
    if not user or not user.get("is_onboarded"):
        msg = "⚠️ Please finish your setup first! Type /start to complete your profile."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    plan = get_effective_plan(user)
    
    user_dict = {
        "telegram_id": user_id,
        "skills": user.get("skills", []),
        "location_pref": user.get("location_pref", "remote"),
        "plan": plan,
        "experience_level": user.get("experience_level", "0"),
        "batch_year": user.get("batch_year"),
        "role_pref": user.get("role_pref", "fullstack"),
    }
    
    feed_limit = 8 if plan == "free" else 12

    # Fetch jobs + freshness count in parallel
    jobs, new_jobs = await asyncio.gather(
        get_personalized_manual_jobs(
            user_dict,
            seen_job_ids=seen_jobs,
            limit=feed_limit,
            exclude_sent_within_days=3,
            max_age_days=10
        ),
        count_new_jobs_since(user.get("jobs_reset_at")),
    )

    if jobs:
        await log_jobs_sent(user_id, [j["id"] for j in jobs])

    # Build optional skill tip (Phase 4) — compute from last 20 matched jobs
    skill_tip = None
    try:
        from db.manual_jobs import get_manual_jobs
        from utils.messages import compute_manual_job_match
        import random
        # Only show the tip ~30% of the time to avoid repetition
        if random.random() < 0.30:
            sample_jobs = await get_manual_jobs(limit=20)
            missing_skills: dict[str, int] = {}
            user_skills_lower = {s.lower() for s in (user_dict.get("skills") or [])}
            for job in sample_jobs:
                job_skills = [s.lower() for s in (job.get("skills") or [])]
                for sk in job_skills:
                    if sk not in user_skills_lower:
                        missing_skills[sk] = missing_skills.get(sk, 0) + 1
            if missing_skills:
                top_skill, count = max(missing_skills.items(), key=lambda x: x[1])
                pct = round((count / len(sample_jobs)) * 100)
                if pct >= 30:  # only show if meaningful
                    skill_tip = f"{pct}% of your matched jobs require {top_skill.title()}. Adding it could unlock more matches!"
    except Exception:
        skill_tip = None  # non-critical, never crash the feed

    if not jobs:
        msg = messages.no_jobs_found()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]])
    else:
        msg = messages.format_daily_feed_message(jobs, plan, total_active_jobs, user=user_dict, new_jobs=new_jobs, skill_tip=skill_tip)
        kb = keyboards.daily_feed_keyboard(jobs, plan)

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)


async def view_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /jobs command and 'View Jobs' / pagination buttons."""
    import asyncio
    user_id = update.effective_user.id
    
    # Fire ALL independent DB queries in a single parallel batch.
    # This turns 5 sequential round trips (~1500ms with cross-ocean latency)
    # into 1 parallel batch (~350ms).
    from db.manual_jobs import get_personalized_manual_jobs, get_seen_jobs, count_manual_jobs
    
    reset_task = check_and_reset_daily(user_id, get_pool())
    user_task = get_user(user_id)
    seen_task = get_seen_jobs(user_id)
    count_task = count_manual_jobs()
    
    _, user, seen_jobs, total_active_jobs = await asyncio.gather(
        reset_task, user_task, seen_task, count_task
    )
    
    if not user or not user.get("is_onboarded"):
        msg = "⚠️ Please finish your setup first! Type /start to complete your profile."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    plan = get_effective_plan(user)
    
    # Determine page number
    page = 1
    if update.callback_query and update.callback_query.data.startswith("jobs_page_"):
        page = int(update.callback_query.data.split("_")[-1])

    limit = get_limit(plan, "jobs_per_day")
    jobs_seen_today = user.get("jobs_seen_today", 0)
    offset = (page - 1) * 5
    display_count = 5

    # Free users: block pagination past their allowance
    if plan == "free":
        max_viewable_offset = 6
        if offset >= max_viewable_offset:
            msg = (
                "🔒 *100+ more personalized jobs available*\n\n"
                "Upgrade to unlock filters & get full access."
            )
            from utils.messages import escape_md
            kb = keyboards.InlineKeyboardMarkup([
                [keyboards.InlineKeyboardButton("💎 Go Pro — ₹199/mo", callback_data="upgrade_pro")],
                [keyboards.InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
            ])
            if update.callback_query:
                await update.callback_query.edit_message_text(escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")
            return
        display_count = min(5, max_viewable_offset - offset)

    # Get active filters
    filters = context.user_data.get("job_filters", {})
    
    # Fetch top 100 personalized jobs
    user_dict = {
        "telegram_id": user.get("telegram_id"),
        "skills": user.get("skills") or [],
        "location_pref": user.get("location_pref") or "remote",
        "plan": plan,
        "experience_level": user.get("experience_level") or "0",
        "batch_year": user.get("batch_year"),
        "role_pref": user.get("role_pref") or "fullstack",
    }
    all_jobs = await get_personalized_manual_jobs(user_dict, limit=100)
    
    # Filter out seen jobs
    all_jobs = [j for j in all_jobs if j["id"] not in seen_jobs]
    
    # Apply filters
    filtered_jobs = []
    f_exp = filters.get("exp", "any")
    f_time = filters.get("time", "any")
    f_match = filters.get("match", "any")
    
    # Use explicit filter if set, otherwise fallback to user's role preference
    f_role = filters.get("role", user.get("role_pref", "any")).lower()
    
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    for job in all_jobs:
        # 1. Experience Filter
        job_exp = job.get("min_yoe", 0)
        if f_exp != "any":
            if f_exp == "0" and job_exp > 0: continue
            elif f_exp == "1" and not (1 <= job_exp <= 2): continue
            elif f_exp == "3" and job_exp < 3: continue
            
        # 2. Recency Filter
        if f_time != "any":
            posted = job.get("posted_at")
            if posted:
                if isinstance(posted, str):
                    dt = datetime.fromisoformat(posted.replace('Z', '+00:00'))
                else:
                    dt = posted
                diff_hours = (now - dt).total_seconds() / 3600
                if f_time == "1d" and diff_hours > 24: continue
                elif f_time == "3d" and diff_hours > 72: continue
                
        # 3. Match Level Filter
        if f_match != "any":
            score = job.get("_match_score", 0)
            if f_match == "high" and score < 70: continue
            elif f_match == "med" and score < 40: continue
            
        # 4. Role Filter
        if f_role != "any" and f_role != "fullstack":
            title_lower = job.get("title", "").lower()
            if f_role == "frontend" and not any(kw in title_lower for kw in ["frontend", "front-end", "front end", "react", "angular", "vue"]):
                continue
            elif f_role == "backend" and not any(kw in title_lower for kw in ["backend", "back-end", "back end", "node", "python", "java", "django"]):
                continue
            
        filtered_jobs.append(job)
        
    total_filtered = len(filtered_jobs)
    page_jobs = filtered_jobs[offset:offset+display_count]

    if not page_jobs:
        if page > 1: msg = messages.no_jobs_found()
        else: msg = messages.no_jobs_found()
        back_kb = keyboards.InlineKeyboardMarkup([[
            keyboards.InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu"),
            keyboards.InlineKeyboardButton("⚙️ Filters", callback_data="jobs_filter_menu")
        ]])
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg, reply_markup=back_kb, parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(msg, reply_markup=back_kb, parse_mode="MarkdownV2")
        return

    msg = messages.format_job_list_message(page_jobs, plan, total_filtered, user=user)
    kb = keyboards.job_list_keyboard(page_jobs, plan, total_filtered, page)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)

    # Only increment counter on first view of the day (not on re-views)
    if jobs_seen_today == 0 and page == 1:
        await increment_jobs_seen(user_id, len(page_jobs))


async def view_job_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show details for a specific job."""
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split("_")
    
    from_saved = False
    from_daily = False
    if data_parts[-1] == "saved":
        from_saved = True
        job_id = int(data_parts[-2])
    elif data_parts[-1] == "daily":
        from_daily = True
        job_id = int(data_parts[-2])
    else:
        job_id = int(data_parts[-1])
        
    is_manual = "manual" in query.data

    if is_manual:
        job = await get_manual_job_by_id(job_id)
    else:
        job = await get_job_by_id(job_id)

    if not job:
        await query.edit_message_text(
            messages.error_job_not_found(),
            reply_markup=keyboards.InlineKeyboardMarkup([[keyboards.InlineKeyboardButton("🔙 Back to Jobs", callback_data="menu_jobs")]]),
            parse_mode="MarkdownV2"
        )
        return

    user_id = update.effective_user.id
    
    # User actually clicked to view the job, so mark it permanently seen
    from db.manual_jobs import mark_jobs_seen
    await mark_jobs_seen(user_id, [job_id])
    user = await get_user(user_id)
    plan = get_effective_plan(user)
    user_skills = user.get("skills", [])
    user_exp = user.get("experience_level", "0")

    if job.get("is_manual"):
        from utils.messages import compute_manual_job_match
        details = compute_manual_job_match(user, job)
    else:
        from utils.messages import compute_match_details
        details = compute_match_details(user_skills, job.get("skills", []), str(user_exp), job.get("experience_required"))
    score = details["score"]

    msg = messages.job_detail_message(job, plan=plan, user=user)
    kb = keyboards.job_detail_keyboard(job, plan=plan, score=score, from_saved=from_saved, from_daily=from_daily, user_id=user_id)

    await query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)


async def save_job_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle saving a job."""
    query = update.callback_query
    user_id = update.effective_user.id
    job_id = int(query.data.split("_")[-1])

    saved = await save_job(user_id, job_id)
    if saved:
        await query.answer("✅ Job saved!")
    else:
        await query.answer("ℹ️ Job already saved.")


async def unsave_job_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unsaving a job (from saved jobs list)."""
    query = update.callback_query
    user_id = update.effective_user.id
    job_id = int(query.data.split("_")[-1])

    await unsave_job(user_id, job_id)
    await query.answer("🗑 Job removed from saved list.")

    # Refresh saved jobs list after deletion
    from handlers.settings import view_saved_jobs
    await view_saved_jobs(update, context)


async def unsave_manual_job_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unsaving a manual job (from saved jobs list)."""
    query = update.callback_query
    user_id = update.effective_user.id
    manual_job_id = int(query.data.split("_")[-1])

    await unsave_manual_job(user_id, manual_job_id)
    await query.answer("🗑 Job removed from saved list.")

    # Refresh saved jobs list after deletion
    from handlers.settings import view_saved_jobs
    await view_saved_jobs(update, context)


async def save_manual_job_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle saving a manual (admin-curated) job."""
    query = update.callback_query
    user_id = update.effective_user.id
    manual_job_id = int(query.data.split("_")[-1])

    saved = await save_manual_job(user_id, manual_job_id)
    if saved:
        await query.answer("✅ Job saved!")
    else:
        await query.answer("ℹ️ Job already saved.")


async def jobs_filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the job filter menu."""
    query = update.callback_query
    await query.answer()
    
    filters = context.user_data.get("job_filters", {})
    from utils import keyboards
    from utils import messages
    kb = keyboards.filter_menu_keyboard(filters)
    
    msg = "⚙️ *Filter Jobs*\nSelect your preferences below:"
    await query.edit_message_text(messages.escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")


async def handle_filter_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle a specific filter and refresh the menu."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    filters = context.user_data.get("job_filters", {})
    
    if data == "filter_clear":
        context.user_data["job_filters"] = {}
    elif data.startswith("filter_"):
        parts = data.split("_")
        if len(parts) >= 3:
            category = parts[1]
            val = "_".join(parts[2:])
            filters[category] = val
            context.user_data["job_filters"] = filters
            
    # Refresh menu
    from utils import keyboards
    from utils import messages
    kb = keyboards.filter_menu_keyboard(context.user_data.get("job_filters", {}))
    msg = "⚙️ *Filter Jobs*\nSelect your preferences below:"
    try:
        await query.edit_message_text(messages.escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")
    except Exception:
        pass # message not modified


async def remind_me_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ⏳ Remind Me for a regular (scraped) job.
    Saves the job and confirms with a toast. The scheduler will nudge the user at 6:30 PM."""
    query = update.callback_query
    user_id = update.effective_user.id
    # callback_data format: remind_job_<job_id>
    job_id = int(query.data.split("_")[-1])

    saved = await save_job(user_id, job_id)
    if saved:
        await query.answer("⏳ Saved! I'll remind you to apply at 6:30 PM.", show_alert=True)
    else:
        await query.answer("ℹ️ Already in your saved list — I'll remind you at 6:30 PM.", show_alert=True)


async def remind_me_manual_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ⏳ Remind Me for a manual (admin-curated) job.
    Saves the job and confirms with a toast. The scheduler will nudge the user at 6:30 PM."""
    query = update.callback_query
    user_id = update.effective_user.id
    # callback_data format: remind_manual_<job_id>
    job_id = int(query.data.split("_")[-1])

    saved = await save_manual_job(user_id, job_id)
    if saved:
        await query.answer("⏳ Saved! I'll remind you to apply at 6:30 PM.", show_alert=True)
    else:
        await query.answer("ℹ️ Already in your saved list — I'll remind you at 6:30 PM.", show_alert=True)
