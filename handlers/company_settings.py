"""
Company Preferences & Filtering Handlers (RFC-004)
Allows users to manage target company watchlists, mute employers, and explore curated bundles.
"""
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from loguru import logger

from db.users import get_user
from db.company_prefs import (
    get_user_prefs_detail,
    follow_company,
    unfollow_company,
    mute_company,
    unmute_company,
    follow_bundle,
    set_company_filter_mode,
    search_companies,
    get_company_by_id,
)
from utils.helpers import get_effective_plan
from utils.messages import escape_md


# ──────────────────────────────────────────────
# In-Alert / In-Detail Callback Actions
# ──────────────────────────────────────────────

async def company_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles compact callback actions from alert/detail keyboards:
      - cf_fw:{cid}   -> Follow company
      - cf_unfw:{cid} -> Unfollow company
      - cf_mt:{cid}   -> Mute company
      - cf_unmt:{cid} -> Unmute company (undo)
    """
    query = update.callback_query
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    user = await get_user(user_id, bot_id=bot_id)
    if not user:
        await query.answer("Please start the bot first with /start", show_alert=True)
        return

    plan = get_effective_plan(user)
    data = query.data

    try:
        prefix, cid_str = data.split(":")
        company_id = int(cid_str)
    except Exception:
        await query.answer()
        return

    company = await get_company_by_id(company_id)
    cname = company.get("name", "Company") if company else "Company"
    cname_short = cname[:15]

    if prefix == "cf_fw":
        res = await follow_company(user_id, company_id, plan=plan)
        if res.get("success"):
            if res.get("already_following"):
                await query.answer(f"You are already following {cname}.", show_alert=False)
            else:
                cap_info = f" ({res['count']}/{res['cap']} used)" if res.get("cap") else f" (Total: {res['count']})"
                msg_toast = f"⭐ Following {cname}!{cap_info}"
                if res.get("converted_from_mute"):
                    msg_toast = f"✅ Unmuted and added {cname} to followed companies."
                await query.answer(msg_toast, show_alert=False)

            # Update inline button to unfollow toggle
            await _update_alert_keyboard_row(query, company_id, is_following=True)
        else:
            if plan not in ("pro", "trial", "proplus", "premium"):
                await query.answer(
                    "⭐ Free tier limit reached (5/5). Upgrade to Pro to follow unlimited companies!",
                    show_alert=True
                )
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"⭐ *Company Watchlist Limit Reached*\n\n"
                            f"Free members can follow up to *5 Dream Companies*\\.\n"
                            f"Upgrade to *Froncy Pro* to follow *unlimited companies* and unlock Watchlist\\-Only instant drops\\!"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💎 Upgrade to Pro — ₹199/mo", callback_data="upgrade_pro")],
                            [InlineKeyboardButton("⚙️ Manage Follows", callback_data="settings_comp_edit_follows")]
                        ]),
                        parse_mode="MarkdownV2"
                    )
                except Exception:
                    pass
            else:
                await query.answer("Could not follow company.", show_alert=True)

    elif prefix == "cf_unfw":
        await unfollow_company(user_id, company_id)
        await query.answer(f"Removed {cname} from your followed companies.", show_alert=False)
        await _update_alert_keyboard_row(query, company_id, is_following=False)

    elif prefix == "cf_mt":
        res = await mute_company(user_id, company_id)
        if res.get("success"):
            msg_toast = f"🔕 Muted {cname}. You will not receive alerts from this company."
            if res.get("converted_from_follow"):
                msg_toast = f"🔕 Muted {cname} (removed from followed companies)."
            await query.answer(msg_toast, show_alert=False)
            await _update_alert_keyboard_mute(query, company_id, is_muted=True, company_name=cname_short)
        else:
            await query.answer("Could not mute company.", show_alert=True)

    elif prefix == "cf_unmt":
        await unmute_company(user_id, company_id)
        await query.answer(f"Unmuted {cname}.", show_alert=False)
        await _update_alert_keyboard_mute(query, company_id, is_muted=False, company_name=cname_short)


async def _update_alert_keyboard_row(query, company_id: int, is_following: bool) -> None:
    """Updates follow button in-place without disturbing other rows."""
    if not query.message or not query.message.reply_markup:
        return
    kb = query.message.reply_markup.inline_keyboard
    new_rows = []
    company = await get_company_by_id(company_id)
    cname_short = (company.get("name", "Company") if company else "Company")[:15]

    for row in kb:
        new_row = []
        for btn in row:
            if btn.callback_data in (f"cf_fw:{company_id}", f"cf_unfw:{company_id}"):
                if is_following:
                    new_row.append(InlineKeyboardButton("✅ Following", callback_data=f"cf_unfw:{company_id}"))
                else:
                    new_row.append(InlineKeyboardButton(f"⭐ Follow {cname_short}", callback_data=f"cf_fw:{company_id}"))
            else:
                new_row.append(btn)
        new_rows.append(new_row)

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_rows))
    except Exception:
        pass


async def _update_alert_keyboard_mute(query, company_id: int, is_muted: bool, company_name: str) -> None:
    """Updates mute button in-place to show/hide Undo."""
    if not query.message or not query.message.reply_markup:
        return
    kb = query.message.reply_markup.inline_keyboard
    new_rows = []
    for row in kb:
        new_row = []
        for btn in row:
            if btn.callback_data in (f"cf_mt:{company_id}", f"cf_unmt:{company_id}"):
                if is_muted:
                    new_row.append(InlineKeyboardButton(f"↩️ Undo Mute {company_name}", callback_data=f"cf_unmt:{company_id}"))
                else:
                    new_row.append(InlineKeyboardButton("🔕 Mute", callback_data=f"cf_mt:{company_id}"))
            else:
                new_row.append(btn)
        new_rows.append(new_row)

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_rows))
    except Exception:
        pass


# ──────────────────────────────────────────────
# Settings: Target Companies Menu
# ──────────────────────────────────────────────

async def settings_companies_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Renders Company Preferences overview."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    user = await get_user(user_id, bot_id=bot_id)
    if not user:
        return

    plan = get_effective_plan(user)
    is_pro = plan in ("pro", "trial", "proplus", "premium")

    prefs = await get_user_prefs_detail(user_id, is_pro=is_pro)
    mode = prefs["mode"]
    active_follows = prefs["active_follows"]
    frozen_follows = prefs["frozen_follows"]
    mutes = prefs["mutes"]
    cap = prefs["cap"]

    mode_label = "🎯 *Watchlist Only* \\(Alerts from followed companies only\\)" if mode == "watchlist" else "🌐 *All Companies* \\(Profile matches across all 1,000\\+ companies\\)"

    # Format followed list
    if active_follows:
        f_lines = "\n".join([f"• {escape_md(c['name'])}" for c in active_follows[:6]])
        if len(active_follows) > 6:
            f_lines += f"\n_\\.\\.\\.and {len(active_follows) - 6} more_"
    else:
        f_lines = "_None yet \\(Tap search or bundles below to add\\)_"

    frozen_note = ""
    if frozen_follows:
        frozen_note = f"\n❄️ *{len(frozen_follows)} frozen follows* \\(Upgrade to Pro to unfreeze\\)\n"

    # Format muted list
    if mutes:
        m_lines = "\n".join([f"• {escape_md(c['name'])}" for c in mutes[:5]])
        if len(mutes) > 5:
            m_lines += f"\n_\\.\\.\\.and {len(mutes) - 5} more_"
    else:
        m_lines = "_None \\(Mute current employer to prevent alerts\\)_"

    if is_pro:
        follows_header = f"⭐ *Followed Companies* \\({len(active_follows)}\\):"
        follows_desc = "_⚡ Unlimited company follows with instant alerts \\& feed priority\\._"
    else:
        follows_header = f"⭐ *Followed Companies* \\({len(active_follows)}/5\\):"
        follows_desc = "_📌 Pinned to top of your Daily Feed \\& prioritized for weekly sample drops\\._"

    mutes_header = f"🚫 *Muted Companies / Current Employer* \\({len(mutes)}\\):"
    mutes_desc = "_Muted companies are completely hidden across all alerts and browse\\._"

    text = (
        f"🏢 *Target Company Preferences*\n\n"
        f"Current Mode: {mode_label}\n\n"
        f"{follows_header}\n"
        f"{f_lines}\n"
        f"{frozen_note}\n"
        f"{follows_desc}\n\n"
        f"{mutes_header}\n"
        f"{m_lines}\n"
        f"{mutes_desc}"
    )

    buttons = [
        [
            InlineKeyboardButton("🔍 Search & Add Company", callback_data="settings_comp_search"),
            InlineKeyboardButton("📦 Curated Bundles", callback_data="settings_comp_bundles"),
        ],
    ]

    # Mode toggle for Pro users
    if is_pro:
        toggle_btn = (
            InlineKeyboardButton("🔄 Switch to All Companies", callback_data="settings_comp_mode_all")
            if mode == "watchlist" else
            InlineKeyboardButton("🎯 Switch to Watchlist Only", callback_data="settings_comp_mode_watchlist")
        )
        buttons.append([toggle_btn])
    else:
        buttons.append([InlineKeyboardButton("⭐ Unlock Watchlist-Only Mode (Pro)", callback_data="upgrade_pro")])

    buttons.append([
        InlineKeyboardButton(f"✏️ Manage Following ({len(active_follows)})", callback_data="settings_comp_edit_follows"),
        InlineKeyboardButton(f"🚫 Manage Muted ({len(mutes)})", callback_data="settings_comp_edit_mutes"),
    ])
    buttons.append([InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")])

    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="MarkdownV2")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Error editing company preferences menu: {e}")


async def settings_comp_mode_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switches company filter mode between 'all' and 'watchlist'."""
    query = update.callback_query
    user_id = update.effective_user.id
    target_mode = "watchlist" if "watchlist" in query.data else "all"

    bot_id = context.bot_data.get("bot_id", 1)
    user = await get_user(user_id, bot_id=bot_id)
    plan = get_effective_plan(user)
    is_pro = plan in ("pro", "trial", "proplus", "premium")

    res = await set_company_filter_mode(user_id, target_mode, is_pro=is_pro)
    if res.get("success"):
        toast = "🎯 Switched to Watchlist Only mode." if target_mode == "watchlist" else "🌐 Switched to All Companies mode."
        await query.answer(toast, show_alert=False)
        await settings_companies_menu(update, context)
    else:
        if res.get("reason") == "empty_watchlist":
            await query.answer(
                "⚠️ Your Watchlist is empty! Follow at least 1 company before switching to Watchlist Only mode.",
                show_alert=True
            )
        elif res.get("reason") == "pro_required":
            await query.answer("⭐ Watchlist-Only mode requires Froncy Pro. Type /upgrade to unlock!", show_alert=True)
        else:
            await query.answer("Could not update mode.", show_alert=True)


