"""
Settings, Status, Saved Jobs, and Account Deletion handlers.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from loguru import logger

from db.users import get_user, update_user_profile
from db.jobs import get_saved_jobs
from utils import keyboards, messages
from utils.helpers import escape_md


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings — routes to unified Profile & Preferences dashboard."""
    from handlers.resume import view_profile
    await view_profile(update, context)


# ──────────────────────────────────────────────
# Edit Skills from Settings
# ──────────────────────────────────────────────

async def settings_edit_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user for comma-separated skills, displaying current skills in an easy tap-to-copy code block."""
    import html
    user_id = update.effective_user.id
    bot_id = context.bot_data.get('bot_id', 1)
    user = await get_user(user_id, bot_id=bot_id)
    if not user:
        return

    context.user_data["awaiting_settings_custom_skill"] = True

    skills = (user.get("skills") if user else []) or []

    if skills:
        from utils.validators import CANONICAL_SKILL_MAP
        skills_str = ", ".join([CANONICAL_SKILL_MAP.get(s.lower(), s.title() if len(s) > 3 and not s.isupper() else s) for s in skills])
        msg = (
            "🏷 <b>Edit Skills</b>\n\n"
            "<b>Your Current Skills:</b>\n"
            f"<code>{html.escape(skills_str)}</code>\n\n"
            "💡 <i>Tap the code box above to copy your skills, edit them in the message bar, and send.</i>\n\n"
            "Or send a resume (PDF) to auto-extract skills instantly."
        )
    else:
        msg = (
            "🏷 <b>Edit Skills</b>\n\n"
            "<i>No skills configured yet.</i>\n\n"
            "Please type your skills separated by commas below:\n"
            "<i>Example: Python, React, TypeScript, Docker, SQL</i>\n\n"
            "Or send a resume (PDF) to auto-extract skills instantly."
        )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📄 Extract from Resume (PDF)", callback_data="profile_refresh_resume"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile"),
        ]
    ])

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")


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
    """Receive text input for skills, validate, backup, and save to DB."""
    import html
    text = (update.message.text or "").strip()
    from utils.validators import validate_and_normalize_skills
    is_valid, normalized, err_msg = validate_and_normalize_skills(text, max_skills=15)
    if not is_valid:
        await update.message.reply_text(
            f"⚠️ {err_msg or 'Please enter valid technical skills separated by commas.'}\n\n"
            "Try again, or tap below to extract from resume:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📄 Extract from Resume (PDF)", callback_data="profile_refresh_resume")],
                [InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")],
            ]),
        )
        return

    user_id = update.effective_user.id
    bot_id = context.bot_data.get('bot_id', 1)

    # 1. Backup existing skills in user_skills_backup for Undo support
    try:
        from db.connection import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            curr_skills = await conn.fetchval(
                "SELECT skills FROM users WHERE telegram_id = $1 AND bot_id = $2",
                user_id, bot_id
            ) or []
            if curr_skills:
                await conn.execute(
                    """
                    INSERT INTO user_skills_backup (telegram_id, bot_id, previous_skills, updated_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (telegram_id, bot_id) DO UPDATE 
                    SET previous_skills = EXCLUDED.previous_skills, updated_at = NOW()
                    """,
                    user_id, bot_id, curr_skills
                )
    except Exception as e:
        logger.warning(f"Failed to backup skills for user {user_id}: {e}")

    # 2. Save directly to DB
    from db.users import update_user_profile
    await update_user_profile(user_id, bot_id=bot_id, skills=[s.lower() for s in normalized], skills_need_review=False)
    
    # 3. Clear the flag
    context.user_data.pop("awaiting_settings_custom_skill", None)
    
    # 4. Show success with clean actionable buttons
    skills_display = ", ".join(normalized)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("↩️ Undo", callback_data="profile_skills_undo"),
            InlineKeyboardButton("✏️ Edit Again", callback_data="settings_skills"),
        ],
        [
            InlineKeyboardButton("🎯 My Profile", callback_data="menu_profile"),
            InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu"),
        ],
    ])
    
    await update.message.reply_text(
        f"✅ <b>Skills updated successfully!</b>\n\n"
        f"<b>Active Skills ({len(normalized)}):</b>\n"
        f"<code>{html.escape(skills_display)}</code>\n\n"
        f"💡 <i>Your alerts and feed are now aligned with these skills.</i>",
        reply_markup=kb,
        parse_mode="HTML",
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
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")]]),
        parse_mode="MarkdownV2",
    )


# ──────────────────────────────────────────────
# Edit Experience from Settings
# ──────────────────────────────────────────────

async def settings_change_experience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show experience selection text prompt."""
    query = update.callback_query
    await query.answer()

    context.user_data["awaiting_settings_experience"] = True
    await query.edit_message_text(
        "🧠 *Edit Experience Level*\n\nHow many years of professional experience do you have? \\(Reply with a number, e\\.g\\. 0, 2, 5\\)",
        parse_mode="MarkdownV2",
    )

async def settings_experience_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save the new experience level from text input."""
    text = (update.message.text or "").strip()
    
    if not text.isdigit():
        await update.message.reply_text("Please enter a valid number (e.g., 0, 2, 5).")
        return

    exp_val = text
    user_id = update.effective_user.id
    
    # Clear the flag
    context.user_data.pop("awaiting_settings_experience", None)
    
    await update_user_profile(user_id, experience_level=exp_val)

    exp_display = exp_val.replace('_plus', '+').replace('_', '-')
    
    from handlers.settings import settings_command
    await update.message.reply_text(f"✅ Experience updated to: *{exp_display}* years", parse_mode="Markdown")
    await settings_command(update, context)



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
    rows.append([InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")])

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
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")]]),
        parse_mode="MarkdownV2",
    )


# ──────────────────────────────────────────────
# Change Location from Settings
# ──────────────────────────────────────────────

async def settings_change_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show work mode selection."""
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌏 Remote Only", callback_data="setloc_remote"),
            InlineKeyboardButton("🏢 Onsite Only", callback_data="setloc_onsite"),
        ],
        [
            InlineKeyboardButton("🌍 Hybrid Only", callback_data="setloc_hybrid"),
            InlineKeyboardButton("🔄 All Work Modes", callback_data="setloc_all"),
        ],
        [InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")],
    ])

    await query.edit_message_text(
        "💼 *Change Work Mode*\n\nSelect your preferred work mode:",
        reply_markup=kb,
        parse_mode="MarkdownV2",
    )


