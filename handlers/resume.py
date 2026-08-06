"""
Resume and ATS Analyzer handlers.
"""
import io
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from loguru import logger

from db.users import get_user, check_ats_limit, increment_ats_check
from db.tracker import log_ai_usage
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
            f"Paste the full Job Description below\\. \\({checks_text}\\)",
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
        jd_text = (update.message.text or update.message.caption or "").strip()

        await update.message.reply_text(r"⏳ Analyzing your resume with AI — this takes about 20 seconds\.\.\.", parse_mode="MarkdownV2")

        # Always use QUALITY (70B) for ATS — 8B doesn’t reliably output strict JSON
        result = await analyze_resume_match(resume_text, jd_text, mode=LLMMode.QUALITY)
        msg = messages.ats_result(result)

        # Increment counter AFTER successful analysis
        await increment_ats_check(user_id)
        await log_ai_usage(user_id, "ats_check")

        # Build keyboard — upsell for free users, always show Back button
        if plan not in PRO_PLANS:
            result_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Get 5 checks/day — Pro for ₹99/mo", callback_data="upgrade_pro")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
            ])
        else:
            result_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📄 My Resume", callback_data="menu_resume")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
            ])
        await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=result_kb)
        # Store JD in context for the PDF generator (manual ATS flow)
        context.user_data["last_ats_jd"] = jd_text if 'jd_text' in dir() else update.message.text
        context.user_data["last_ats_result"] = result

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
        await log_ai_usage(user_id, "ats_check")

        from utils.keyboards import InlineKeyboardMarkup as KB, InlineKeyboardButton as IKB

        # Correct 'Back to Job' callback depending on scraped vs manual
        back_cb = f"manual_view_{job_id}" if is_manual else f"job_view_{job_id}"
        pdf_cb = f"gen_ats_pdf_manual_{job_id}" if is_manual else f"gen_ats_pdf_{job_id}"

        # Store ATS result and JD in context for the PDF generator
        context.user_data["last_ats_jd"] = jd_text
        context.user_data["last_ats_result"] = result
        context.user_data["last_ats_job_id"] = job_id
        context.user_data["last_ats_is_manual"] = is_manual

        # Add upsell only for free users; always add the PDF generator button
        if plan not in PRO_PLANS:
            back_kb = KB([
                [IKB("✨ Create ATS-Optimized Resume", callback_data=pdf_cb)],
                [IKB("💎 Get 5 checks/day — Pro for ₹99/mo", callback_data="upgrade_pro")],
                [IKB("🔙 Back to Job", callback_data=back_cb)]
            ])
        else:
            back_kb = KB([
                [IKB("✨ Create ATS-Optimized Resume", callback_data=pdf_cb)],
                [IKB("🔙 Back to Job", callback_data=back_cb)]
            ])

        await query.edit_message_text(msg, parse_mode="MarkdownV2", reply_markup=back_kb)
    except Exception as e:
        logger.exception(f"ATS job analysis failed: {e}")
        await query.edit_message_text(
            "⚠️ Analysis failed\\. Please try again\\.",
            parse_mode="MarkdownV2"
        )