async def settings_comp_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompts user to type a company name to search."""
    query = update.callback_query
    await query.answer()

    context.user_data["comp_search_active"] = True
    context.user_data["comp_search_ts"] = datetime.now(timezone.utc).timestamp()

    text = (
        "🔍 *Search Monitored Companies*\n\n"
        "Type the name \\(or part of it\\) of any company you want to follow or mute:\n\n"
        "Examples: `Razorpay`, `Google`, `Swiggy`, `Uber`, `Stripe`\n\n"
        "_Send your message below or tap Cancel:_"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="settings_companies")]
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="MarkdownV2")


async def handle_company_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handles user text message when search mode is active.
    Returns True if handled, False otherwise.
    """
    if not context.user_data.get("comp_search_active"):
        return False

    # Check 60-second timeout
    ts = context.user_data.get("comp_search_ts", 0)
    now = datetime.now(timezone.utc).timestamp()
    if now - ts > 60:
        context.user_data["comp_search_active"] = False
        return False

    query_text = (update.message.text or "").strip()
    if not query_text or len(query_text) < 2:
        await update.message.reply_text("Please type at least 2 characters to search for a company:")
        return True

    results = await search_companies(query_text, limit=5)
    context.user_data["comp_search_active"] = False

    if not results:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search Again", callback_data="settings_comp_search")],
            [InlineKeyboardButton("🔙 Company Preferences", callback_data="settings_companies")]
        ])
        await update.message.reply_text(
            f"No monitored companies found matching '{escape_md(query_text)}'\\.\n\n"
            f"We currently monitor top tier\\-1 companies & startups\\. Try another search term:",
            reply_markup=kb,
            parse_mode="MarkdownV2"
        )
        return True

    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    user = await get_user(user_id, bot_id=bot_id)
    plan = get_effective_plan(user)
    is_pro = plan in ("pro", "trial", "proplus", "premium")
    prefs = await get_user_prefs_detail(user_id, is_pro=is_pro)

    followed_ids = {c["id"] for c in prefs["active_follows"]}
    muted_ids = {c["id"] for c in prefs["mutes"]}

    buttons = []
    res_lines = []
    for i, c in enumerate(results, 1):
        cid = c["id"]
        cname = c["name"]
        res_lines.append(f"{i}\\. *{escape_md(cname)}*")

        row = []
        if cid in followed_ids:
            row.append(InlineKeyboardButton(f"✅ Following {cname[:12]}", callback_data=f"cf_unfw:{cid}"))
        else:
            row.append(InlineKeyboardButton(f"⭐ Follow {cname[:12]}", callback_data=f"cf_fw:{cid}"))

        if cid in muted_ids:
            row.append(InlineKeyboardButton(f"🔕 Muted", callback_data=f"cf_unmt:{cid}"))
        else:
            row.append(InlineKeyboardButton(f"🔕 Mute", callback_data=f"cf_mt:{cid}"))

        buttons.append(row)

    buttons.append([
        InlineKeyboardButton("🔍 Search Another", callback_data="settings_comp_search"),
        InlineKeyboardButton("🔙 Preferences", callback_data="settings_companies")
    ])

    await update.message.reply_text(
        f"Found {len(results)} matching companies:\n\n" + "\n".join(res_lines) + "\n\n_Tap below to follow or mute:_ ",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="MarkdownV2"
    )
    return True