async def settings_location_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save updated work mode preference."""
    query = update.callback_query
    await query.answer()

    loc_map = {"setloc_remote": "remote", "setloc_onsite": "onsite", "setloc_hybrid": "hybrid", "setloc_all": "all"}
    location = loc_map.get(query.data, "remote")

    user_id = update.effective_user.id
    bot_id = context.bot_data.get('bot_id', 1)
    await update_user_profile(user_id, location_pref=location, bot_id=bot_id)

    loc_display = {"remote": "🌏 Remote Only", "onsite": "🏢 Onsite Only", "hybrid": "🌍 Hybrid Only", "all": "🔄 All Work Modes"}
    await query.edit_message_text(
        f"✅ Work mode updated: *{escape_md(loc_display.get(location, location))}*\n",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")]]),
        parse_mode="MarkdownV2",
    )


# ──────────────────────────────────────────────
# Edit Role / Stream from Settings
# ──────────────────────────────────────────────

async def settings_edit_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show role/stream selection."""
    query = update.callback_query
    await query.answer()

    kb = keyboards.role_keyboard(prefix="setrole_")
    # Append back button
    buttons = list(kb.inline_keyboard)
    buttons.append([InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")])

    await query.edit_message_text(
        "🎯 *Change Target Stream*\n\nSelect your stream or type a custom role:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="MarkdownV2",
    )


async def settings_role_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save updated role preference or prompt for custom typing."""
    query = update.callback_query
    await query.answer()

    role_val = query.data.replace("setrole_", "")

    if role_val == "custom":
        context.user_data["awaiting_settings_role"] = True
        await query.edit_message_text(
            "✍️ *Type your stream / role below* \\(e\\.g\\., Java Developer, Flutter, DevOps, Cybersecurity\\):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")]]),
            parse_mode="MarkdownV2",
        )
        return

    user_id = update.effective_user.id
    bot_id = context.bot_data.get('bot_id', 1)
    await update_user_profile(user_id, role_pref=role_val, bot_id=bot_id)

    await query.edit_message_text(
        f"✅ Target Stream updated to: *{escape_md(role_val.title())}*\n",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")]]),
        parse_mode="MarkdownV2",
    )


async def settings_role_custom_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save a custom-typed stream/role from settings."""
    context.user_data.pop("awaiting_settings_role", None)
    raw = (update.message.text or "").strip()
    role = raw[:50]
    user_id = update.effective_user.id
    bot_id = context.bot_data.get('bot_id', 1)
    await update_user_profile(user_id, role_pref=role, bot_id=bot_id)

    await update.message.reply_text(
        f"✅ Target Stream updated to: *{escape_md(role.title())}*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")]]),
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
    buttons.append([InlineKeyboardButton("🔙 Back to Notifications", callback_data="settings_notifications")])

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
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Notifications", callback_data="settings_notifications")]]),
        parse_mode="MarkdownV2",
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status — routes to unified Profile & Preferences dashboard."""
    from handlers.resume import view_profile
    await view_profile(update, context)


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
        msg += f"{i}\\. *{title}* \\({company}\\)\n"

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
    bot_id = context.bot_data.get('bot_id', 1)
    from services.resume_parser import delete_resume_file
    from db.users import soft_delete_user, delete_user_resume

    await delete_user_resume(user_id, bot_id=bot_id)
    delete_resume_file(user_id)
    
    success = await soft_delete_user(user_id)
    if success:
        try:
            from db.connection import get_pool
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM user_company_prefs WHERE telegram_id = $1", user_id)
        except Exception as e:
            logger.warning(f"Failed to purge user_company_prefs on account delete: {e}")
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
            InlineKeyboardButton("❌ Keep Pro", callback_data="menu_profile"),
        ]
    ])
    
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    await query.edit_message_text(
        "⚠️ *Cancel Subscription*\n\n"
        f"Are you sure you want to cancel your {escape_md(bot_name)} Pro subscription?\n"
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
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    
    db_pool = get_pool()
    bot_id = context.bot_data.get('bot_id', 1)
    success = await cancel_user_subscription(user_id, db_pool, bot_id=bot_id)
    
    if success:
        logger.info(f"User {user_id} cancelled their subscription.")
        await query.edit_message_text(
            "✅ *Subscription Cancelled*\n\n"
            f"Your {escape_md(bot_name)} Pro subscription has been cancelled and will not renew\\.\n"
            "You can continue using Pro features until your current cycle ends\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")]])
        )
    else:
        await query.edit_message_text(
            "❌ Could not cancel your subscription at this time\\. Please contact support\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu_profile")]])
        )



# ──────────────────────────────────────────────
# Notification Preferences (RFC-002)
# ──────────────────────────────────────────────

async def settings_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Render Notification Preferences menu."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    bot_id = context.bot_data.get('bot_id', 1)
    user = await get_user(user_id, bot_id=bot_id)
    if not user:
        return
    
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    is_pro = user.get("plan") in ("pro", "trial", "proplus", "premium")
    text = messages.notification_settings_message(user, bot_name=bot_name)
    kb = keyboards.notification_settings_keyboard(user, is_pro=is_pro)
    
    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Error editing notification menu: {e}")


async def settings_toggle_notification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Atomic idempotent handler for toggling notification streams."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data  # e.g. notif_set_instant_0 or notif_set_daily_1
    
    parts = data.split("_")
    stream = parts[2]
    val = (parts[3] == "1")

    column_map = {
        "instant": "notify_instant_alerts",
        "daily": "notify_daily_digest",
        "silent": "silent_night_mode",
        "evening": "notify_evening_digest",
        "weekly": "notify_weekly_scorecard",
    }
    col = column_map.get(stream)
    if not col:
        return

    from db.connection import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE users SET {col} = $1 WHERE telegram_id = $2", val, user_id)

    bot_id = context.bot_data.get('bot_id', 1)
    user = await get_user(user_id, bot_id=bot_id)
    if not user:
        return
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    is_pro = user.get("plan") in ("pro", "trial", "proplus", "premium")
    text = messages.notification_settings_message(user, bot_name=bot_name)
    kb = keyboards.notification_settings_keyboard(user, is_pro=is_pro)

    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Error updating notification toggle: {e}")


async def settings_instant_locked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show toast explaining instant alerts are a Pro feature."""
    query = update.callback_query
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    await query.answer(f"💎 Instant alerts require {bot_name} Pro. Type /upgrade to unlock!", show_alert=True)


