"""
Admin analytics handlers.
/analytics  — multi-page dashboard stats (3 pages, Next/Prev buttons)
/users      — paginated list of all users (name + ID)
/user <id>  — full profile of a specific user
All commands are admin-only.
"""
import html
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from loguru import logger
from config import settings
from db.connection import get_pool
from db.tracker import get_ai_usage_stats, get_application_funnel_stats, get_retention_stats, get_click_stats


# ─────────────────────────────────────────────
# Guard helper
# ─────────────────────────────────────────────

def _is_admin(update: Update) -> bool:
    return update.effective_user.id == settings.ADMIN_TELEGRAM_ID


# ─────────────────────────────────────────────
# Page builders
# ─────────────────────────────────────────────

async def _build_page_1(pool) -> str:
    """Page 1: Growth & Users."""
    async with pool.acquire() as conn:
        total_users   = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_deleted IS NOT TRUE")
        onboarded     = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_onboarded = TRUE AND is_deleted IS NOT TRUE")
        with_resume   = await conn.fetchval("SELECT COUNT(*) FROM users WHERE resume_text IS NOT NULL AND is_deleted IS NOT TRUE")
        deleted_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_deleted = TRUE")

        free_count    = await conn.fetchval("SELECT COUNT(*) FROM users WHERE plan = 'free' AND (is_deleted IS NOT TRUE)")
        pro_count     = await conn.fetchval("SELECT COUNT(*) FROM users WHERE plan = 'pro'  AND (is_deleted IS NOT TRUE)")
        trial_count   = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE is_trial = TRUE AND trial_expires_at > NOW() AND is_deleted IS NOT TRUE"
        )

        now         = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start  = today_start - timedelta(days=7)

        new_today  = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at >= $1 AND is_deleted IS NOT TRUE", today_start)
        new_week   = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at >= $1 AND is_deleted IS NOT TRUE", week_start)
        total_jobs = await conn.fetchval("SELECT COUNT(*) FROM manual_jobs WHERE is_active = TRUE")

    return (
        "📊 <b>FroncyBot Analytics</b>  <i>— Page 1 of 3</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 <b>Users</b>\n"
        f"  • Total registered : <b>{total_users}</b>\n"
        f"  • Completed setup  : <b>{onboarded}</b>\n"
        f"  • Uploaded resume  : <b>{with_resume}</b>\n"
        f"  • Deleted accounts : <b>{deleted_count}</b>\n\n"
        "💳 <b>Plans</b>\n"
        f"  • 🆓 Free          : <b>{free_count}</b>\n"
        f"  • ⏳ Active trials  : <b>{trial_count}</b>\n"
        f"  • 💎 Pro           : <b>{pro_count}</b>\n\n"
        "📅 <b>Growth</b>\n"
        f"  • New today        : <b>{new_today}</b>\n"
        f"  • New this week    : <b>{new_week}</b>\n\n"
        "💼 <b>Jobs</b>\n"
        f"  • Active listings  : <b>{total_jobs}</b>\n"
    )


async def _build_page_2() -> str:
    """Page 2: AI Engine usage stats."""
    stats = await get_ai_usage_stats()
    cl  = stats["cover_letter"]
    ats = stats["ats_check"]
    aps = stats["apply_smart"]

    return (
        "🤖 <b>AI Engine Analytics</b>  <i>— Page 2 of 3</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 <b>Apply Smart Kits Generated</b>\n"
        f"  • Today            : <b>{aps['today']}</b>\n"
        f"  • This week        : <b>{aps['week']}</b>\n"
        f"  • This month       : <b>{aps['month']}</b>\n"
        f"  • All time total   : <b>{aps['total']}</b>\n\n"
        "✍️ <b>Cover Letters Generated</b>\n"
        f"  • Today            : <b>{cl['today']}</b>\n"
        f"  • This week        : <b>{cl['week']}</b>\n"
        f"  • This month       : <b>{cl['month']}</b>\n"
        f"  • All time total   : <b>{cl['total']}</b>\n\n"
        "📊 <b>ATS Resume Checks</b>\n"
        f"  • Today            : <b>{ats['today']}</b>\n"
        f"  • This week        : <b>{ats['week']}</b>\n"
        f"  • This month       : <b>{ats['month']}</b>\n"
        f"  • All time total   : <b>{ats['total']}</b>\n"
    )


