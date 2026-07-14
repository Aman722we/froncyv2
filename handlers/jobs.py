"""
Jobs handlers — view jobs list, job details, and save/unsave jobs.
"""
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from loguru import logger
import asyncio

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
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    if update.callback_query:
        await update.callback_query.answer()

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
    from db.manual_jobs import get_personalized_manual_jobs, get_seen_jobs, count_manual_jobs, log_jobs_sent
    
    seen_jobs = await get_seen_jobs(user_id)
    feed_limit = 8 if plan == "free" else 12

    from datetime import datetime, timedelta, timezone
    # Fetch jobs + freshness count in parallel
    jobs, new_jobs = await asyncio.gather(
        get_personalized_manual_jobs(
            user_dict,
            seen_job_ids=seen_jobs,
            limit=feed_limit,
            exclude_sent_within_days=3,
            max_age_days=10
        ),
        count_new_jobs_since(datetime.now(timezone.utc) - timedelta(hours=24)),
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
    user_id = update.effective_user.id
    await check_and_reset_daily(user_id, get_pool())
    user = await get_user(user_id)

    if not user or not user.get("is_onboarded"):
        msg = "⚠️ Please finish your setup first! Type /start to complete your profile."
        if update.callback_query:
            await update.callback_query.answer()
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
        max_viewable_offset = 6  # 6 additional jobs
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
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")
            return
        display_count = min(5, max_viewable_offset - offset)

    from db.manual_jobs import get_personalized_manual_jobs, get_seen_jobs, count_manual_jobs
    
    # Get active filters
    filters = context.user_data.get("job_filters", {})
    
    # Fetch top 100 personalized jobs to allow in-memory filtering
    # For /jobs list, we DO NOT filter by seen_jobs to ensure pagination stays stable.
    user_dict = {
        "telegram_id": user.get("telegram_id"),
        "skills": user.get("skills") or [],
        "location_pref": user.get("location_pref") or "remote",
        "plan": plan,
        "experience_level": user.get("experience_level") or "0",
        "batch_year": user.get("batch_year"),
        "role_pref": user.get("role_pref") or "fullstack",
    }
    import asyncio
    
    # Run independent DB queries concurrently to slash network latency
    seen_jobs, total_active_jobs = await asyncio.gather(
        get_seen_jobs(user_id),
        count_manual_jobs()
    )
    
    all_jobs = await get_personalized_manual_jobs(user_dict, limit=100)
    
    # Filter out seen_jobs manually here (since we removed it from the args above)
    all_jobs = [j for j in all_jobs if j["id"] not in seen_jobs]
    
    # Apply filters
    filtered_jobs = []
    f_exp = filters.get("exp", "any")
    f_time = filters.get("time", "any")
    f_match = filters.get("match", "any")
    f_loc = filters.get("loc", "any")
    
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    for job in all_jobs:
        # 1. Experience Filter
        job_exp = job.get("min_yoe", 0)
        if f_exp != "any":
            if f_exp == "0" and job_exp > 0: continue
            elif f_exp == "1" and job_exp != 1: continue
            
        # 2. Location Filter
        if f_loc != "any":
            job_loc = (job.get("location") or "remote").lower()
            if f_loc == "remote" and "remote" not in job_loc: continue
            if f_loc == "onsite" and "remote" in job_loc: continue

        # 3. Recency Filter
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
            

        filtered_jobs.append(job)
        
    total_filtered = len(filtered_jobs)
    page_jobs = filtered_jobs[offset:offset+display_count]

    force_new = context.user_data.pop("force_new_message", False)
    
    if not page_jobs:
        if page > 1: msg = messages.no_jobs_found()
        else: msg = messages.no_jobs_found()
        back_kb = keyboards.InlineKeyboardMarkup([[
            keyboards.InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu"),
            keyboards.InlineKeyboardButton("⚙️ Filters", callback_data="jobs_filter_menu")
        ]])
        if update.callback_query and not force_new:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg, reply_markup=back_kb, parse_mode="MarkdownV2")
        else:
            if update.callback_query:
                await update.callback_query.answer()
                await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=msg, reply_markup=back_kb, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(msg, reply_markup=back_kb, parse_mode="MarkdownV2")
        return

    msg = messages.format_job_list_message(page_jobs, plan, total_filtered, user=user)
    kb = keyboards.job_list_keyboard(page_jobs, plan, total_filtered, page)

    if update.callback_query and not force_new:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)
    else:
        if update.callback_query:
            await update.callback_query.answer()
            await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)
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

    if query.message and query.message.document:
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=user_id,
            text=msg,
            reply_markup=kb,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
    else:
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


# ─────────────────────────────────────────────────────────
# Apply Smart — One-Click Application Kit
# ─────────────────────────────────────────────────────────

