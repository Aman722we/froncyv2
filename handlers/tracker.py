import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.users import get_user
from db.jobs import get_job_by_id
from db.tracker import add_application, get_applications, count_applications, get_weekly_stats, get_application_by_id, update_application_status
from utils.messages import escape_md
from utils.limits import get_limit

async def mark_applied_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ✅ Mark as Applied button."""
    query = update.callback_query

    job_id = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    plan = user.get("plan", "free")
    limit = get_limit(plan, "application_tracking_max") or 999
    
    if limit < 999:
        total_apps = await count_applications(user_id)
        if total_apps >= limit:
            await query.answer()
            msg = (
                "⚠️ *App Tracker Limit Reached*\n\n"
                "You have tracked your maximum of 10 applications\\.\n\n"
                "Upgrade to Pro \\(₹99/mo\\) for unlimited tracking and follow\\-up reminders\\!"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Upgrade — ₹99/mo", callback_data="upgrade_pro")],
                [InlineKeyboardButton("🔙 Back to Jobs", callback_data="menu_jobs")]
            ])
            await query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
            return
            
    success = await add_application(user_id, job_id)
    
    if success:
        msg = "✅ Job added to your tracker!"
        if plan == "pro":
            msg += "\nI'll remind you to follow up in 3 days."
        await query.answer(msg, show_alert=True)
    else:
        await query.answer("ℹ️ You have already tracked this job.", show_alert=True)


async def tracker_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user's applications."""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    # Handle pagination
    page = 1
    if query and query.data.startswith("tracker_page_"):
        page = int(query.data.split("_")[-1])
    
    jobs_per_page = 5
    offset = (page - 1) * jobs_per_page
    
    apps = await get_applications(user_id, limit=jobs_per_page, offset=offset)
    total_apps = await count_applications(user_id)
    
    if total_apps == 0:
        msg = "📋 *My Applications*\n\nYou haven't tracked any applications yet\\."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Browse Jobs", callback_data="menu_jobs")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        if query:
            await query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
        return

    total_pages = math.ceil(total_apps / jobs_per_page)
    msg = f"📋 *My Applications* \\({total_apps} total\\)\n"
    msg += f"Page {page} of {total_pages}\n\n"
    msg += "Tap an application below to view details or update its status\\:"
    
    buttons = []
    for app in apps:
        # Create an inline button for each application
        date_str = app["applied_at"].strftime("%b %d")
        status_emoji = {
            "applied": "🔵", "interviewing": "🟡",
            "rejected": "🔴", "offer": "🟢"
        }.get(app["status"], "⚪")
        
        btn_text = f"{status_emoji} {date_str} - {app['company']} ({app['title'][:15]})"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"manage_app_{app['app_id']}")])
        
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"tracker_page_{page-1}"))
    if offset + jobs_per_page < total_apps:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"tracker_page_{page+1}"))
        
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu")])
    kb = InlineKeyboardMarkup(buttons)
    
    if query:
        await query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="MarkdownV2")

async def _render_manage_app_ui(update: Update, context: ContextTypes.DEFAULT_TYPE, app_id: int) -> None:
    """Helper to render the application management UI."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    app = await get_application_by_id(user_id, app_id)
    if not app:
        await query.edit_message_text("Application not found.")
        return

    date_str = app["applied_at"].strftime("%b %d, %Y")
    status_display = app["status"].title().replace("Offer", "🎉 Offer Received!").replace("Interviewing", "🟡 Interviewing")
    
    msg = (
        f"🏢 *{escape_md(app['company'])}*\n"
        f"*{escape_md(app['title'])}*\n"
        f"📍 {escape_md(app['location'] or 'Remote')}\n\n"
        f"🗓 *Date Applied:* {escape_md(date_str)}\n"
        f"📊 *Current Status:* {escape_md(status_display)}\n\n"
        f"*Job Link:* {escape_md(app['url'])}\n\n"
        "What is the new status of this application?"
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 Applied", callback_data=f"updapp_{app_id}_applied"),
            InlineKeyboardButton("🟡 Interviewing", callback_data=f"updapp_{app_id}_interviewing")
        ],
        [
            InlineKeyboardButton("🔴 Rejected", callback_data=f"updapp_{app_id}_rejected"),
            InlineKeyboardButton("🟢 Got Offer!", callback_data=f"updapp_{app_id}_offer")
        ],
        [InlineKeyboardButton("🔙 Back to Tracker", callback_data="tracker")]
    ])
    
    await query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2", disable_web_page_preview=True)

async def manage_app_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View details of a single application to update its status."""
    query = update.callback_query
    await query.answer()

    app_id = int(query.data.split("_")[-1])
    await _render_manage_app_ui(update, context, app_id)

async def update_app_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle status update click."""
    query = update.callback_query
    # Parse data: updapp_{app_id}_{new_status}
    parts = query.data.split("_")
    app_id = int(parts[1])
    new_status = parts[2]
    user_id = update.effective_user.id

    success = await update_application_status(user_id, app_id, new_status)
    if success:
        await query.answer(f"Status updated to {new_status.title()}!", show_alert=True)
        # Refresh the management UI to reflect the new state
        await _render_manage_app_ui(update, context, app_id)
    else:
        await query.answer("Failed to update status. Please try again.", show_alert=True)

async def weekly_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show weekly stats for pro users."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    if user.get("plan", "free") != "pro":
        await query.message.reply_text("This feature is for Pro users only.")
        return
        
    stats = await get_weekly_stats(user_id)
    msg = (
        "📊 *Weekly Summary*\n\n"
        f"You have applied to {stats['weekly_apps']} jobs in the last 7 days\\.\n"
        "Keep up the great work\\! Consistent applications often lead to better interview chances\\."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 View Tracker", callback_data="tracker")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
    ])
    await query.edit_message_text(msg, reply_markup=kb, parse_mode="MarkdownV2")
