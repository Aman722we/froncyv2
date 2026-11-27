"""
/start — Onboarding ConversationHandler.
Flow: Welcome → Skills → Role Selection → Experience → Resume Prompt → Complete
"""
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from loguru import logger
from config import settings

from db.users import get_or_create_user, update_user_profile, update_resume, set_onboarded, get_user
from db.connection import get_pool
from services.resume_parser import (
    extract_text_from_pdf,
    extract_text_from_pdf_bytes_safe,
    rank_and_extract_skills,
    extract_skills_hybrid,
    save_resume_file,
)
from utils.validators import is_resume_intent, validate_and_normalize_skills
from services.storage import upload_resume
from db.users import record_resume_consent
from services.pricing_service import start_trial, get_current_pricing
from utils import keyboards, messages
from utils.helpers import escape_md
from utils.admin_notify import notify_admin

# Conversation states
WELCOME, SKILLS, ROLE, WAITING_CUSTOM_SKILL, CONFIRM_SKILLS, EXPERIENCE, LOCATION, BATCH_YEAR, RESUME_PROMPT, WAITING_RESUME, WAITING_CUSTOM_ROLE, WAITING_RESUME_CONSENT = range(12)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — begin onboarding or show main menu if already onboarded."""
    user = update.effective_user
    
    # Get the tenant bot_id (injected by the multi-tenant pre-processor)
    bot_id = context.bot_data.get("bot_id", 1)
    
    # Send instant placeholder to prevent drop-off during DB load
    placeholder = await update.message.reply_text("⏳ Give me a second, setting up your profile...")
    
    # Check if they existed before this exact /start click — scoped to this bot
    is_new_user = (await get_user(user.id, bot_id=bot_id)) is None
    
    db_user = await get_or_create_user(user.id, user.username, user.first_name, bot_id=bot_id)

    if db_user.get("is_deleted"):
        from db.users import restore_user
        await restore_user(user.id)
        db_user = await get_user(user.id, bot_id=bot_id)  # Refresh db_user
        
        await update.message.reply_text(
            "🎉 *Welcome back\\! Your previous data has been restored\\.*",
            parse_mode="MarkdownV2"
        )

    if db_user.get("is_onboarded"):
        # Check if skills need a refresh
        if db_user.get("skills_need_review"):
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            review_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛠️ Refresh My Skills", callback_data="refresh_user_skills")]
            ])
            await update.message.reply_text(
                "👋 <b>Welcome back!</b>\n\n"
                "⚠️ <b>Skills Update Recommended</b>\n"
                "Your profile skills need a quick refresh so our 100-point matcher can deliver accurate job alerts.\n"
                "Tap below to update them in 30 seconds:",
                reply_markup=review_kb,
                parse_mode="HTML"
            )
            await placeholder.delete()
            return ConversationHandler.END

        # Returning user → main menu
        plan = db_user.get("plan", "free")
        upgrade_price = None
        if plan not in ("pro",):
            try:
                from services.pricing_service import get_current_pricing
                pricing = await get_current_pricing(get_pool())
                upgrade_price = pricing.get("current_price")
            except Exception:
                pass
        await update.message.reply_text(
            messages.main_menu(db_user, bot_name=context.bot.first_name),
            reply_markup=keyboards.main_menu_keyboard(plan, upgrade_price=upgrade_price),
            parse_mode="MarkdownV2",
        )
        await placeholder.delete()
        return ConversationHandler.END

    # New user → start onboarding
    context.user_data["selected_skills"] = []

    # Capture referral param (e.g. /start ref_8619554269) or pilot source (e.g. /start li_pilot)
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_") and arg[4:].isdigit():
            referrer_id = int(arg[4:])
            if referrer_id != user.id:  # Can't refer yourself
                context.user_data["referrer_id"] = referrer_id
                # Persist to database so server restarts don't lose the referral
                try:
                    pool = get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE users 
                            SET referred_by = $1 
                            WHERE telegram_id = $2 AND bot_id = $3 AND referred_by IS NULL
                            """,
                            referrer_id, user.id, bot_id
                        )
                except Exception as e:
                    logger.warning(f"Failed to persist referred_by on start: {e}")
        elif arg in ("li_pilot", "pilot") or arg.startswith("li_"):
            context.user_data["signup_source"] = "linkedin_pilot"


    # 🔔 Notify admin ONLY if this is their absolute first time clicking /start
    if is_new_user:
        import html
        first_name_esc = html.escape(user.first_name) if user.first_name else "Unknown"
        username_str = f"@{html.escape(user.username)}" if user.username else "(no username)"
        await notify_admin(
            context.bot,
            f"🆕 <b>New User Joined!</b>\n"
            f"👤 {first_name_esc} {username_str}\n"
            f"🆔 ID: <code>{user.id}</code>"
        )

    # Jump straight to Step 1: Role Selection
    try:
        step1_bar = messages.escape_md("[🟢⚪⚪] Step 1 of 3")
        await update.message.reply_text(
            f"{step1_bar}\n\n"
            "*What kind of tech jobs are you looking for?* 🎯\n\n"
            "Choose your role stream so we can personalise your job feed and application kit\\.",
            reply_markup=keyboards.role_keyboard(prefix="onboard_role_"),
            parse_mode="MarkdownV2",
        )
    except BadRequest as e:
        logger.warning(
            f"Chat unreachable for user {user.id} ({e}). "
            "Scheduling a 5-second delayed role retry."
        )

        async def _retry_role(ctx: ContextTypes.DEFAULT_TYPE) -> None:
            """One-shot job: try sending the role screen one final time."""
            chat_id   = ctx.job.data["chat_id"]
            try:
                step1_bar = messages.escape_md("[🟢⚪⚪] Step 1 of 3")
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=f"{step1_bar}\n\n*What kind of tech jobs are you looking for?* 🎯\n\nChoose your role stream so we can personalise your job feed and application kit\\.",
                    reply_markup=keyboards.role_keyboard(prefix="onboard_role_"),
                    parse_mode="MarkdownV2",
                )
                logger.info(f"Delayed role retry succeeded for user {chat_id}.")
            except Exception as retry_err:
                logger.warning(
                    f"Delayed role retry also failed for user {chat_id}: {retry_err}."
                )

        context.job_queue.run_once(
            _retry_role,
            when=5,
            data={"chat_id": update.effective_chat.id},
            name=f"role_retry_{user.id}",
        )

    await placeholder.delete()
    return ROLE



