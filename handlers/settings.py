"""
Settings, Status, Saved Jobs, and Account Deletion handlers.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from loguru import logger

from db.users import get_user, delete_user, update_user_profile
from db.jobs import get_saved_jobs
from utils import keyboards, messages
from utils.helpers import escape_md


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings."""
    user_id = update.effective_user.id
    user = await get_user(user_id)
    is_active_pro = False
    if user and user.get("plan") != "free" and user.get("subscription_status") == "active":
        is_active_pro = True

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            messages.settings_menu(),
            reply_markup=keyboards.settings_keyboard(is_active_pro),
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text(
            messages.settings_menu(),
            reply_markup=keyboards.settings_keyboard(is_active_pro),
            parse_mode="MarkdownV2"
        )


# ──────────────────────────────────────────────
# Edit Skills from Settings
# ──────────────────────────────────────────────

async def settings_edit_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show skills selection grid (reuses onboarding keyboard)."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user = await get_user(user_id)
    current_skills = user.get("skills", []) if user else []
    context.user_data["edit_skills"] = list(current_skills)

    await query.edit_message_text(
        "🏷 *Edit Skills*\n\nSelect your skills, then tap Done\\.",
        reply_markup=keyboards.skills_keyboard(current_skills),
        parse_mode="MarkdownV2",
    )


async def settings_skill_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle a skill on/off from settings."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get("edit_skills", [])
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

    context.user_data["edit_skills"] = selected

    await query.edit_message_text(
        "🏷 *Edit Skills*\n\nSelect your skills, then tap Done\\.",
        reply_markup=keyboards.skills_keyboard(selected),
        parse_mode="MarkdownV2",
    )


async def settings_add_custom_skill_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to type custom skills from settings."""
    query = update.callback_query
    await query.answer()
    
    # We set a flag in user_data so the MessageHandler in bot.py knows to intercept the next text message
    context.user_data["awaiting_settings_custom_skill"] = True
    
    await query.edit_message_text(
        "✍️ *Type your custom skills separated by commas*\n"
        "\\(e\\.g\\., Prisma, Redis, GraphQL\\)\n\n"
        "Send your skills below:",
        parse_mode="MarkdownV2"
    )

async def settings_custom_skill_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receive text input for custom skills in settings."""
    text = update.message.text
    raw_skills = [s.strip() for s in text.split(',') if s.strip()]
    
    from utils.helpers import normalize_skills
    normalized = normalize_skills(raw_skills)
    
    selected = context.user_data.get("edit_skills", [])
    for s in normalized:
        if s.lower() not in [x.lower() for x in selected]:
            selected.append(s)
            
    context.user_data["edit_skills"] = selected
    
    # Clear the flag
    context.user_data.pop("awaiting_settings_custom_skill", None)
    
    await update.message.reply_text(
        "🏷 *Edit Skills*\n\nSelect your skills, then tap Done\\.",
        reply_markup=keyboards.skills_keyboard(selected),
        parse_mode="MarkdownV2",
    )


async def settings_skills_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save updated skills and return to settings menu."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get("edit_skills", [])
    user_id = update.effective_user.id
    await update_user_profile(user_id, skills=[s.lower() for s in selected])

    skills_text = escape_md(", ".join(selected)) if selected else "None"
    await query.edit_message_text(
        f"✅ Skills updated: {skills_text}\n",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]]),
        parse_mode="MarkdownV2",
    )


# ──────────────────────────────────────────────
# Edit Experience from Settings
# ──────────────────────────────────────────────

async def settings_change_experience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show experience selection."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🧠 *Edit Experience Level*\n\nHow many years of professional experience do you have?",
        reply_markup=keyboards.experience_keyboard(prefix="setexp_"),
        parse_mode="MarkdownV2",
    )

async def settings_experience_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save the new experience level."""
    query = update.callback_query
    await query.answer()

    exp_val = query.data.replace("setexp_", "")
    user_id = update.effective_user.id
    
    await update_user_profile(user_id, experience_level=exp_val)

    exp_display = exp_val.replace('_plus', '+').replace('_', '-')
    await query.edit_message_text(
        f"✅ Experience updated to: *{escape_md(exp_display)}*\n",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]]),
        parse_mode="MarkdownV2",
    )



# ──────────────────────────────────────────────
# Edit Batch Year from Settings
# ──────────────────────────────────────────────

async def settings_change_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show batch year selection buttons (2020–2028)."""
    query = update.callback_query
    await query.answer()

    current_year = 2025
    years = list(range(2020, 2029))
    rows = []
    row = []
    for y in years:
        row.append(InlineKeyboardButton(str(y), callback_data=f"setbatch_{y}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")])

    await query.edit_message_text(
        "🎓 *Edit Batch Year*\n\nSelect your graduation year:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="MarkdownV2",
    )


async def settings_batch_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save selected batch year."""
    query = update.callback_query
    await query.answer()

    batch_val = int(query.data.replace("setbatch_", ""))
    user_id = update.effective_user.id
    await update_user_profile(user_id, batch_year=batch_val)

    await query.edit_message_text(
        f"✅ Batch year updated to: *{batch_val}*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]]),
        parse_mode="MarkdownV2",
    )


# ──────────────────────────────────────────────
# Change Location from Settings
# ──────────────────────────────────────────────

async def settings_change_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show location selection."""
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌏 Remote Only", callback_data="setloc_remote"),
            InlineKeyboardButton("🇮🇳 India Only", callback_data="setloc_india"),
            InlineKeyboardButton("🌐 Both", callback_data="setloc_both"),
        ],
        [InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")],
    ])

    await query.edit_message_text(
        "📍 *Change Location*\n\nWhere are you looking for work?",
        reply_markup=kb,
        parse_mode="MarkdownV2",
    )


