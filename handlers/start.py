"""
/start — Onboarding ConversationHandler.
Flow: Welcome → Skills → Location → Resume Prompt → Complete
"""
from telegram import Update
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from loguru import logger

from db.users import get_or_create_user, update_user_profile, update_resume, set_onboarded, get_user
from db.connection import get_pool
from services.resume_parser import extract_text_from_pdf, save_resume_file
from services.pricing_service import start_trial, get_current_pricing
from utils import keyboards, messages
from utils.admin_notify import notify_admin

# Conversation states
WELCOME, SKILLS, ROLE, WAITING_CUSTOM_SKILL, EXPERIENCE, LOCATION, BATCH_YEAR, RESUME_PROMPT, WAITING_RESUME = range(9)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — begin onboarding or show main menu if already onboarded."""
    user = update.effective_user
    db_user = await get_or_create_user(user.id, user.username, user.first_name)

    if db_user.get("is_deleted"):
        from db.users import restore_user
        await restore_user(user.id)
        db_user = await get_user(user.id)  # Refresh db_user
        
        await update.message.reply_text(
            "🎉 *Welcome back\\! Your previous data has been restored\\.*",
            parse_mode="MarkdownV2"
        )

    if db_user.get("is_onboarded"):
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
            messages.main_menu(db_user),
            reply_markup=keyboards.main_menu_keyboard(plan, upgrade_price=upgrade_price),
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    # New user → start onboarding
    context.user_data["selected_skills"] = []

    # 🔔 Notify admin about new user
    username_str = f"@{user.username}" if user.username else "(no username)"
    await notify_admin(
        context.bot,
        f"🆕 <b>New User Joined!</b>\n"
        f"👤 {user.first_name} {username_str}\n"
        f"🆔 ID: <code>{user.id}</code>"
    )

    try:
        with open("assets/images/Applixy_banner.png", "rb") as banner:
            await update.message.reply_photo(
                photo=banner,
                caption=messages.welcome_message(user.first_name),
                reply_markup=keyboards.onboarding_welcome_keyboard(),
                parse_mode="MarkdownV2",
            )
    except FileNotFoundError:
        logger.warning("Applixy_banner.png not found, falling back to text.")
        await update.message.reply_text(
            messages.welcome_message(user.first_name),
            reply_markup=keyboards.onboarding_welcome_keyboard(),
            parse_mode="MarkdownV2",
        )

    return WELCOME


async def welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'Actively Hunting' / 'Just Exploring' selection."""
    query = update.callback_query
    await query.answer()

    # Store user intent (not used for logic yet, but trackable)
    context.user_data["intent"] = query.data  # onboard_hunting or onboard_exploring

    # The welcome message may be a photo (banner) or text (fallback).
    # We can't edit_message_text on a photo, so delete and send fresh.
    try:
        await query.message.delete()
    except Exception:
        pass  # If delete fails, just continue

    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=messages.skills_prompt(),
        reply_markup=keyboards.skills_keyboard([]),
        parse_mode="MarkdownV2",
    )
    return SKILLS


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


async def custom_skill_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive and normalize custom typed skills, then return to skill grid."""
    text = update.message.text
    raw_skills = [s.strip() for s in text.split(',') if s.strip()]
    
    from utils.helpers import normalize_skills
    normalized = normalize_skills(raw_skills)
    
    selected = context.user_data.get("selected_skills", [])
    for s in normalized:
        if s.lower() not in [x.lower() for x in selected]:
            selected.append(s)
            
    context.user_data["selected_skills"] = selected
    
    await update.message.reply_text(
        messages.skills_prompt(),
        reply_markup=keyboards.skills_keyboard(selected),
        parse_mode="MarkdownV2",
    )
    return SKILLS


async def skills_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save selected skills and move to location selection."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get("selected_skills", [])

    # Save skills to DB
    user_id = update.effective_user.id
    await update_user_profile(user_id, skills=[s.lower() for s in selected])

    await query.edit_message_text(
        "💼 What is your primary role preference?",
        reply_markup=keyboards.role_keyboard(),
        parse_mode="MarkdownV2",
    )
    return ROLE

async def role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save role preference and prompt for experience."""
    query = update.callback_query
    await query.answer()

    role_val = query.data.replace("role_", "")
    
    user_id = update.effective_user.id
    await update_user_profile(user_id, role_pref=role_val)
    context.user_data["role_pref"] = role_val

    await query.edit_message_text(
        "🧠 How many years of professional experience do you have?",
        reply_markup=keyboards.experience_keyboard(),
        parse_mode="MarkdownV2",
    )
    return EXPERIENCE