# welcome_callback removed — onboarding now goes directly to Skills from /start.



async def skill_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle a skill on/off in the selection grid."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get("selected_skills", [])
    # Extract skill name from callback: skill_react, skill_vuejs, etc.
    skill_raw = query.data.replace("skill_", "")

    from utils.keyboards import ALL_SKILLS
    skill_map = {
        s.lower().replace('.', '').replace(' ', '_').replace('/', '_'): s
        for s in ALL_SKILLS
    }

    skill = skill_map.get(skill_raw, skill_raw)

    if skill.lower() in [s.lower() for s in selected]:
        selected = [s for s in selected if s.lower() != skill.lower()]
    else:
        selected.append(skill)

    context.user_data["selected_skills"] = selected

    await query.edit_message_text(
        messages.skills_prompt(),
        reply_markup=keyboards.skills_keyboard(selected),
        parse_mode="MarkdownV2",
    )
    return SKILLS


async def add_custom_skill_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to type their custom skills."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✍️ *Type your custom skills separated by commas*\n"
        "\\(e\\.g\\., Prisma, Redis, GraphQL\\)\n\n"
        "Send your skills below:",
        parse_mode="MarkdownV2"
    )
    return WAITING_CUSTOM_SKILL


async def prompt_experience_step(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None) -> int:
    """Prompt user for years of experience with 1-tap quick buttons or numeric reply."""
    step3_bar = "[🟢🟢🟢] Step 3 of 3"
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    exp_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Fresher (0-1 yr)", callback_data="onboard_exp_0"),
         InlineKeyboardButton("1-3 yrs", callback_data="onboard_exp_2")],
        [InlineKeyboardButton("3-5 yrs", callback_data="onboard_exp_4"),
         InlineKeyboardButton("5+ yrs", callback_data="onboard_exp_6")]
    ])
    text = (
        f"<b>{step3_bar}</b>\n\n"
        "📅 <b>What is your experience level?</b>\n"
        "Tap a button below or type a number of years (e.g. 0, 2, 5):"
    )
    if query:
        await query.edit_message_text(text, reply_markup=exp_kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=exp_kb, parse_mode="HTML")
    return EXPERIENCE


