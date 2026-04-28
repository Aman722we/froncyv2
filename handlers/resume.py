"""
Resume and ATS Analyzer handlers.
"""
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from loguru import logger

from db.users import get_user, check_ats_limit, increment_ats_check
from db.jobs import get_job_by_id
from db.manual_jobs import get_manual_job_by_id
from services.ats_analyzer import analyze_resume_match
from services.llm_service import LLMMode
from utils import keyboards, messages, helpers

# Re-use WAITING_RESUME state from start.py
WAITING_RESUME = 4

# Plans treated as non-free (pro-equivalent or better)
PRO_PLANS = ("pro", "trial", "proplus", "premium")


async def view_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume and Menu -> My Resume."""
    user_id = update.effective_user.id
    user = await get_user(user_id)

    if not user:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Please /start first.")
        else:
            await update.message.reply_text("Please /start first.")
        return

    has_resume = bool(user.get("resume_text"))
    plan = user.get("plan", "free")
    filename = user.get("resume_filename")

    msg = messages.resume_status(filename, has_resume)
    kb = keyboards.resume_keyboard(has_resume, plan)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2")


async def ats_analyze_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to send a Job Description text for ATS analysis."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user = await get_user(user_id)
    plan = user.get("plan", "free")

    # Check resume first (regardless of plan)
    if not user.get("resume_text"):
        await query.edit_message_text(
            r"📄 Please upload your resume first with /resume\." "\n"
            r"I need it to compare against the job description\.",
            parse_mode="MarkdownV2"
        )
        return

    # Check daily limit
    can_run, used_today = await check_ats_limit(user_id, plan)

    if not can_run:
        if plan == "free":
            await query.edit_message_text(
                r"*You've used your 1 free ATS check today\.*\n\n"
                r"Pro users check up to *5 resumes/day* — enough\n"
                r"for every job worth applying to\.\n\n"
                r"Also unlocks: unlimited jobs, 10 cover letters/day,\n"
                r"match scores, and application tracking\.",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 All of this for ₹99/mo", callback_data="upgrade_pro")],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_menu")]
                ])
            )
        else:
            # Pro limit (5/day)
            await query.edit_message_text(
                r"*You've used all 5 ATS checks for today\.*" "\n\n"
                r"Your daily limit resets at midnight\. Come back tomorrow\!",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="back_menu")]
                ])
            )
        return

    # Show message — free users see preview notice, pro/trial see remaining checks
    if plan == "free":
        await query.edit_message_text(
            r"📊 *ATS Resume Analyzer* \— Free Preview" "\n\n"
            r"This is your *1 free check today*\. Paste the full Job Description below and I'll analyze your resume against it with AI\.",
            parse_mode="MarkdownV2"
        )
    else:
        # Pro/Trial: show remaining checks (proplus/premium have unlimited so no counter)
        if plan in ("proplus", "premium"):
            checks_text = "unlimited checks"
        else:
            checks_left = 5 - used_today
            checks_text = f"{checks_left} checks remaining today"
        await query.edit_message_text(
            r"📊 *ATS Resume Analyzer*" "\n\n"
            rf"Paste the full Job Description below\. \({checks_text}\)",
            parse_mode="MarkdownV2"
        )

    context.user_data["waiting_for_ats_jd"] = True


async def ats_analyze_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process the JD text and show ATS score."""
    if not context.user_data.get("waiting_for_ats_jd"):
        return

    context.user_data["waiting_for_ats_jd"] = False

    try:
        user_id = update.effective_user.id
        user = await get_user(user_id)
        plan = user.get("plan", "free")
        resume_text = user.get("resume_text", "")
        jd_text = update.message.text

        await update.message.reply_text(r"⏳ Analyzing with AI — this takes ~20 seconds\.\.\.", parse_mode="MarkdownV2")

        # Always use QUALITY (70B) for ATS — 8B doesn’t reliably output strict JSON
        result = await analyze_resume_match(resume_text, jd_text, mode=LLMMode.QUALITY)
        msg = messages.ats_result(result)

        # Increment counter AFTER successful analysis
        await increment_ats_check(user_id)

        # Upsell nudge only for free users after their one shot
        if plan not in PRO_PLANS:
            upsell_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Get 5 checks/day + full Pro — ₹99/mo", callback_data="upgrade_pro")]
            ])
            await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=upsell_kb)
        else:
            await update.message.reply_text(msg, parse_mode="MarkdownV2")

    except Exception as e:
        logger.exception(f"ATS analysis failed: {e}")
        await update.message.reply_text(
            "⚠️ Something went wrong during analysis\\. Please try again\\.",
            parse_mode="MarkdownV2"
        )