async def experience_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save experience level and prompt for location."""
    query = update.callback_query
    await query.answer()

    # Data is like: exp_0, exp_1, exp_2, exp_3_5, exp_5_plus
    exp_val = query.data.replace("exp_", "")
    
    user_id = update.effective_user.id
    await update_user_profile(user_id, experience_level=exp_val)
    context.user_data["experience_level"] = exp_val

    await query.edit_message_text(
        "🌍 Where are you looking for work?",
        reply_markup=keyboards.location_keyboard(),
        parse_mode="MarkdownV2",
    )
    return LOCATION


async def location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save location preference and prompt for resume."""
    query = update.callback_query
    await query.answer()

    loc_map = {"loc_remote": "remote", "loc_onsite": "onsite", "loc_hybrid": "hybrid", "loc_all": "all"}
    location = loc_map.get(query.data, "remote")

    user_id = update.effective_user.id
    await update_user_profile(user_id, location_pref=location)
    context.user_data["location"] = location

    text = messages.escape_md("🎓 What year did you (or will you) graduate? (e.g. 2025)\n\nPlease type a 4-digit year:")
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
    await update_user_profile(user_id, batch_year=batch_year)
    context.user_data["batch_year"] = batch_year

    await update.message.reply_text(
        "📄 Almost done\\!\n\n"
        "Upload your resume \\(PDF\\) so I can write personalised cover letters for you\\.\n\n"
        "You can skip this and upload later with /resume",
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

        # Update DB 
        await update_resume(user_id, resume_text, document.file_name)

        await update.message.reply_text(
            messages.resume_uploaded_success(document.file_name),
            parse_mode="MarkdownV2",
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
    await set_onboarded(user_id)

    skills = context.user_data.get("selected_skills", [])
    location = context.user_data.get("location", "remote")
    exp = context.user_data.get("experience_level", "?")

    # Activate 3-day free trial for new user
    db_pool = get_pool()
    trial_expires_at = await start_trial(user_id, db_pool)

    msg = messages.trial_activated_message(trial_expires_at)
    kb = keyboards.onboarding_complete_keyboard()

    if query:
        await query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2")

    # 🔔 Notify admin — user finished onboarding
    username_str = f"@{user_tg.username}" if user_tg.username else "(no username)"
    skills_str = ", ".join(skills) if skills else "none selected"
    resume_str = "✅ Uploaded" if has_resume else "⏭️ Skipped"
    await notify_admin(
        context.bot,
        f"✅ <b>User Onboarded!</b>\n"
        f"👤 {user_tg.first_name} {username_str}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🛠 Skills: {skills_str}\n"
        f"📍 Location: {location} | Exp: {exp} yrs\n"
        f"📄 Resume: {resume_str}"
    )

    logger.info(f"User {user_id} completed onboarding: skills={skills}, loc={location}")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel onboarding and return to menu."""
    user = await get_user(update.effective_user.id)
    plan = user.get("plan", "free") if user else "free"
    upgrade_price = None
    if plan not in ("pro",):
        try:
            pricing = await get_current_pricing(get_pool())
            upgrade_price = pricing.get("current_price")
        except Exception:
            pass

    await update.message.reply_text(
        messages.main_menu(user),
        reply_markup=keyboards.main_menu_keyboard(plan, upgrade_price=upgrade_price),
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


def get_start_handler() -> ConversationHandler:
    """Build the /start ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            WELCOME: [
                CallbackQueryHandler(welcome_callback, pattern="^onboard_"),
            ],
            SKILLS: [
                CallbackQueryHandler(skill_toggle, pattern="^skill_"),
                CallbackQueryHandler(skills_done, pattern="^skills_done$"),
                CallbackQueryHandler(add_custom_skill_prompt, pattern="^add_custom_skill$"),
            ],
            WAITING_CUSTOM_SKILL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_skill_receive),
            ],
            ROLE: [
                CallbackQueryHandler(role_callback, pattern="^role_"),
            ],
            EXPERIENCE: [
                CallbackQueryHandler(experience_callback, pattern="^exp_"),
            ],
            LOCATION: [
                CallbackQueryHandler(location_callback, pattern="^loc_"),
            ],
            BATCH_YEAR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, batch_year_received),
            ],
            RESUME_PROMPT: [
                CallbackQueryHandler(resume_upload_prompt, pattern="^resume_upload$"),
                CallbackQueryHandler(resume_skip, pattern="^resume_skip$"),
            ],
            WAITING_RESUME: [
                MessageHandler(filters.Document.PDF, resume_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True,
    )