async def settings_pause_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show duration picker for pausing notifications."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "🔕 *Pause All Notifications*\n\n"
        "Need a break from job alerts? Choose how long to pause:\n\n"
        "• While paused, all instant alerts & daily feeds are silenced\\.\n"
        "• Scheduled application follow\\-ups will still arrive\\.\n"
        "• Alerts will automatically resume once the duration ends\\."
    )
    try:
        await query.edit_message_text(text, reply_markup=keyboards.pause_duration_keyboard(), parse_mode="MarkdownV2")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Error showing pause menu: {e}")


async def settings_pause_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set pause duration on alerts_paused_until."""
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data

    duration_str = data.replace("notif_pause_set_", "")
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    
    if duration_str == "3d":
        paused_until = now + timedelta(days=3)
        msg_toast = "🔕 Alerts paused for 3 days."
    elif duration_str == "7d":
        paused_until = now + timedelta(days=7)
        msg_toast = "🔕 Alerts paused for 1 week."
    elif duration_str == "14d":
        paused_until = now + timedelta(days=14)
        msg_toast = "🔕 Alerts paused for 2 weeks."
    else:  # forever
        paused_until = now + timedelta(days=365)
        msg_toast = "🔕 Alerts paused indefinitely until resumed."

    await query.answer(msg_toast, show_alert=True)

    from db.connection import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET alerts_paused_until = $1 WHERE telegram_id = $2", paused_until, user_id)

    bot_id = context.bot_data.get('bot_id', 1)
    user = await get_user(user_id, bot_id=bot_id)
    if not user:
        return
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    is_pro = user.get("plan") in ("pro", "trial", "proplus", "premium")
    text = messages.notification_settings_message(user, bot_name=bot_name)
    kb = keyboards.notification_settings_keyboard(user, is_pro=is_pro)

    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Error updating paused state: {e}")


async def settings_pause_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resume alerts immediately."""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer("▶️ Alerts resumed!", show_alert=True)

    from db.connection import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET alerts_paused_until = NULL WHERE telegram_id = $1", user_id)

    bot_id = context.bot_data.get('bot_id', 1)
    user = await get_user(user_id, bot_id=bot_id)
    if not user:
        return
    bot_name = (context.bot.first_name or "Froncy") if context and context.bot else "Froncy"
    is_pro = user.get("plan") in ("pro", "trial", "proplus", "premium")
    text = messages.notification_settings_message(user, bot_name=bot_name)
    kb = keyboards.notification_settings_keyboard(user, is_pro=is_pro)

    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Error resuming alerts: {e}")