async def custom_skill_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive, validate, and normalize custom typed skills, or catch conversational intent."""
    text = (update.message.text or "").strip()

    # 1. Detect conversational intent asking to upload resume
    if is_resume_intent(text):
        await update.message.reply_text(
            "📄 <b>Yes, absolutely!</b>\n\n"
            "Send your resume as a <b>PDF file</b> (max 5MB) right here, and I'll automatically extract your technical skills.",
            parse_mode="HTML",
        )
        return WAITING_CUSTOM_SKILL

    # 2. Validate and normalize skills
    is_valid, normalized, err_msg = validate_and_normalize_skills(text, max_skills=15)
    if not is_valid:
        import html
        await update.message.reply_text(
            f"⚠️ {html.escape(err_msg or 'Please enter valid technical skills separated by commas.')}",
            parse_mode="HTML",
        )
        return WAITING_CUSTOM_SKILL

    context.user_data["selected_skills"] = normalized
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    await update_user_profile(user_id, bot_id=bot_id, skills=[s.lower() for s in normalized])
    context.user_data["has_resume"] = False

    return await prompt_experience_step(update, context)


async def onboard_upload_resume_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to send their resume PDF for skill extraction."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📎 <b>Send me your resume as a PDF file</b> (max 5MB) right here.\n\n"
        "I will scan it and extract your technical skills for instant job matching!",
        parse_mode="HTML",
    )
    return WAITING_CUSTOM_SKILL


async def resume_doc_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process uploaded resume PDF during Step 2 of onboarding safely off event loop."""
    document = update.message.document
    if not document or not (document.file_name or "").lower().endswith(".pdf"):
        await update.message.reply_text(
            "⚠️ Please upload a <b>PDF file</b> (e.g. resume.pdf).",
            parse_mode="HTML",
        )
        return WAITING_CUSTOM_SKILL

    if document.file_size and document.file_size > 5 * 1024 * 1024:
        await update.message.reply_text(
            "⚠️ File too large. Maximum size is 5MB.",
            parse_mode="HTML",
        )
        return WAITING_CUSTOM_SKILL

    status_msg = await update.message.reply_text("⏳ Analyzing resume and extracting skills...")

    try:
        file = await document.get_file()
        file_bytes = await file.download_as_bytearray()
        raw_bytes = bytes(file_bytes)

        # Safe extraction off event loop with concurrency limit
        resume_text = await extract_text_from_pdf_bytes_safe(raw_bytes)
        role = context.user_data.get("role_pref", "other")
        # RFC-009: 100% Local Deterministic Extraction — zero bytes leave the server
        extracted = rank_and_extract_skills(resume_text, role_pref=role, max_skills=15)

        try:
            await status_msg.delete()
        except Exception:
            pass

        if not extracted:
            await update.message.reply_text(
                "⚠️ We couldn't recognize any technical skills from this PDF.\n\n"
                "Please type your technical skills below separated by commas (e.g. React, Python, AWS):",
                parse_mode="HTML",
            )
            return WAITING_CUSTOM_SKILL

        # Save skills directly to profile
        user_id = update.effective_user.id
        bot_id = context.bot_data.get("bot_id", 1)
        context.user_data["selected_skills"] = extracted
        context.user_data["prev_extracted_skills"] = list(extracted)
        context.user_data["skills_edited"] = False
        context.user_data.pop("_skills_confirmed", None)
        await update_user_profile(user_id, bot_id=bot_id, skills=[s.lower() for s in extracted])

        # RFC-009: Ephemeral model — purge raw bytes & text immediately (never stored)
        del raw_bytes
        del resume_text

        await _send_skills_review(update, context, extracted)
        return CONFIRM_SKILLS

    except Exception as e:
        logger.warning(f"Resume parsing during onboarding failed: {e}")
        try:
            await status_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            "⚠️ Could not extract text from this PDF (it may be password-protected or a scanned image).\n\n"
            "Please type your technical skills below separated by commas (e.g. React, Python, AWS):",
            parse_mode="HTML",
        )
        return WAITING_CUSTOM_SKILL