async def _build_page_3() -> str:
    """Page 3: Application Tracker Kanban funnel."""
    stats = await get_application_funnel_stats()

    tracker_active = stats["total"] > 0
    usage_line = "✅ <b>Yes — users are actively tracking applications!</b>" if tracker_active else "❌ Not yet — no applications tracked."

    return (
        "📋 <b>Application Tracker</b>  <i>— Page 3 of 4</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔍 <b>Tracker Being Used?</b>  {usage_line}\n\n"
        "📈 <b>Application Funnel</b>\n"
        f"  • 📥 Total tracked  : <b>{stats['total']}</b>\n"
        f"  • 🔵 Applied        : <b>{stats['applied']}</b>\n"
        f"  • 🟡 Interviewing   : <b>{stats['interviewing']}</b>\n"
        f"  • 🔴 Rejected       : <b>{stats['rejected']}</b>\n"
        f"  • 🟢 Got Offer!     : <b>{stats['offer']}</b>\n"
    )


async def _build_page_4() -> str:
    """Page 4: Retention & Application Intent."""
    retention = await get_retention_stats()
    clicks    = await get_click_stats()

    # Cover letter copy rate from ai_usage_logs
    pool = get_pool()
    async with pool.acquire() as conn:
        cl_generated = await conn.fetchval(
            "SELECT COUNT(*) FROM ai_usage_logs WHERE feature_type = 'cover_letter'"
        )
        cl_copied = await conn.fetchval(
            "SELECT COUNT(*) FROM ai_usage_logs WHERE feature_type = 'cover_letter_copied'"
        )
    copy_rate = f"{round((cl_copied / cl_generated) * 100)}%" if cl_generated else "N/A"

    return (
        "🔄 <b>Retention &amp; Intent</b>  <i>— Page 4 of 4</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📅 <b>Activity &amp; Retention</b>\n"
        f"  • DAU (today)        : <b>{retention['dau']}</b>\n"
        f"  • WAU (last 7 days)  : <b>{retention['wau']}</b>\n"
        f"  • Returning users    : <b>{retention['returning']}</b>\n"
        f"  • D7 retention       : <b>{retention['d7']}</b>\n"
        f"  • D30 retention      : <b>{retention['d30']}</b>\n\n"
        "🔗 <b>Job Link Clicks (Apply Intent)</b>\n"
        f"  • Today              : <b>{clicks['today']}</b>\n"
        f"  • This week          : <b>{clicks['week']}</b>\n"
        f"  • This month         : <b>{clicks['month']}</b>\n"
        f"  • All time           : <b>{clicks['total']}</b>\n\n"
        "✍️ <b>Cover Letter Utility</b>\n"
        f"  • Total generated    : <b>{cl_generated or 0}</b>\n"
        f"  • Total copied       : <b>{cl_copied or 0}</b>\n"
        f"  • Copy rate          : <b>{copy_rate}</b>\n"
    )


def _analytics_keyboard(page: int) -> InlineKeyboardMarkup:
    """Build Next/Prev navigation for analytics pages (1 through 4)."""
    row = []
    if page > 1:
        row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"analytics_page_{page - 1}"))
    if page < 4:
        row.append(InlineKeyboardButton("Next ▶️", callback_data=f"analytics_page_{page + 1}"))
    return InlineKeyboardMarkup([row]) if row else None


# ─────────────────────────────────────────────
# /analytics
# ─────────────────────────────────────────────

async def analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show analytics page 1 to admin."""
    if not _is_admin(update):
        return

    pool = get_pool()
    msg = await _build_page_1(pool)
    kb  = _analytics_keyboard(1)
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)


async def analytics_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Next/Prev page navigation for /analytics."""
    query = update.callback_query
    if not _is_admin(update):
        await query.answer()
        return

    await query.answer()
    page = int(query.data.split("_")[-1])
    pool = get_pool()

    if page == 1:
        msg = await _build_page_1(pool)
    elif page == 2:
        msg = await _build_page_2()
    elif page == 3:
        msg = await _build_page_3()
    elif page == 4:
        msg = await _build_page_4()
    else:
        return

    kb = _analytics_keyboard(page)
    await query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)


# ─────────────────────────────────────────────
# /users  — paginated user list
# ─────────────────────────────────────────────

USERS_PAGE_SIZE = 20


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show paginated list of all users."""
    if not _is_admin(update):
        return
    await _send_users_page(update, context, page=1)


async def users_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle page-turn callbacks for /users."""
    if not _is_admin(update):
        await update.callback_query.answer()
        return
    page = int(update.callback_query.data.split("_")[-1])
    await update.callback_query.answer()
    await _send_users_page(update, context, page=page, edit=True)