async def generate_ats_pdf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle '✨ Apply these changes — Generate PDF' button from the ATS result screen.
    Extracts resume JSON, optimizes bullets with the job's missing keywords,
    compiles a PDF via LaTeX, and sends it directly to the user in Telegram.
    """
    query = update.callback_query
    await query.answer("🚀 Starting PDF generation...")

    user_id = update.effective_user.id
    user = await get_user(user_id)

    if not user or not user.get("resume_text"):
        await query.message.reply_text(
            "📄 Please upload your resume first with /resume\\.",
            parse_mode="MarkdownV2"
        )
        return

    # Parse job_id from callback: gen_ats_pdf_<job_id> or gen_ats_pdf_manual_<job_id>
    data = query.data  # e.g. "gen_ats_pdf_42" or "gen_ats_pdf_manual_42"
    is_manual = "manual" in data
    job_id = int(data.split("_")[-1])

    # Retrieve cached ATS result and JD from context
    ats_result = context.user_data.get("last_ats_result", {})
    jd_text = context.user_data.get("last_ats_jd", "")
    
    # CRITICAL: We only pass soft technical skills to the optimizer to prevent hallucinating 
    # entirely new programming languages or frameworks that the candidate doesn't know.
    missing_keywords = ats_result.get("missing_soft_tech_skills", [])

    if is_manual:
        job = await get_manual_job_by_id(job_id)
    else:
        job = await get_job_by_id(job_id)
        
    if not job:
        job = {}

    # If no cached JD, fall back to fetching the job from DB
    if not jd_text and job:
        jd_text = (
            f"Job Title: {job.get('title', '')}\n"
            f"Company: {job.get('company', '')}\n"
            f"Skills: {', '.join(job.get('skills', []))}"
        )

    # ── Stage 1: Extract resume JSON ──────────────────────────────────────
    back_cb = f"explore_loading_jobs"
    loading_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Explore Other Jobs", callback_data=back_cb)
    ]])
    
    # Reset navigation state
    context.user_data["navigated_away_from_loading"] = False
    
    async def update_loading_msg(step_text: str):
        if not context.user_data.get("navigated_away_from_loading"):
            try:
                full_text = (
                    f"⚙️ *Generating your ATS Resume\\.\\.\\.*\n\n{step_text}\n\n"
                    r"_This requires heavy AI reasoning and can take 2\-3 minutes\. "
                    r"You don't need to wait here, feel free to explore other jobs, and we'll send the PDF here when it's ready\!_"
                )
                await query.edit_message_text(
                    full_text,
                    reply_markup=loading_kb,
                    parse_mode="MarkdownV2"
                )
            except Exception:
                pass

    await update_loading_msg(r"✅ *Step 1 of 3: Parsing your resume profile\.\.\.*")

    from services.llm_service import extract_resume_json, optimize_resume_bullets
    from services.resume_builder import compile_resume_pdf

    try:
        resume_json = await extract_resume_json(user["resume_text"])
    except Exception as e:
        logger.error(f"Resume JSON extraction failed: {e}")
        await query.edit_message_text(
            r"⚠️ Couldn't parse your resume\. Please try re\-uploading your PDF with /resume\.",
            parse_mode="MarkdownV2"
        )
        return

    # Check for missing critical fields and ask user
    missing_fields = []
    if not resume_json.get("email"):
        missing_fields.append("email address")
    if not resume_json.get("name"):
        missing_fields.append("full name")

    if missing_fields:
        fields_str = " and ".join(missing_fields)
        context.user_data["resume_json_draft"] = resume_json
        context.user_data["pdf_jd_text"] = jd_text
        context.user_data["pdf_missing_keywords"] = missing_keywords
        context.user_data["pdf_job_id"] = job_id
        context.user_data["pdf_is_manual"] = is_manual
        await query.edit_message_text(
            f"👋 Your resume is missing your {fields_str}\\."
            r" Please reply with: `Your Name | your@email.com`",
            parse_mode="MarkdownV2"
        )
        context.user_data["waiting_for_resume_details"] = True
        return

    # ── Stage 2: Optimize bullets ─────────────────────────────────────────
    await update_loading_msg(r"🎯 *Step 2 of 3: Optimizing keywords for this job\.\.\.*")

    try:
        optimized_json = await optimize_resume_bullets(resume_json, jd_text, missing_keywords)
    except Exception as e:
        logger.warning(f"Bullet optimization failed, using original: {e}")
        optimized_json = resume_json  # Graceful fallback

    # ── Stage 3: Compile PDF ──────────────────────────────────────────────
    await update_loading_msg(r"📄 *Step 3 of 3: Compiling your ATS PDF\.\.\.*\n_This takes about 15 seconds\._")
    
    # Save optimized json for LaTeX export
    context.user_data["last_optimized_json"] = optimized_json
    context.user_data["pdf_job_id"] = job_id
    context.user_data["pdf_is_manual"] = is_manual

    try:
        pdf_bytes = await compile_resume_pdf(optimized_json)
    except Exception as e:
        logger.error(f"PDF compilation failed: {e}")
        await query.edit_message_text(
            "⚠️ PDF generation failed\\. Our team has been notified\\. Please try again in a few minutes\\.",
            parse_mode="MarkdownV2"
        )
        return

    # ── Send PDF ──────────────────────────────────────────────────────────
    name_slug = resume_json.get("name", "resume").replace(" ", "_")
    company_name = job.get("company", "Company").replace(" ", "_").replace("/", "_")
    filename = f"{name_slug}_ATS_{company_name}.pdf"

    await query.edit_message_text(
        r"✅ *Your ATS\-optimized resume is ready\!*" "\n\n"
        r"_Your bullet points have been rewritten to match this job's keywords\._",
        parse_mode="MarkdownV2"
    )

    latex_cb = f"get_latex_{job_id}"
    back_cb = f"manual_view_{job_id}" if is_manual else f"job_view_{job_id}"
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Get LaTeX Code", callback_data=latex_cb)],
        [InlineKeyboardButton("🔙 Back to Job", callback_data=back_cb)]
    ])

    await query.message.reply_document(
        document=io.BytesIO(pdf_bytes),
        filename=filename,
        caption=(
            f"🎯 ATS-Optimized Resume for {job.get('company', 'Company')}\n"
            f"Keywords added: {', '.join(missing_keywords[:5]) if missing_keywords else 'general optimization'}\n\n"
            "Good luck with your application! 🚀\n\n"
            "Need to make a tiny tweak? Click 'Get LaTeX Code' below and paste it into Overleaf."
        ),
        reply_markup=reply_markup
    )

    logger.info(f"ATS PDF sent to user {user_id}: {filename} ({len(pdf_bytes)} bytes)")

async def get_latex_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the raw LaTeX source code to the user."""
    query = update.callback_query
    await query.answer("Preparing LaTeX code...")

    # Remove the buttons from the original PDF message
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Failed to remove markup from PDF: {e}")

    optimized_json = context.user_data.get("last_optimized_json")
    if not optimized_json:
        await context.bot.send_message(chat_id=query.message.chat_id, text="LaTeX code expired. Please generate the PDF again.")
        return

    from services.resume_builder import _render_latex
    import io
    latex_source = _render_latex(optimized_json, font_size="11pt")
    
    name_slug = optimized_json.get("name", "resume").replace(" ", "_")
    filename = f"{name_slug}_resume_source.tex"
    
    job_id = context.user_data.get("pdf_job_id")
    is_manual = context.user_data.get("pdf_is_manual", False)
    
    reply_markup = None
    if job_id:
        back_cb = f"manual_view_{job_id}" if is_manual else f"job_view_{job_id}"
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back to Job", callback_data=back_cb)
        ]])

    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=io.BytesIO(latex_source.encode("utf-8")),
        filename=filename,
        caption="📄 Here is your raw LaTeX source code! Paste this into Overleaf.com to make manual adjustments.",
        reply_markup=reply_markup
    )