async def settings_comp_bundles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists curated bundles for 1-tap follow."""
    query = update.callback_query
    await query.answer()

    from db.connection import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        bundles = await conn.fetch("""
            SELECT b.id, b.name, b.emoji, b.description, COUNT(m.company_id) as member_count
            FROM company_bundles b
            LEFT JOIN company_bundle_members m ON b.id = m.bundle_id
            GROUP BY b.id, b.name, b.emoji, b.description
            ORDER BY b.id ASC
        """)

    lines = [
        "📦 *Curated Company Bundles*\n",
        "Follow entire collections of top\\-tier companies in 1 tap:\n"
    ]
    buttons = []
    for b in bundles:
        bid = b["id"]
        bname = b["name"]
        bemoji = b["emoji"]
        cnt = b["member_count"]
        lines.append(f"{bemoji} *{escape_md(bname)}* \\({cnt} companies\\)\n_{escape_md(b['description'] or '')}_\n")
        buttons.append([InlineKeyboardButton(f"➕ Follow {bname} ({cnt})", callback_data=f"cf_bdl_{bid}")])

    buttons.append([InlineKeyboardButton("🔙 Back to Companies", callback_data="settings_companies")])

    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="MarkdownV2")


async def handle_bundle_follow_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles 1-tap bundle follow."""
    query = update.callback_query
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    user = await get_user(user_id, bot_id=bot_id)
    plan = get_effective_plan(user)

    bundle_id = int(query.data.split("_")[-1])
    res = await follow_bundle(user_id, bundle_id, plan=plan)

    if res.get("success"):
        await query.answer(f"🎉 Followed all companies in bundle! Total: {res.get('total')}", show_alert=True)
        await settings_companies_menu(update, context)
    else:
        reason = res.get("reason")
        if reason == "pro_required":
            await query.answer("⭐ Curated 1-tap bundles require Froncy Pro. Type /upgrade to unlock!", show_alert=True)
        else:
            await query.answer("Could not add bundle.", show_alert=True)