async def _send_users_page(update: Update, context, page: int, edit: bool = False, show_deleted: bool = False):
    pool = get_pool()
    offset = (page - 1) * USERS_PAGE_SIZE

    condition = "is_deleted = TRUE" if show_deleted else "is_deleted IS NOT TRUE"

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM users WHERE {condition}")
        rows  = await conn.fetch(
            f"""
            SELECT telegram_id, first_name, username, plan, is_onboarded, created_at
            FROM users
            WHERE {condition}
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            USERS_PAGE_SIZE, offset
        )

    total_pages = max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)

    title = "🗑 <b>Deleted Accounts</b>" if show_deleted else "👥 <b>Users</b>"
    cb_prefix = "adm_delusers" if show_deleted else "adm_users"

    lines = [f"{title}  (Page {page}/{total_pages} · {total} total)\n"]
    for row in rows:
        name     = html.escape(row["first_name"] or "Unknown")
        username = f"@{html.escape(row['username'])}" if row["username"] else "—"
        plan_tag = {"pro": "💎", "free": "🆓"}.get(row["plan"] or "free", "🆓")
        onb_tag  = "✅" if row["is_onboarded"] else "⏳"
        lines.append(
            f"{onb_tag} {plan_tag} <b>{name}</b> {username}\n"
            f"   <code>{row['telegram_id']}</code>"
        )

    msg = "\n".join(lines)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"{cb_prefix}_{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"{cb_prefix}_{page + 1}"))
    kb = InlineKeyboardMarkup([nav]) if nav else None

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)


async def deleted_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show paginated list of deleted users."""
    if not _is_admin(update):
        return
    await _send_users_page(update, context, page=1, show_deleted=True)


async def deleted_users_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle page-turn callbacks for /deletedusers."""
    if not _is_admin(update):
        await update.callback_query.answer()
        return
    page = int(update.callback_query.data.split("_")[-1])
    await update.callback_query.answer()
    await _send_users_page(update, context, page=page, edit=True, show_deleted=True)


# ─────────────────────────────────────────────
# /user <telegram_id>  — full user profile
# ─────────────────────────────────────────────

async def user_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full profile of a specific user. Usage: /user 8619554269"""
    if not _is_admin(update):
        return

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "⚠️ Usage: <code>/user &lt;telegram_id&gt;</code>\n"
            "Example: <code>/user 8619554269</code>",
            parse_mode="HTML"
        )
        return

    target_id = int(args[0])
    pool = get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", target_id)

    if not row:
        await update.message.reply_text(f"❌ No user found with ID <code>{target_id}</code>.", parse_mode="HTML")
        return

    u = dict(row)

    name        = html.escape(u.get("first_name") or "Unknown")
    username    = f"@{html.escape(u['username'])}" if u.get("username") else "—"
    plan        = (u.get("plan") or "free").upper()
    onboarded   = "✅ Yes" if u.get("is_onboarded") else "❌ No"
    has_resume  = "✅ Yes" if u.get("resume_text") else "❌ No"
    skills      = ", ".join(u.get("skills") or []) or "None"
    location    = html.escape(str(u.get("location_pref") or "—"))
    role        = html.escape(str(u.get("role_pref") or "—"))
    exp         = html.escape(str(u.get("experience_level") or "—"))
    batch       = html.escape(str(u.get("batch_year") or "—"))
    alert_time  = html.escape(str(u.get("alert_time") or "—"))
    joined      = u["created_at"].strftime("%d %b %Y, %H:%M UTC") if u.get("created_at") else "—"

    trial_line = ""
    if u.get("is_trial"):
        exp_at = u.get("trial_expires_at")
        if exp_at:
            now = datetime.now(timezone.utc)
            exp_at_aware = exp_at.replace(tzinfo=timezone.utc) if exp_at.tzinfo is None else exp_at
            remaining    = exp_at_aware - now
            if remaining.total_seconds() > 0:
                h = int(remaining.total_seconds() // 3600)
                trial_line = f"\n  ⏳ Trial expires in <b>{h}h</b>"
            else:
                trial_line = "\n  ⚠️ Trial <b>expired</b>"

    msg = (
        f"👤 <b>{name}</b>  {username}\n"
        f"🆔 <code>{target_id}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Joined      : {joined}\n"
        f"✅ Onboarded   : {onboarded}\n"
        f"💳 Plan        : <b>{plan}</b>{trial_line}\n"
        f"📄 Resume      : {has_resume}\n\n"
        f"🛠 Skills      : {html.escape(skills)}\n"
        f"📍 Location    : {location}\n"
        f"👔 Role        : {role}\n"
        f"💼 Experience  : {exp} yrs\n"
        f"🎓 Batch       : {batch}\n"
        f"🔔 Alert time  : {alert_time}\n"
    )

    await update.message.reply_text(msg, parse_mode="HTML")
