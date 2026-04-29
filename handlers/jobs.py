"""
Jobs handlers — view jobs list, job details, and save/unsave jobs.
"""
from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger

from db.users import get_user, increment_jobs_seen
from db.jobs import get_job_by_id, save_job, unsave_job, save_manual_job, unsave_manual_job
from db.manual_jobs import get_manual_jobs, get_manual_job_by_id, count_manual_jobs
from db.connection import get_pool
from services.reset_service import check_and_reset_daily
from utils.limits import get_limit
from utils import keyboards, messages


async def view_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /jobs command and 'View Jobs' / pagination buttons."""
    user_id = update.effective_user.id
    await check_and_reset_daily(user_id, get_pool())
    user = await get_user(user_id)

    if not user:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Please /start first.")
        else:
            await update.message.reply_text("Please /start first.")
        return

    plan = user.get("plan", "free")
    
    # Determine page number
    page = 1
    if update.callback_query and update.callback_query.data.startswith("jobs_page_"):
        page = int(update.callback_query.data.split("_")[-1])

    limit = get_limit(plan, "jobs_per_day")
    jobs_seen_today = user.get("jobs_seen_today", 0)
    offset = (page - 1) * 5
    display_count = 5

    # Free users: block pagination past their daily allowance
    if plan == "free":
        max_viewable_offset = limit  # e.g. 5 for free
        if offset >= max_viewable_offset:
            msg = (
                "⚠️ You've seen your 5 free jobs for today.\n"
                "Fresh jobs reset at midnight.\n\n"
                "Upgrade to Pro (₹99/mo) for unlimited \n"
                "jobs every day + 10 cover letters/day."
            )
            kb = keyboards.InlineKeyboardMarkup([
                [keyboards.InlineKeyboardButton("💎 Upgrade for ₹99/mo", callback_data="upgrade_pro")],
                [keyboards.InlineKeyboardButton("⏰ Remind me tomorrow", callback_data="back_menu")]
            ])
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(messages.escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(messages.escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")
            return
        display_count = min(5, max_viewable_offset - offset)

    from db.manual_jobs import get_personalized_manual_jobs
    
    # Get active filters
    filters = context.user_data.get("job_filters", {})
    
    # Fetch top 100 personalized jobs to allow in-memory filtering
    # user dict requires correct keys:
    user_dict = {
        "telegram_id": user.get("telegram_id"),
        "skills": user.get("skills") or [],
        "location_pref": user.get("location_pref") or "remote",
        "plan": plan,
        "experience_level": user.get("experience_level") or "0",
        "batch_year": user.get("batch_year"),
    }
    all_jobs = await get_personalized_manual_jobs(user_dict, limit=100)
    
    # Apply filters
    filtered_jobs = []
    f_exp = filters.get("exp", "any")
    f_time = filters.get("time", "any")
    f_match = filters.get("match", "any")
    f_role = filters.get("role", "any")
    
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
        if f_role != "any":
            title_lower = job.get("title", "").lower()
            if f_role == "frontend" and "frontend" not in title_lower and "react" not in title_lower and "angular" not in title_lower and "vue" not in title_lower: continue
            elif f_role == "backend" and "backend" not in title_lower and "node" not in title_lower and "python" not in title_lower and "java" not in title_lower: continue
            elif f_role == "fullstack" and "fullstack" not in title_lower and "full stack" not in title_lower: continue
            
        filtered_jobs.append(job)
        
    total_count = len(filtered_jobs)
    
    # Paginate the filtered list
    jobs = filtered_jobs[offset : offset + display_count]

    # For free users, cap the visible total so pagination stays within their limit
    if plan == "free":
        total_count = min(total_count, limit)

    if not jobs:
        msg = messages.no_jobs_found()
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

    msg = messages.format_job_list_message(jobs, plan, total_count, user=user)
    kb = keyboards.job_list_keyboard(jobs, plan, total_count, page)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)

    # Only increment counter on first view of the day (not on re-views)
    if jobs_seen_today == 0 and page == 1:
        await increment_jobs_seen(user_id, len(jobs))


async def view_job_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show details for a specific job."""
    query = update.callback_query
    await query.answer()

    # Data format: job_view_123 or manual_view_123 or job_view_123_saved
    data_parts = query.data.split("_")
    
    from_saved = False
    if data_parts[-1] == "saved":
        from_saved = True
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
    user = await get_user(user_id)
    plan = user.get("plan", "free")
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
    kb = keyboards.job_detail_keyboard(job, plan=plan, score=score, from_saved=from_saved)

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