PAGE_SIZE = 8

async def settings_comp_edit_follows(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = None) -> None:
    """Renders active follows list with 1-tap unfollow buttons and clean pagination."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    user = await get_user(user_id, bot_id=bot_id)
    plan = get_effective_plan(user)
    is_pro = plan in ("pro", "trial", "proplus", "premium")

    if page is None:
        page = 0
        if query.data and ":" in query.data:
            try:
                page = int(query.data.split(":")[-1])
            except Exception:
                page = 0

    prefs = await get_user_prefs_detail(user_id, is_pro=is_pro)
    follows = prefs["active_follows"]

    if not follows:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search Companies", callback_data="settings_comp_search")],
            [InlineKeyboardButton("🔙 Back to Companies", callback_data="settings_companies")]
        ])
        await query.edit_message_text("⭐ *Followed Companies*\n\nYou are not following any companies yet\\.", reply_markup=kb, parse_mode="MarkdownV2")
        return

    total_pages = max(1, (len(follows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page >= total_pages:
        page = total_pages - 1

    start_idx = page * PAGE_SIZE
    page_items = follows[start_idx : start_idx + PAGE_SIZE]

    buttons = []
    for c in page_items:
        cid = c["id"]
        cname = c["name"]
        buttons.append([
            InlineKeyboardButton(f"❌ Unfollow {cname[:20]}", callback_data=f"cf_unfw_menu:{cid}:{page}")
        ])

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"settings_comp_edit_follows:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data=f"settings_comp_edit_follows:{page}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"settings_comp_edit_follows:{page + 1}"))
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🔙 Back to Companies", callback_data="settings_companies")])

    cap_str = f"/{prefs['cap']}" if prefs.get("cap") else ""
    text = f"⭐ *Manage Followed Companies* \\({len(follows)}{cap_str}\\):\n\n_Tap any company below to unfollow:_"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="MarkdownV2")


async def handle_menu_unfollow_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles unfollowing from the settings edit list."""
    query = update.callback_query
    user_id = update.effective_user.id
    parts = query.data.split(":")
    cid = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    company = await get_company_by_id(cid)
    cname = company.get("name", "Company") if company else "Company"

    await unfollow_company(user_id, cid)
    await query.answer(f"Unfollowed {cname}.", show_alert=False)

    # Reload edit follows menu with preserved page
    await settings_comp_edit_follows(update, context, page=page)