async def ats_analyze_job_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ATS Analyze click from a job detail page — uses job data as JD automatically."""
    query = update.callback_query
    await query.answer("⏳ Running AI analysis...")

    user_id = update.effective_user.id
    user = await get_user(user_id)
    plan = user.get("plan", "free")

    from db.users import check_ats_limit, increment_ats_check
    can_run, used_today = await check_ats_limit(user_id, plan)
    
    if not can_run:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        is_manual = query.data.startswith("manual_")
        job_id_str = query.data.split("_")[-1]
        back_cb = f"manual_view_{job_id_str}" if is_manual else f"job_view_{job_id_str}"
        if plan in PRO_PLANS:
            msg = ("🔒 *ATS Analyzer Limit Reached*\n\n"
                   "You've used your 5 ATS checks for today\\.\n"
                   "Resets at midnight\\! 🔄\n\n"
                   "While you wait — want me to find more\n"
                   "jobs matching your updated resume?")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Find Matching Jobs", callback_data="menu_jobs")],
                [InlineKeyboardButton("🔙 Back to Job", callback_data=back_cb)]
            ])
        else:
            msg = ("🔒 *ATS Analyzer Limit Reached*\n\n"
                   "You've used your 1 free check today\\. Upgrade to Pro for 5 checks/day, "
                   "Pro\\+ for unlimited\\.\n\n"
                   "\\[ 💎 Pro — ₹99/mo \\| Unlimited Apps \\]")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Upgrade to Pro", callback_data="upgrade_pro")],
                [InlineKeyboardButton("🔙 Back to Job", callback_data=back_cb)]
            ])
            
        await query.edit_message_text(
            msg,
            parse_mode="MarkdownV2",
            reply_markup=kb
        )
        return

    resume_text = user.get("resume_text", "")
    if not resume_text:
        await query.edit_message_text(
            "📄 Please upload your resume first with /resume\\.",
            parse_mode="MarkdownV2"
        )
        return

    # Extract job_id from callback_data: ats_job_<id> or manual_ats_job_<id>
    job_id = int(query.data.split("_")[-1])
    is_manual = query.data.startswith("manual_")

    if is_manual:
        job = await get_manual_job_by_id(job_id)
    else:
        job = await get_job_by_id(job_id)
        
    if not job:
        await query.edit_message_text("⚠️ Job not found\\.", parse_mode="MarkdownV2")
        return

    # Build JD: try fetching live page first, fall back to metadata
    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    skills_list = job.get("skills", [])
    salary = job.get("salary", "")
    url = job.get("url", "")

    # Metadata fallback JD
    meta_jd = (
        f"Job Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n"
        f"Required Skills: {', '.join(skills_list)}\n"
        f"Salary: {salary}"
    )

    # Try fetching full JD text from the live URL
    jd_text = meta_jd
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                import re
                raw = resp.text
                # Strip HTML tags
                raw_clean = re.sub(r"<[^>]+>", " ", raw)
                raw_clean = re.sub(r"\s{2,}", " ", raw_clean).strip()
                if len(raw_clean) > 200:
                    jd_text = f"Job Title: {title}\nCompany: {company}\n\n{raw_clean[:3000]}"
    except Exception as fetch_err:
        logger.warning(f"Could not fetch live JD, using metadata fallback: {fetch_err}")

    # Show loading message
    from utils.helpers import escape_md
    await query.edit_message_text(
        f"⏳ *AI ATS Analyzer*\n\n"
        f"Analyzing your resume against *{escape_md(title)}* at *{escape_md(company)}*\\.\\.\\.",
        parse_mode="MarkdownV2"
    )

    try:
        # Always use QUALITY (70B) for ATS — strict JSON output requires the larger model
        result = await analyze_resume_match(resume_text, jd_text, mode=LLMMode.QUALITY)
        from utils.messages import ats_result
        msg = ats_result(result)
        
        await increment_ats_check(user_id)

        from utils.keyboards import InlineKeyboardMarkup as KB, InlineKeyboardButton as IKB
        
        # Correct 'Back to Job' callback depending on scraped vs manual
        back_cb = f"manual_view_{job_id}" if is_manual else f"job_view_{job_id}"

        # Add upsell only for free users
        if plan not in PRO_PLANS:
            back_kb = KB([
                [IKB("💎 Get 5 checks/day — Pro for ₹99/mo", callback_data="upgrade_pro")],
                [IKB("🔙 Back to Job", callback_data=back_cb)]
            ])
        else:
            back_kb = KB([[IKB("🔙 Back to Job", callback_data=back_cb)]])
            
        await query.edit_message_text(msg, parse_mode="MarkdownV2", reply_markup=back_kb)
    except Exception as e:
        logger.exception(f"ATS job analysis failed: {e}")
        await query.edit_message_text(
            "⚠️ Analysis failed\\. Please try again\\.",
            parse_mode="MarkdownV2"
        )


# ──────────────────────────────────────────────
# Replace Resume (standalone — outside onboarding)
# ──────────────────────────────────────────────

async def replace_resume_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Replace' button from /resume menu — prompt user to send a new PDF."""
    query = update.callback_query
    await query.answer()
    context.user_data["waiting_for_replace_resume"] = True
    await query.edit_message_text(
        "📎 Send me your new resume as a PDF file \\(max 5MB\\)\\.",
        parse_mode="MarkdownV2"
    )


async def replace_resume_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process the new PDF when replacing an existing resume."""
    if not context.user_data.get("waiting_for_replace_resume"):
        return

    document = update.message.document
    if not document or not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("⚠️ Please upload a PDF file\\.", parse_mode="MarkdownV2")
        return

    if document.file_size > 5 * 1024 * 1024:
        await update.message.reply_text(
            "⚠️ File too large\\. Maximum size is 5MB\\.", parse_mode="MarkdownV2"
        )
        return

    context.user_data["waiting_for_replace_resume"] = False

    try:
        from services.resume_parser import save_resume_file, extract_text_from_pdf
        from db.users import update_resume

        user_id = update.effective_user.id
        file = await document.get_file()
        file_bytes = await file.download_as_bytearray()
        saved_path = save_resume_file(user_id, bytes(file_bytes), document.file_name)
        resume_text = extract_text_from_pdf(saved_path)
        await update_resume(user_id, resume_text, document.file_name)

        await update.message.reply_text(
            messages.resume_uploaded_success(document.file_name),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        logger.error(f"Replace resume failed: {e}")
        await update.message.reply_text(
            "⚠️ Failed to process your resume\\. Please try again\\.",
            parse_mode="MarkdownV2"
        )