async def _send_skills_review(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    skills: list[str],
    edit_message: bool = False,
) -> None:
    """Render the extracted/edited skills review prompt with Continue, Edit, and optional Undo."""
    import html
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    skills_preview = ", ".join(skills[:15])
    if len(skills) > 15:
        skills_preview += f" (+{len(skills) - 15} more)"
    escaped_skills = html.escape(skills_preview)

    if len(skills) < 3:
        header = f"⚠️ <b>We found only {len(skills)} skill(s) from your PDF.</b> 📄"
        instruction = (
            "Tap <b>✏️ Edit Skills</b> or type your <b>full comma-separated list</b> below to replace &amp; add more "
            "(e.g. <code>React, Python, SQL</code>)."
        )
    else:
        header = f"✅ <b>Extracted {len(skills)} Skills!</b> 📄"
        instruction = (
            "Do these look accurate? Tap <b>✅ Looks Good</b>, or tap <b>✏️ Edit Skills</b> / type your "
            "<b>full comma-separated list</b> below to replace them. "
            "<i>(You can also change them anytime in Settings.)</i>"
        )

    text = f"{header}\n\n<code>{escaped_skills}</code>\n\n{instruction}"
    buttons = [
        [InlineKeyboardButton("✅ Looks Good, Continue →", callback_data="onboard_skills_ok")],
        [InlineKeyboardButton("✏️ Edit Skills", callback_data="onboard_skills_edit")],
    ]
    if context.user_data.get("skills_edited") and context.user_data.get("prev_extracted_skills"):
        buttons.append([InlineKeyboardButton("↩️ Undo Edit (Restore Extracted)", callback_data="onboard_skills_undo")])

    kb = InlineKeyboardMarkup(buttons)
    if edit_message and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def onboard_skills_ok_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Idempotently confirm extracted/edited skills and advance to Experience step."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    db_user = await get_user(user_id, bot_id=bot_id)
    if (db_user and db_user.get("is_onboarded")) or context.user_data.get("_skills_confirmed"):
        return ConversationHandler.END

    context.user_data["_skills_confirmed"] = True
    return await prompt_experience_step(update, context)


async def onboard_skills_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to type their full corrected comma-separated skill list."""
    import html
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    query = update.callback_query
    await query.answer()

    current = context.user_data.get("selected_skills", [])
    current_str = html.escape(", ".join(current)) if current else "None"
    buttons = []
    if context.user_data.get("prev_extracted_skills"):
        buttons.append([InlineKeyboardButton("↩️ Cancel Edit", callback_data="onboard_skills_undo")])
    kb = InlineKeyboardMarkup(buttons) if buttons else None

    await query.edit_message_text(
        f"✏️ <b>Edit Your Skills</b>\n\n"
        f"Current list:\n<code>{current_str}</code>\n\n"
        f"Send your <b>full corrected comma-separated list</b> below to replace these "
        f"(e.g. <code>React, Python, Docker, SQL</code>):",
        reply_markup=kb,
        parse_mode="HTML",
    )
    return CONFIRM_SKILLS


async def onboard_skills_undo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restore the previously extracted skills list (1-step undo)."""
    query = update.callback_query
    await query.answer("Restored extracted skills!")

    prev = context.user_data.get("prev_extracted_skills") or []
    if not prev:
        return CONFIRM_SKILLS

    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    context.user_data["selected_skills"] = list(prev)
    context.user_data["skills_edited"] = False
    await update_user_profile(user_id, bot_id=bot_id, skills=[s.lower() for s in prev])

    await _send_skills_review(update, context, prev, edit_message=True)
    return CONFIRM_SKILLS


async def confirm_skills_text_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate and replace skills when user types text directly in CONFIRM_SKILLS."""
    import html
    text = (update.message.text or "").strip()

    if is_resume_intent(text):
        await update.message.reply_text(
            "📄 <b>Send your resume as a PDF file</b> (max 5MB) right here to re-extract your skills.",
            parse_mode="HTML",
        )
        return CONFIRM_SKILLS

    is_valid, normalized, err_msg = validate_and_normalize_skills(text, max_skills=15)
    if not is_valid or not normalized:
        await update.message.reply_text(
            f"⚠️ {html.escape(err_msg or 'Please enter valid technical skills separated by commas.')}\n\n"
            f"Send your full comma-separated skill list (e.g. <code>React, Python, SQL</code>):",
            parse_mode="HTML",
        )
        return CONFIRM_SKILLS

    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    context.user_data["selected_skills"] = normalized
    context.user_data["skills_edited"] = True
    await update_user_profile(user_id, bot_id=bot_id, skills=[s.lower() for s in normalized])

    await _send_skills_review(update, context, normalized, edit_message=False)
    return CONFIRM_SKILLS


async def resume_consent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """RFC-009: Gracefully advance any user in legacy WAITING_RESUME_CONSENT state."""
    query = update.callback_query
    if query:
        await query.answer()

    # Clear any stale pending state
    context.user_data.pop("pending_bytes", None)
    context.user_data.pop("pending_resume_text", None)
    context.user_data.pop("pending_filename", None)
    context.user_data.pop("pending_skills", None)

    return await prompt_experience_step(update, context, query=query)


async def experience_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save experience level from button click and complete onboarding."""
    query = update.callback_query
    await query.answer()

    exp_val = query.data.replace("onboard_exp_", "")
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)

    await update_user_profile(user_id, bot_id=bot_id, experience_level=exp_val, location_pref="all")
    context.user_data["experience_level"] = exp_val
    context.user_data["location"] = "all"

    has_resume = context.user_data.get("has_resume", False)
    return await _complete_onboarding(update, context, has_resume=has_resume, query=query)