async def explore_loading_jobs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the 'Explore Other Jobs' button during ATS loading."""
    query = update.callback_query
    await query.answer()
    
    # Remove the explore button so the loading message becomes static text
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
        
    context.user_data["navigated_away_from_loading"] = True
    context.user_data["force_new_message"] = True
    
    from handlers.jobs import view_jobs
    await view_jobs(update, context)


async def replace_resume_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Replace' button from /resume menu — prompt user to send a new PDF."""
    query = update.callback_query
    await query.answer()
    context.user_data["waiting_for_replace_resume"] = True
    await query.edit_message_text(
        "📎 Send me your new resume as a PDF file (max 5MB)."
    )


async def replace_resume_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process the new PDF when replacing an existing resume.

    Design principle: NEVER show a generic error. If anything fails at any step,
    we fall through to showing the Complex Layout Detected screen so the user
    always has a path forward (re-upload or request manual fix).
    """
    if not context.user_data.get("waiting_for_replace_resume") and \
       not context.user_data.get("waiting_for_fixresume_upload"):
        return

    document = update.message.document
    if not document or not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("⚠️ Please upload a PDF file.", parse_mode="HTML")
        return

    if document.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("⚠️ File too large. Maximum size is 5MB.", parse_mode="HTML")
        return

    # ── Admin uploading a fixed resume on behalf of a user ────────────
    if context.user_data.get("waiting_for_fixresume_upload"):
        await _admin_fixresume_receive(update, context, document)
        return

    context.user_data["waiting_for_replace_resume"] = False

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from services.resume_parser import save_resume_file, extract_text_from_pdf
    from services.llm_service import check_resume_parseable
    from db.users import update_resume

    user_id = update.effective_user.id

    # ── Step 1: Show progress indicator ───────────────────────────────
    progress_msg = None
    try:
        progress_msg = await update.message.reply_text(
            "⏳ Checking your resume... (~5 seconds)"
        )
    except Exception:
        pass  # Progress message is cosmetic, never fail here

    # ── Step 2: Download & save the PDF file ──────────────────────────
    raw_bytes = None
    saved_path = None
    try:
        file = await document.get_file()
        file_bytes = await file.download_as_bytearray()
        raw_bytes = bytes(file_bytes)
        saved_path = save_resume_file(user_id, raw_bytes, document.file_name)
    except Exception as e:
        logger.error(f"PDF download/save failed for user {user_id}: {e}")
        # Can't even save the file — show a real error (network issue, not user fault)
        if progress_msg:
            try: await progress_msg.delete()
            except Exception: pass
        await update.message.reply_text(
            "⚠️ Failed to download your file. Please check your connection and try again."
        )
        return

    # ── Step 3: Extract text from PDF ─────────────────────────────────
    resume_text = ""
    try:
        resume_text = extract_text_from_pdf(saved_path) or ""
        resume_text = resume_text.encode("utf-8", errors="ignore").decode("utf-8")
        resume_text = resume_text.replace("\x00", "")
    except Exception as e:
        logger.warning(f"PDF text extraction failed for user {user_id}: {e}")
        resume_text = ""  # Extraction failure → force complex layout path below

    # ── Step 4: AI parseability check ─────────────────────────────────
    is_parseable = False
    try:
        if resume_text.strip():
            is_parseable = await check_resume_parseable(resume_text)
        else:
            is_parseable = False  # Empty text → definitely not parseable
    except Exception as e:
        logger.warning(f"AI parseability check failed for user {user_id}: {e}")
        is_parseable = False  # Any AI failure → assume complex layout

    # ── Step 5: Delete progress message ───────────────────────────────
    if progress_msg:
        try: await progress_msg.delete()
        except Exception: pass

    # ── Step 6: Branch on result ──────────────────────────────────────
    if is_parseable:
        # ✅ Resume is clean — save to DB and confirm
        try:
            await update_resume(user_id, resume_text, document.file_name)
        except Exception as e:
            logger.error(f"update_resume DB write failed for user {user_id}: {e}")
            await update.message.reply_text(
                "⚠️ Your resume was read successfully but we had a database error saving it. Please try again."
            )
            return

        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]])
        await update.message.reply_text(
            messages.resume_uploaded_success(document.file_name),
            parse_mode="MarkdownV2",
            reply_markup=back_kb,
        )
    else:
        # ❌ Complex layout (or any failure) — show choice to user
        logger.warning(f"User {user_id} resume flagged as complex: {document.file_name}")

        # Stash raw bytes and text in context for the callback handlers
        context.user_data["pending_raw_resume_bytes"] = raw_bytes
        context.user_data["pending_resume_filename"] = document.file_name
        context.user_data["pending_resume_text"] = resume_text

        choice_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 I'll upload a standard PDF", callback_data="resume_upload_new")],
            [InlineKeyboardButton("⏳ Request Free Manual Fix (2–4 hrs)", callback_data="resume_manual_fix")],
        ])
        await update.message.reply_text(
            "⚠️ <b>Complex Layout Detected</b>\n\n"
            "Our AI couldn't fully read your resume structure. "
            "This usually happens with multi-column layouts, tables, or graphics.\n\n"
            "<b>Why does this matter?</b> Features like Apply Smart, ATS Resume, and Cover Letter "
            "work best when we can read every bullet point in your resume.\n\n"
            "<b>What would you like to do?</b>",
            parse_mode="HTML",
            reply_markup=choice_kb,
        )


async def resume_upload_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User chose to upload a cleaner, standard PDF. Re-prompt them."""
    query = update.callback_query
    await query.answer()
    context.user_data["pending_raw_resume_bytes"] = None
    context.user_data["pending_resume_filename"] = None
    context.user_data["pending_resume_text"] = None
    context.user_data["waiting_for_replace_resume"] = True
    await query.edit_message_text(
        "📎 Please upload a <b>single-column, standard</b> PDF resume (max 5MB).\n\n"
        "<b>Tips for an ATS-friendly format:</b>\n"
        "• Use a single-column layout (no tables or text boxes)\n"
        "• Avoid headers/footers, columns, or graphics\n"
        "• Use a simple font like Arial or Calibri\n\n"
        "You can use <a href=\"https://www.overleaf.com/latex/templates\">Overleaf</a> for a free, clean template.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def resume_manual_fix_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User chose to request a free manual fix. Save raw bytes and flag them."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    raw_bytes = context.user_data.get("pending_raw_resume_bytes")
    filename = context.user_data.get("pending_resume_filename", "resume.pdf")
    resume_text = context.user_data.get("pending_resume_text", "")

    from db.users import save_raw_resume_bytes, update_resume
    from config import settings

    try:
        if raw_bytes:
            # Save the raw PDF bytes and flag the user
            await save_raw_resume_bytes(user_id, raw_bytes, filename)
            # Also save whatever text we extracted as a fallback for other features
            if resume_text:
                await update_resume(user_id, resume_text, filename)
        else:
            # Edge case: no bytes (shouldn't happen normally)
            from db.users import set_manual_resume_flag
            await set_manual_resume_flag(user_id, True)

        # Clean up context
        context.user_data["pending_raw_resume_bytes"] = None
        context.user_data["pending_resume_filename"] = None
        context.user_data["pending_resume_text"] = None

        # Notify the user
        await query.edit_message_text(
            "✅ <b>Got it! Your resume is in the queue.</b>\n\n"
            "Our team will manually parse and optimize your resume within <b>2–4 hours</b>.\n"
            "You'll receive a notification here once it's ready — then you can use Apply Smart, "
            "ATS Resume, and Cover Letter with full accuracy!\n\n"
            "In the meantime, you can still browse jobs and save ones you like 🔍",
            parse_mode="HTML",
        )

        # Alert the admin
        user = await __import__("db.users", fromlist=["get_user"]).get_user(user_id)
        first_name = user.get("first_name", "Unknown") if user else "Unknown"
        username = user.get("username", "") if user else ""
        uname_str = f"@{username}" if username else "(no username)"
        try:
            await context.bot.send_message(
                chat_id=settings.ADMIN_TELEGRAM_ID,
                text=(
                    f"🛠 <b>Manual Resume Fix Request</b>\n\n"
                    f"👤 {first_name} {uname_str}\n"
                    f"🆔 <code>{user_id}</code>\n"
                    f"📄 File: {filename}\n\n"
                    f"Use /badresumes to see the queue, then /fixresume {user_id} to fix this user's resume."
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Could not notify admin of manual resume request: {e}")

        logger.info(f"User {user_id} requested manual resume fix for {filename}")

    except Exception as e:
        logger.error(f"Manual resume fix request failed for {user_id}: {e}")
        await query.edit_message_text(
            "⚠️ Something went wrong. Please try again or contact support."
        )


async def _admin_fixresume_receive(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    document,
) -> None:
    """Internal: called when admin uploads a fixed PDF for a target user."""
    target_user_id = context.user_data.get("fixresume_target_user_id")
    if not target_user_id:
        await update.message.reply_text("⚠️ No target user set. Use /fixresume <user_id> first.")
        return

    context.user_data["waiting_for_fixresume_upload"] = False
    context.user_data["fixresume_target_user_id"] = None

    from services.resume_parser import save_resume_file, extract_text_from_pdf
    from db.users import update_resume, set_manual_resume_flag
    from config import settings

    try:
        file = await document.get_file()
        file_bytes = bytes(await file.download_as_bytearray())
        saved_path = save_resume_file(target_user_id, file_bytes, document.file_name)
        resume_text = extract_text_from_pdf(saved_path)

        if resume_text:
            resume_text = resume_text.encode("utf-8", errors="ignore").decode("utf-8")

        # Save the clean resume and clear the flag
        await update_resume(target_user_id, resume_text, document.file_name)
        await set_manual_resume_flag(target_user_id, False)

        # Notify the user their resume is ready
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    "🎉 <b>Great news! Your resume is ready.</b>\n\n"
                    "Our team has manually parsed and optimized your resume. "
                    "You can now use all features — <b>Apply Smart, ATS Resume, Cover Letter</b> — with full accuracy!\n\n"
                    "Tap below to get started:"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 Go to Menu", callback_data="back_menu")],
                ])
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_user_id} of fixed resume: {e}")

        await update.message.reply_text(
            f"✅ Resume fixed for user <code>{target_user_id}</code>! They have been notified.",
            parse_mode="HTML",
        )
        logger.info(f"Admin fixed resume for user {target_user_id}")

    except Exception as e:
        logger.error(f"Admin fixresume failed for user {target_user_id}: {e}")
        await update.message.reply_text(f"❌ Failed to process fixed resume: {e}")