# Daily limits per plan
APPLY_SMART_LIMITS = {
    "free": 1,
    "trial": 5,
    "pro": 10,
}


async def apply_smart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 🚀 Apply Smart button — triggers full async application kit generation."""
    query = update.callback_query
    user_id = update.effective_user.id
    job_id = int(query.data.split("_")[-1])

    await query.answer()

    # ── 1. Fetch user & plan ──────────────────────────────
    user = await get_user(user_id)
    if not user:
        await query.edit_message_text("⚠️ User not found. Please type /start to set up your profile.")
        return

    plan = get_effective_plan(user)
    resume_text = user.get("resume_text")

    if not resume_text:
        await query.answer(
            "⚠️ Upload your resume first! Go to ⚙️ Settings → Resume.",
            show_alert=True,
        )
        return

    # ── 2. Check daily limit ──────────────────────────────
    from db.users import get_apply_smart_usage, increment_apply_smart_used
    usage = await get_apply_smart_usage(user_id)
    limit = APPLY_SMART_LIMITS.get(plan, 1)
    used = usage.get("used", 0)

    if used >= limit:
        limit_msg = {
            "free": "Free users get 1 Apply Smart per day.\n\n💎 Upgrade to Pro for 10 per day!",
            "trial": f"Trial users get {limit} Apply Smarts per day. You've used all {limit} today!",
            "pro": f"Pro users get {limit} Apply Smarts per day. You've used all {limit} today!",
        }.get(plan, "You've hit your daily Apply Smart limit.")
        await query.answer(f"🚫 {limit_msg}", show_alert=True)
        return

    # ── 3. Fetch job + HM details ─────────────────────────
    job = await get_manual_job_by_id(job_id)
    if not job:
        await query.answer("⚠️ Job not found.", show_alert=True)
        return

    hm_name = job.get("hm_name")
    hm_role = job.get("hm_role")
    hm_linkedin = job.get("hm_linkedin")
    hm_email = job.get("hm_email")
    has_linkedin = bool(hm_name and hm_linkedin)
    has_email = bool(hm_name and hm_email)

    # Build job description for the LLM
    job_desc = (
        f"Job Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Skills Required: {', '.join(job.get('skills', []))}\n"
        f"Experience: {job.get('min_yoe', 0)} years\n"
        f"Salary: {job.get('salary', 'Not disclosed')}\n"
    )

    # ── 4. Instantly respond — free the user to browse ────
    steps = ["✅ ATS Resume", "✅ Cover Letter"]
    if has_linkedin:
        steps.append("✅ LinkedIn Connection Note + DM")
    if has_email:
        steps.append("✅ Cold Email")
    steps.append("✅ Application Tracked + Follow-up Reminder (3 days)")

    from utils.helpers import escape_md
    steps_text = "\n".join(f"  {s}" for s in steps)

    explore_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔍 Explore Other Jobs", callback_data="explore_loading_jobs")
    ]])

    company_name = escape_md(job.get('company', 'this company'))
    
    loading_msg = await query.edit_message_text(
        f"🚀 *Apply Smart Engine Starting\\!*\n\n"
        f"Building your complete application kit for *{company_name}*\\.\n\n"
        f"This takes \\~8 minutes\\. Feel free to browse other jobs — I'll ping you the moment it's ready\\! 🔔\n\n"
        f"*What's being generated:*\n{escape_md(steps_text)}",
        parse_mode="MarkdownV2",
        reply_markup=explore_kb,
    )

    # Increment counter immediately (prevents double-clicks)
    await increment_apply_smart_used(user_id)

    # ── 5. Kick off background generation ─────────────────
    async def _generate_kit():
        try:
            from services.llm_service import (
                extract_resume_json, optimize_resume_bullets,
                generate_cover_letter, generate_outreach_templates, LLMMode,
                generate_ats_analysis,
            )
            from services.resume_builder import compile_resume_pdf
            import io as _io

            # Step 1a: ATS Analysis to get missing keywords
            ats_raw = await generate_ats_analysis(
                resume_text=resume_text,
                job_description=job_desc,
                mode=LLMMode.QUALITY,
            )
            import json as _json
            try:
                ats_result = _json.loads(ats_raw)
            except Exception:
                ats_result = {}
            missing_keywords = ats_result.get("missing_soft_tech_skills", [])

            # Step 1b: Extract resume JSON
            resume_json = await extract_resume_json(resume_text)

            # Step 1c: Optimize bullets with keywords
            optimized_json = await optimize_resume_bullets(resume_json, job_desc, missing_keywords)

            # Step 1d: Compile PDF
            pdf_bytes = await compile_resume_pdf(optimized_json)

            # Step 2: Cover Letter
            cover_letter = await generate_cover_letter(
                resume_text=resume_text,
                job_description=job_desc,
                mode=LLMMode.QUALITY,
            )

            # Step 3: Outreach (dynamic)
            outreach = {}
            if has_linkedin or has_email:
                outreach = await generate_outreach_templates(
                    resume_text=resume_text,
                    job_description=job_desc,
                    hm_name=hm_name or "Hiring Manager",
                    hm_role=hm_role or "Hiring Manager",
                    company=job.get("company", "the company"),
                    generate_linkedin=has_linkedin,
                    generate_email=has_email,
                )

            # Step 4: Track application + set reminder
            from db.connection import get_pool as _get_pool
            from datetime import datetime, timedelta, timezone as _tz
            pool = _get_pool()
            async with pool.acquire() as conn:
                app_id = await conn.fetchval(
                    "SELECT id FROM applications WHERE telegram_id = $1 AND job_id = $2 AND is_manual = TRUE",
                    user_id, job_id
                )
                if not app_id:
                    app_id = await conn.fetchval(
                        """
                        INSERT INTO applications (telegram_id, job_id, status, is_manual)
                        VALUES ($1, $2, 'tracked', TRUE)
                        RETURNING id
                        """,
                        user_id, job_id,
                    )
                
                if app_id:
                    rem_exists = await conn.fetchval("SELECT id FROM reminders WHERE application_id = $1", app_id)
                    if not rem_exists:
                        remind_at = datetime.now(_tz.utc) + timedelta(days=3)
                        await conn.execute(
                            """
                            INSERT INTO reminders (telegram_id, application_id, remind_at, reminder_type)
                            VALUES ($1, $2, $3, 'followup')
                            """,
                            user_id, app_id, remind_at,
                        )

            # Step 5: Send the final payload
            company = job.get("company", "Company")

            # Send ATS Resume PDF
            name_slug = resume_json.get("name", "resume").replace(" ", "_")
            filename = f"{name_slug}_ATS_{company.replace(' ', '_')}.pdf"
            await context.bot.send_document(
                chat_id=user_id,
                document=_io.BytesIO(pdf_bytes),
                filename=filename,
                caption=(
                    f"📄 ATS-Optimized Resume for {company}\n"
                    f"Keywords added: {', '.join(missing_keywords[:5]) if missing_keywords else 'general optimization'}\n\n"
                    "Your Apply Smart Kit continues below 👇"
                ),
            )

            # Build the outreach section
            outreach_lines = []
            if outreach:
                outreach_lines.append(f"\n\n👤 Hiring Manager: {hm_name or 'N/A'} ({hm_role or 'N/A'})")
                if hm_linkedin:
                    outreach_lines.append(f"🔗 LinkedIn: {hm_linkedin}")
                if hm_email:
                    outreach_lines.append(f"📧 Email: {hm_email}")
                if outreach.get("connection_note"):
                    outreach_lines.append(f"\n📌 Connection Note (<200 chars):\n\"{outreach['connection_note'][:200]}\"")
                if outreach.get("linkedin_dm"):
                    outreach_lines.append(f"\n💬 LinkedIn DM:\n{outreach['linkedin_dm']}")
                if outreach.get("cold_email"):
                    outreach_lines.append(f"\n📧 Cold Email:\n{outreach['cold_email']}")

            outreach_text = "\n".join(outreach_lines)

            # Build full cover letter + outreach message (plain text to avoid MarkdownV2 escaping issues)
            full_msg = (
                f"🎯 Apply Smart Kit Ready for {company}!\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✍️ Cover Letter:\n\n{cover_letter}\n"
                f"{outreach_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Application tracked!\n"
                f"⏰ Follow-up reminder set for 3 days from now.\n\n"
                f"Good luck! 🚀"
            )

            MAX_LEN = 4096
            if len(full_msg) > MAX_LEN:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✍️ Cover Letter for {company}:\n\n{cover_letter}",
                )
                if outreach_text:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"👤 Outreach Templates:{outreach_text}\n\n✅ Application tracked! ⏰ Follow-up in 3 days.",
                    )
                await context.bot.send_message(
                    chat_id=user_id,
                    text="✅ Application tracked! ⏰ Follow-up reminder set for 3 days from now. Good luck! 🚀",
                )
            else:
                await context.bot.send_message(chat_id=user_id, text=full_msg)

        except Exception as e:
            logger.error(f"Apply Smart generation failed for user {user_id}, job {job_id}: {e}")
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ Oops! Something went wrong while generating your Apply Kit. "
                    "Your usage counter has still been incremented. "
                    "Please try again in a few minutes or contact support."
                ),
            )

    asyncio.create_task(_generate_kit())