async def refresh_user_skills_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'Refresh My Skills' callback from returning user banner."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    await update_user_profile(user_id, bot_id=bot_id, skills_need_review=False)

    step2_bar = "[🟢🟢⚪] Step 2 of 3"
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Extract from Resume (Upload PDF)", callback_data="onboard_upload_resume")]
    ])
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    await query.edit_message_text(
        f"<b>{step2_bar}</b>\n\n"
        "✍️ <b>What are your top skills?</b> 🛠️\n\n"
        f"💡 <b>Tip:</b> Upload your resume (PDF) to auto-fill your skills. {bot_name} extracts your skills locally and never stores your resume file. Or type them below separated by commas (e.g. React, Node.js, AWS):",
        reply_markup=kb,
        parse_mode="HTML",
    )
    return WAITING_CUSTOM_SKILL


async def skills_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save selected skills, then show role selection step."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get("selected_skills", [])
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)

    # Persist skills
    await update_user_profile(user_id, bot_id=bot_id, skills=[s.lower() for s in selected])

    step2_bar = messages.escape_md("[🟢⚪] Step 2 of 2")
    await query.edit_message_text(
        f"{step2_bar}\n\n"
        "*What kind of tech jobs are you looking for?* 🎯\n\n"
        "Choose your role stream so we can personalise your job feed and application kit\\.",
        reply_markup=keyboards.role_keyboard(prefix="onboard_role_"),
        parse_mode="MarkdownV2",
    )
    return ROLE


async def role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save selected role then show experience step."""
    query = update.callback_query
    await query.answer()

    role = query.data.replace("onboard_role_", "")
    user_id = update.effective_user.id

    if role == "custom":
        await query.edit_message_text(
            "✍️ *Type your role below* \\(e\\.g\\., Game Dev, AR/VR, Security\\):",
            parse_mode="MarkdownV2",
        )
        return WAITING_CUSTOM_ROLE

    bot_id = context.bot_data.get("bot_id", 1)
    await update_user_profile(user_id, bot_id=bot_id, role_pref=role)
    context.user_data["role_pref"] = role

    step2_bar = "[🟢🟢⚪] Step 2 of 3"
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Extract from Resume (Upload PDF)", callback_data="onboard_upload_resume")]
    ])
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    await query.edit_message_text(
        f"<b>{step2_bar}</b>\n\n"
        "✍️ <b>What are your top skills?</b> 🛠️\n\n"
        f"💡 <b>Tip:</b> Upload your resume (PDF) to auto-fill your skills. {bot_name} extracts your skills locally and never stores your resume file. Or type them below separated by commas (e.g. React, Node.js, AWS):",
        reply_markup=kb,
        parse_mode="HTML",
    )
    return WAITING_CUSTOM_SKILL


async def custom_role_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save a custom-typed role then move to experience step."""
    raw = (update.message.text or "").strip().lower()
    role = raw[:50]  # Clamp to 50 chars to avoid abuse
    user_id = update.effective_user.id

    bot_id = context.bot_data.get("bot_id", 1)
    await update_user_profile(user_id, bot_id=bot_id, role_pref=role)
    context.user_data["role_pref"] = role

    step2_bar = "[🟢🟢⚪] Step 2 of 3"
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Extract from Resume (Upload PDF)", callback_data="onboard_upload_resume")]
    ])
    import html
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    await update.message.reply_text(
        f"✅ Got it - we'll find you <b>{html.escape(role)}</b> jobs!\n\n"
        f"<b>{step2_bar}</b>\n\n"
        "✍️ <b>What are your top skills?</b> 🛠️\n\n"
        f"💡 <b>Tip:</b> Upload your resume (PDF) to auto-fill your skills. {bot_name} extracts your skills locally and never stores your resume file. Or type them below separated by commas (e.g. React, Node.js, AWS):",
        reply_markup=kb,
        parse_mode="HTML",
    )
    return WAITING_CUSTOM_SKILL