async def settings_location_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save updated location preference."""
    query = update.callback_query
    await query.answer()

    loc_map = {"setloc_remote": "remote", "setloc_india": "india", "setloc_both": "both"}
    location = loc_map.get(query.data, "remote")

    user_id = update.effective_user.id
    await update_user_profile(user_id, location_pref=location)

    loc_display = {"remote": "🌏 Remote", "india": "🇮🇳 India", "both": "🌐 Both"}
    await query.edit_message_text(
        f"✅ Location updated: {escape_md(loc_display.get(location, location))}\n",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]]),
        parse_mode="MarkdownV2",
    )


# ──────────────────────────────────────────────
# Alert Time from Settings
# ──────────────────────────────────────────────

ALERT_TIME_OPTIONS = [
    ("07:00", "7 AM"),
    ("08:00", "8 AM"),
    ("09:00", "9 AM"),
    ("10:00", "10 AM"),
    ("11:00", "11 AM"),
    ("11:20", "11:20 AM (Test)"),
    ("12:00", "12 PM"),
    ("14:00", "2 PM"),
    ("16:00", "4 PM"),
    ("18:00", "6 PM"),
    ("21:00", "9 PM"),
    ("22:00", "10 PM"),
]


async def settings_alert_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show alert time selection."""
    query = update.callback_query
    await query.answer()

    buttons = []
    row = []
    for time_val, time_label in ALERT_TIME_OPTIONS:
        row.append(InlineKeyboardButton(f"⏰ {time_label}", callback_data=f"setalert_{time_val}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")])

    await query.edit_message_text(
        "⏰ *Alert Time*\n\nWhen should I send daily job alerts? \\(IST\\)",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="MarkdownV2",
    )


async def settings_alert_time_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save updated alert time."""
    query = update.callback_query
    await query.answer()

    time_val = query.data.replace("setalert_", "")  # e.g. "09:00"
    user_id = update.effective_user.id
    await update_user_profile(user_id, alert_time=time_val)

    await query.edit_message_text(
        f"✅ Alert time updated: {escape_md(time_val)} IST\n",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]]),
        parse_mode="MarkdownV2",
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status and View Status from settings."""
    user_id = update.effective_user.id
    user = await get_user(user_id)

    if not user:
        await update.message.reply_text("Please /start first.")
        return

    msg = messages.user_status(user)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            msg,
            reply_markup=keyboards.InlineKeyboardMarkup([[keyboards.InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]]),
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text(msg, parse_mode="MarkdownV2")


async def view_saved_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /saved."""
    user_id = update.effective_user.id
    jobs = await get_saved_jobs(user_id)

    if not jobs:
        msg = "You don't have any saved jobs."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                msg,
                reply_markup=keyboards.InlineKeyboardMarkup([[keyboards.InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]]),
            )
        else:
            await update.message.reply_text(msg)
        return

    msg = "💾 *Your Saved Jobs*\n\n"
    for i, job in enumerate(jobs[:10], 1):
        title = escape_md(job.get("title", "Untitled")[:30])
        company = escape_md(job.get("company") or "N/A")
        msg += f"{i}\\. *{title}* — {company}\n"

    kb = keyboards.saved_jobs_keyboard(jobs)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)


async def delete_account_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show GDPR delete confirmation."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            messages.confirm_delete(),
            reply_markup=keyboards.confirm_delete_keyboard(),
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text(
            messages.confirm_delete(),
            reply_markup=keyboards.confirm_delete_keyboard(),
            parse_mode="MarkdownV2"
        )


async def delete_account_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute account deletion."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    from services.resume_parser import delete_resume_file
    from db.users import soft_delete_user
    
    success = await soft_delete_user(user_id)
    if success:
        # We don't delete the resume file anymore since it's a soft delete and we want to recover it later
        logger.info(f"User {user_id} soft deleted their account.")
        await query.edit_message_text(messages.account_deleted(), parse_mode="MarkdownV2")
    else:
        await query.edit_message_text("❌ Something went wrong\\. Please try again\\.", parse_mode="MarkdownV2")


# ──────────────────────────────────────────────
# Subscription Cancellation
# ──────────────────────────────────────────────

async def cancel_subscription_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user before cancelling subscription."""
    query = update.callback_query
    await query.answer()
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ Yes, Cancel My Subscription", callback_data="confirm_cancel_sub"),
            InlineKeyboardButton("❌ Keep Pro", callback_data="menu_settings"),
        ]
    ])
    
    await query.edit_message_text(
        "⚠️ *Cancel Subscription*\n\n"
        "Are you sure you want to cancel your Applixy Pro subscription?\n"
        "• You will not be billed again\\.\n"
        "• You will keep your Pro benefits until the end of your current billing cycle\\.",
        reply_markup=kb,
        parse_mode="MarkdownV2"
    )

async def cancel_subscription_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle actual subscription cancellation."""
    from services.payment_service import cancel_user_subscription
    from db.connection import get_pool
    
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    db_pool = get_pool()
    success = await cancel_user_subscription(user_id, db_pool)
    
    if success:
        logger.info(f"User {user_id} cancelled their subscription.")
        await query.edit_message_text(
            "✅ *Subscription Cancelled*\n\n"
            "Your Applixy Pro subscription has been cancelled and will not renew\\.\n"
            "You can continue using Pro features until your current cycle ends\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]])
        )
    else:
        await query.edit_message_text(
            "❌ Could not cancel your subscription at this time\\. Please contact support\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]])
        )