async def settings_comp_edit_mutes(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = None) -> None:
    """Renders muted companies list with 1-tap unmute buttons and clean pagination."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    bot_id = context.bot_data.get("bot_id", 1)
    user = await get_user(user_id, bot_id=bot_id)
    plan = get_effective_plan(user)
    is_pro = plan in ("pro", "trial", "proplus", "premium")

    if page is None:
        page = 0
        if query.data and ":" in query.data:
            try:
                page = int(query.data.split(":")[-1])
            except Exception:
                page = 0

    prefs = await get_user_prefs_detail(user_id, is_pro=is_pro)
    mutes = prefs["mutes"]

    if not mutes:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search to Mute", callback_data="settings_comp_search")],
            [InlineKeyboardButton("🔙 Back to Companies", callback_data="settings_companies")]
        ])
        await query.edit_message_text("🚫 *Muted Companies*\n\nYou have not muted any companies\\.", reply_markup=kb, parse_mode="MarkdownV2")
        return

    total_pages = max(1, (len(mutes) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page >= total_pages:
        page = total_pages - 1

    start_idx = page * PAGE_SIZE
    page_items = mutes[start_idx : start_idx + PAGE_SIZE]

    buttons = []
    for c in page_items:
        cid = c["id"]
        cname = c["name"]
        buttons.append([
            InlineKeyboardButton(f"🔊 Unmute {cname[:20]}", callback_data=f"cf_unmt_menu:{cid}:{page}")
        ])

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"settings_comp_edit_mutes:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data=f"settings_comp_edit_mutes:{page}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"settings_comp_edit_mutes:{page + 1}"))
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🔙 Back to Companies", callback_data="settings_companies")])

    text = f"🚫 *Muted Companies / Current Employer* \\({len(mutes)}\\):\n\n_Tap any company below to unmute:_"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="MarkdownV2")


async def handle_menu_unmute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles unmuting from the settings edit list."""
    query = update.callback_query
    user_id = update.effective_user.id
    parts = query.data.split(":")
    cid = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    company = await get_company_by_id(cid)
    cname = company.get("name", "Company") if company else "Company"

    await unmute_company(user_id, cid)
    await query.answer(f"Unmuted {cname}.", show_alert=False)

    # Reload edit mutes menu with preserved page
    await settings_comp_edit_mutes(update, context, page=page)