async def experience_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Save experience level from user text input and complete onboarding immediately.
    """
    text = (update.message.text or "").strip()
    
    if not text.isdigit():
        await update.message.reply_text("Please enter a valid number (e.g., 0, 2, 5).")
        return EXPERIENCE

    exp_val = text
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)

    await update_user_profile(user_id, bot_id=bot_id, experience_level=exp_val, location_pref="all")   # sensible default
    context.user_data["experience_level"] = exp_val
    context.user_data["location"] = "all"

    has_resume = context.user_data.get("has_resume", False)
    return await _complete_onboarding(update, context, has_resume=has_resume, query=None)




async def location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save location preference and prompt for resume."""
    query = update.callback_query
    await query.answer()

    loc_map = {"loc_remote": "remote", "loc_onsite": "onsite", "loc_hybrid": "hybrid", "loc_all": "all"}
    location = loc_map.get(query.data, "remote")

    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    await update_user_profile(user_id, bot_id=bot_id, location_pref=location)
    context.user_data["location"] = location

    step3_bar = messages.escape_md("[🟢🟢🟢⚪] Step 3 of 4")
    text = (
        f"{step3_bar}\n\n"
        + messages.escape_md("*Your graduation year* 🎓\nWhat year did you (or will you) graduate? (e.g. 2025)\n\nPlease type a 4-digit year:")
    )
    await query.edit_message_text(text, parse_mode="MarkdownV2")
    return BATCH_YEAR

async def batch_year_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process user's graduation year and prompt for resume."""
    text = update.message.text.strip()
    
    if not text.isdigit() or len(text) != 4 or not (2010 <= int(text) <= 2030):
        await update.message.reply_text(
            "⚠️ Please enter a valid 4\\-digit graduation year \\(e\\.g\\. 2024\\)\\.",
            parse_mode="MarkdownV2",
        )
        return BATCH_YEAR

    batch_year = int(text)
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    await update_user_profile(user_id, bot_id=bot_id, batch_year=batch_year)
    context.user_data["batch_year"] = batch_year

    step4_bar = messages.escape_md("[🟢🟢🟢🟢] Step 4 of 4: Almost there!")
    await update.message.reply_text(
        f"{step4_bar}\n\n"
        r"📄 *Upload your resume* \(PDF\) to automatically extract your skills for instant job matching\." "\n\n"
        "You can skip this and add skills manually in /profile",
        reply_markup=keyboards.resume_prompt_keyboard(),
        parse_mode="MarkdownV2",
    )
    return RESUME_PROMPT


async def resume_upload_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User chose to upload resume — wait for PDF."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📎 Send me your resume as a PDF file \\(max 5MB\\)\\.",
        parse_mode="MarkdownV2",
    )
    return WAITING_RESUME


async def resume_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process uploaded resume PDF."""
    document = update.message.document

    if not document or not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text(
            "⚠️ Please upload a PDF file\\.",
            parse_mode="MarkdownV2",
        )
        return WAITING_RESUME

    if document.file_size > 5 * 1024 * 1024:
        await update.message.reply_text(
            "⚠️ File too large\\. Maximum size is 5MB\\.",
            parse_mode="MarkdownV2",
        )
        return WAITING_RESUME

    try:
        file = await document.get_file()
        file_bytes = await file.download_as_bytearray()

        # Save file to disk first
        user_id = update.effective_user.id
        saved_path = save_resume_file(user_id, bytes(file_bytes), document.file_name)

        # Extract text from the saved file
        resume_text = extract_text_from_pdf(saved_path)

        # Upload to Supabase Storage
        from services.storage import upload_resume, delete_resume
        from db.users import get_user
        
        bot_id = context.bot_data.get('bot_id', 1)
        old_user = await get_user(user_id, bot_id=bot_id)
        if old_user and old_user.get("resume_filename") and old_user.get("resume_filename") != document.file_name:
            await delete_resume(user_id, old_user["resume_filename"])
            
        raw_bytes = bytes(file_bytes)
        resume_url = await upload_resume(user_id, document.file_name, raw_bytes)

        # Update DB 
        bot_id = context.bot_data.get('bot_id', 1)
        await update_resume(user_id, resume_text, document.file_name, bot_id=bot_id, raw_bytes=raw_bytes, resume_url=resume_url)

        from telegram import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB
        await update.message.reply_text(
            messages.resume_uploaded_success(document.file_name),
            parse_mode="MarkdownV2",
            reply_markup=IKM([[IKB("🔙 Back to Menu", callback_data="back_menu")]]),
        )

    except ValueError as e:
        await update.message.reply_text(
            f"⚠️ {str(e)}",
        )
        return WAITING_RESUME

    return await _complete_onboarding(update, context, has_resume=True)


async def resume_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User skipped resume upload."""
    query = update.callback_query
    await query.answer()
    return await _complete_onboarding(update, context, has_resume=False, query=query)


async def _complete_onboarding(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    has_resume: bool = False, query=None,
) -> int:
    """Finish onboarding — activate trial, show trial activated message."""
    user_id = update.effective_user.id
    user_tg = update.effective_user
    bot_id = context.bot_data.get("bot_id", 1)
    await set_onboarded(user_id, bot_id=bot_id)

    skills   = context.user_data.get("selected_skills", [])
    location = context.user_data.get("location", "all")
    exp      = context.user_data.get("experience_level", "0")

    db_pool = get_pool()
    bot_id = context.bot_data.get("bot_id", 1)

    signup_source = context.user_data.get("signup_source", "organic")
    signup_cohort = "trial" if getattr(settings, "ENABLE_FREE_TRIAL", True) else "no_trial"

    # Persist cohort & source tracking to users table
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users 
                SET signup_cohort = $1, signup_source = $2, updated_at = NOW()
                WHERE telegram_id = $3 AND bot_id = $4
                """,
                signup_cohort, signup_source, user_id, bot_id
            )
    except Exception as e:
        logger.warning(f"Failed to record cohort/source for user {user_id}: {e}")

    tracked_url = None
    tracked_count = None
    try:
        from db.bots import get_tracked_companies_url
        from db.career_sources import get_tracked_companies_summary
        tracked_url = await get_tracked_companies_url(bot_id)
        summary = await get_tracked_companies_summary()
        tracked_count = summary.get("count") or None
    except Exception as e:
        logger.warning(f"Failed to load tracked companies info for onboarding complete: {e}")

    if getattr(settings, "ENABLE_FREE_TRIAL", True):
        trial_expires_at = await start_trial(user_id, db_pool, bot_id=bot_id)
        msg = messages.trial_activated_message(trial_expires_at, bot_name=context.bot.first_name)
        kb = keyboards.onboarding_complete_keyboard(tracked_url=tracked_url, tracked_count=tracked_count)
    else:
        # Free plan completion with immediate Pro upgrade option (no trial experiment)
        bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
        count_str = f"{tracked_count}" if tracked_count else "curated"
        msg = (
            "🎉 *Your profile setup is complete\!*\n\n"
            "You are on the *Free Plan* with access to our daily curated job feed\.\n\n"
            "⚡ *Want automated alerts?*\n"
            f"Upgrade to *Pro* to have {escape_md(bot_name)} monitor {escape_md(count_str)} company career pages on an hourly crawl "
            "and alert you on Telegram as matching jobs drop\."
        )
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        rows = [
            [InlineKeyboardButton("💎 Upgrade to Pro (₹99/mo)", callback_data="upgrade_pro")],
            [
                InlineKeyboardButton("💼 Browse Daily Feed", callback_data="menu_jobs"),
                InlineKeyboardButton("🏢 Target Companies", callback_data="settings_companies"),
            ],
            [
                InlineKeyboardButton("🎯 My Profile", callback_data="menu_profile"),
            ],
        ]
        if tracked_url:
            btn_label = f"📋 Tracked Companies ({tracked_count})" if tracked_count else "📋 Tracked Companies"
            rows.append([InlineKeyboardButton(btn_label, url=tracked_url)])
        kb = InlineKeyboardMarkup(rows)

    if query:
        await query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2")

    # 🔔 Notify admin — user finished onboarding
    import html
    
    first_name_esc = html.escape(user_tg.first_name) if user_tg.first_name else "Unknown"
    username_str = f"@{html.escape(user_tg.username)}" if user_tg.username else "(no username)"
    skills_str = html.escape(", ".join(skills)) if skills else "none selected"
    loc_esc = html.escape(str(location))
    exp_esc = html.escape(str(exp))
    resume_str = "✅ Uploaded" if has_resume else "⏭️ Skipped"
    role_pref = user_tg.role_pref if hasattr(user_tg, "role_pref") else context.user_data.get("role_pref", "unknown")
    
    await notify_admin(
        context.bot,
        f"✅ <b>User Onboarded!</b>\n"
        f"👤 {first_name_esc} {username_str}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🎯 Stream: {role_pref.capitalize()}\n"
        f"🛠 Skills: {skills_str}\n"
        f"📍 Location: {loc_esc} | Exp: {exp_esc} yrs\n"
        f"📄 Resume: {resume_str}\n"
        f"🏷 Source: {signup_source} | Cohort: {signup_cohort}"
    )

    # ✅ Process referral reward if applicable
    referrer_id = context.user_data.pop("referrer_id", None)
    if not referrer_id:
        db_u = await get_user(user_id, bot_id=bot_id)
        if db_u:
            referrer_id = db_u.get("referred_by")

    if referrer_id:
        try:
            from services.referral_service import process_referral
            rewarded, days_awarded, new_expires = await process_referral(referrer_id, user_id, db_pool, bot_id=bot_id)
            if rewarded:
                # Notify the referrer
                import html as _html
                new_name = _html.escape(user_tg.first_name or "Someone")
                date_str = new_expires.strftime("%b %d, %Y") if new_expires else f"{days_awarded} days"
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=(
                            f"🎉 <b>Referral Reward Activated!</b>\n\n"
                            f"Your friend <b>{new_name}</b> just joined and completed setup!\n\n"
                            f"⭐️ <b>You've unlocked {days_awarded} Free Pro Days:</b>\n"
                            f"• 8 personalised, high-match jobs in your Daily Feed\n"
                            f"• Telegram alerts for new matching opportunities\n"
                            f"• Jobs discovered directly from 530+ company career pages\n"
                            f"• Full job match scores and skill-gap analysis\n"
                            f"• Browse active jobs with advanced filters\n"
                            f"• Track companies you specifically want to join\n\n"
                            f"⏳ Active until: <b>{date_str}</b>\n\n"
                            f"Type /menu to explore your Pro features! 🚀"
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify referrer {referrer_id}: {e}")
        except Exception as e:
            logger.warning(f"Referral processing failed: {e}")

    logger.info(f"User {user_id} completed onboarding: skills={skills}, loc={location}")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel onboarding and return to menu."""
    bot_id = context.bot_data.get("bot_id", 1)
    user = await get_user(update.effective_user.id, bot_id=bot_id)
    plan = user.get("plan", "free") if user else "free"
    upgrade_price = None
    if plan not in ("pro",):
        try:
            pricing = await get_current_pricing(get_pool())
            upgrade_price = pricing.get("current_price")
        except Exception:
            pass

    await update.message.reply_text(
        messages.main_menu(user, bot_name=context.bot.first_name),
        reply_markup=keyboards.main_menu_keyboard(plan, upgrade_price=upgrade_price),
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


def get_start_handler() -> ConversationHandler:
    """Build the /start ConversationHandler — 3-step onboarding (Skills → Role → Experience)."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CallbackQueryHandler(refresh_user_skills_callback, pattern="^refresh_user_skills$"),
        ],
        states={
            SKILLS: [
                CallbackQueryHandler(skill_toggle, pattern="^skill_"),
                CallbackQueryHandler(skills_done, pattern="^skills_done$"),
                CallbackQueryHandler(add_custom_skill_prompt, pattern="^add_custom_skill$"),
            ],
            WAITING_CUSTOM_SKILL: [
                CallbackQueryHandler(onboard_upload_resume_prompt, pattern="^onboard_upload_resume$"),
                MessageHandler(filters.Document.ALL, resume_doc_receive),
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_skill_receive),
            ],
            CONFIRM_SKILLS: [
                CallbackQueryHandler(onboard_skills_ok_callback, pattern="^onboard_skills_ok$"),
                CallbackQueryHandler(onboard_skills_edit_callback, pattern="^onboard_skills_edit$"),
                CallbackQueryHandler(onboard_skills_undo_callback, pattern="^onboard_skills_undo$"),
                MessageHandler(filters.Document.ALL, resume_doc_receive),
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_skills_text_receive),
            ],
            WAITING_RESUME_CONSENT: [
                CallbackQueryHandler(resume_consent_callback, pattern="^onboard_consent_"),
            ],
            ROLE: [
                CallbackQueryHandler(role_selected, pattern="^onboard_role_"),
                CallbackQueryHandler(onboard_upload_resume_prompt, pattern="^onboard_upload_resume$"),
            ],
            WAITING_CUSTOM_ROLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_role_receive),
            ],
            EXPERIENCE: [
                CallbackQueryHandler(experience_callback_handler, pattern="^onboard_exp_\\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, experience_message_handler),
            ],
            # Kept for state-enum validity
            WELCOME:       [],
            LOCATION:      [],
            BATCH_YEAR:    [],
            RESUME_PROMPT: [],
            WAITING_RESUME:[],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True,
    )
