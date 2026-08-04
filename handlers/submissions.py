"""
Community Job Submission handler.

User flow:
  User sends a URL  ->  bot queues it + pings admin

Admin flow:
  Admin gets alert with [Start Legitimacy Check] button
  -> bot shows a toggleable inline checklist
  -> Admin clicks [Reject Job] or [Approve Job]
  -> If rejected: bot sends Legitimacy Check report to user (fail)
  -> If approved: bot enters /addjob-like conversation to paste job text,
     parses + inserts job, then notifies user (pass + apply smart link)
"""
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, ConversationHandler, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters,
)
from loguru import logger
from config import settings
from db.submissions import (
    create_submission, get_submission, get_pending_submissions,
    check_url_status, mark_submission_rejected, mark_submission_approved,
)
from db.manual_jobs import add_manual_job
from utils.helpers import normalize_job_url


# ── Conversation state for admin job-text entry after approval ──────────────
WAITING_FOR_SUBMISSION_JOB_TEXT = 50
WAITING_FOR_DUPLICATE_JOB_ID = 51

# ── Checklist items: (label, callback_data_key) ──────────────────────────────
CHECKLIST_ITEMS = [
    ("Company exists",        "company"),
    ("Recruiter verified",    "recruiter"),
    ("Career page exists",    "career"),
    ("Salary realistic",      "salary"),
    ("Scam / Requested payment", "scam"),
]

URL_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{2,256}\.[a-z]{2,6}\b(?:[-a-zA-Z0-9@:%_\+.~#?&//=]*)",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# USER FLOW: Intercept a URL message
# ─────────────────────────────────────────────────────────────────────────────

async def handle_url_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called when an onboarded user sends a plain URL."""
    # Skip if admin sent it (they use /addjob for their own URLs)
    if update.effective_user.id == settings.ADMIN_TELEGRAM_ID:
        return

    text = update.message.text.strip()
    match = URL_REGEX.search(text)
    if not match:
        return

    url = match.group(0).rstrip(".,;)")
    normalized = normalize_job_url(url)
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Unknown"

    # Duplicate check
    duplicate_state = await check_url_status(normalized)
    
    if duplicate_state:
        if duplicate_state.get("status") == "live":
            job_id = duplicate_state.get("job_id")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Apply Smart", callback_data=f"apply_smart_{job_id}")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
            ])
            await update.message.reply_text(
                "🎯 <b>Great find!</b>\n\n"
                "This exact role is already live on our board.\n"
                "Tap below to get your Apply Kit for it!",
                parse_mode="HTML",
                reply_markup=kb
            )
            return
        elif duplicate_state.get("status") == "pending":
            await update.message.reply_text(
                "👀 This job is already in our review queue! "
                "We will notify you once it goes live."
            )
            return

    # Save to DB (we save the original URL)
    submission_id = await create_submission(user_id, url)
    logger.info(f"New job submission #{submission_id} from user {user_id}: {url}")

    # Tell user we got it
    await update.message.reply_text(
        "📥 <b>Job Submission Received!</b>\n\n"
        "Thanks for contributing to the community! 🙌\n\n"
        "Our team will review this job for legitimacy.\n"
        "We'll send you a <b>Legitimacy Report</b> and notify you "
        "once it's verified and added to the board.\n\n"
        "<i>Estimated review time: a few hours</i>",
        parse_mode="HTML",
    )

    # Alert admin
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔍 Start Legitimacy Check", callback_data=f"sub_check_{submission_id}"),
        InlineKeyboardButton("🗑 Ignore", callback_data=f"sub_ignore_{submission_id}"),
    ]])
    await context.bot.send_message(
        chat_id=settings.ADMIN_TELEGRAM_ID,
        text=(
            f"📥 <b>New Job Submitted</b>\n\n"
            f"👤 User: <code>{user_id}</code> ({user_name})\n"
            f"🔗 URL: {url}\n"
            f"📋 Submission ID: <code>{submission_id}</code>"
        ),
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN FLOW: Start Legitimacy Check — show checklist
# ─────────────────────────────────────────────────────────────────────────────

def _build_checklist_keyboard(submission_id: int, checks: dict) -> InlineKeyboardMarkup:
    """Build the toggleable checklist inline keyboard."""
    rows = []
    for label, key in CHECKLIST_ITEMS:
        is_scam_item = key == "scam"
        is_checked = checks.get(key, False)

        if is_scam_item:
            icon = "🚨" if is_checked else "✅"  # scam item is bad when ON
        else:
            icon = "✅" if is_checked else "❌"

        rows.append([InlineKeyboardButton(
            f"{icon} {label}",
            callback_data=f"sub_toggle_{submission_id}_{key}",
        )])

    rows.append([
        InlineKeyboardButton("❌ Reject", callback_data=f"sub_reject_{submission_id}"),
        InlineKeyboardButton("🔗 Mark as Duplicate", callback_data=f"sub_duplicate_{submission_id}"),
    ])
    rows.append([
        InlineKeyboardButton("✅ Approve Job", callback_data=f"sub_approve_{submission_id}"),
    ])
    return InlineKeyboardMarkup(rows)


async def sub_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin clicked Start Legitimacy Check."""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return

    submission_id = int(query.data.split("_")[-1])
    sub = await get_submission(submission_id)
    if not sub:
        await query.edit_message_text("❌ Submission not found.")
        return

    # Init empty check state in context
    context.user_data[f"sub_checks_{submission_id}"] = {key: False for _, key in CHECKLIST_ITEMS}

    kb = _build_checklist_keyboard(submission_id, context.user_data[f"sub_checks_{submission_id}"])
    await query.edit_message_text(
        f"🔍 <b>Legitimacy Check</b> — Submission #{submission_id}\n\n"
        f"URL: {sub['url']}\n\n"
        "Toggle each item, then submit your decision:",
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


async def sub_ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin clicked Ignore — silently removes the admin alert."""
    query = update.callback_query
    await query.answer("Submission ignored.")
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return
    await query.edit_message_reply_markup(reply_markup=None)


async def sub_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin toggled a checklist item."""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return

    parts = query.data.split("_")  # sub_toggle_<id>_<key>
    submission_id = int(parts[2])
    key = parts[3]

    state_key = f"sub_checks_{submission_id}"
    checks = context.user_data.get(state_key, {key: False for _, key in CHECKLIST_ITEMS})
    checks[key] = not checks.get(key, False)
    context.user_data[state_key] = checks

    kb = _build_checklist_keyboard(submission_id, checks)
    await query.edit_message_reply_markup(reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN FLOW: Reject
# ─────────────────────────────────────────────────────────────────────────────

def _build_report_text(checks: dict, approved: bool) -> str:
    """Build the Legitimacy Check report shown to the user."""
    lines = ["🔍 <b>Legitimacy Check Complete</b>\n"]
    positives = 0
    total_positive_items = len(CHECKLIST_ITEMS) - 1  # exclude scam item from score

    for label, key in CHECKLIST_ITEMS:
        is_scam_item = key == "scam"
        is_checked = checks.get(key, False)

        if is_scam_item:
            if is_checked:
                lines.append(f"🚨 Requested payment / Scam signal detected")
            else:
                lines.append(f"✓ No obvious scam signals")
        else:
            if is_checked:
                lines.append(f"✓ {label}")
                positives += 1
            else:
                lines.append(f"⚠ {label.replace('exists','not found').replace('verified','not verified').replace('realistic','unrealistic')}")

    # Adjust score: scam = big penalty
    score = int((positives / total_positive_items) * 100)
    if checks.get("scam"):
        score = max(0, score - 40)

    lines.append(f"\n<b>Legitimacy Score: {score}/100</b>")
    return "\n".join(lines)


async def sub_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin clicked Reject Job — notify user with the legitimacy report."""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return

    submission_id = int(query.data.split("_")[-1])
    sub = await get_submission(submission_id)
    if not sub:
        await query.edit_message_text("❌ Submission not found.")
        return

    checks = context.user_data.get(f"sub_checks_{submission_id}", {})
    await mark_submission_rejected(submission_id)

    report = _build_report_text(checks, approved=False)
    report += (
        "\n\n❌ <b>This job did not pass our safety standards and was not added to the board.</b>\n"
        "If you believe this is a mistake, please try submitting again with the official company careers page link."
    )

    # Notify the user
    try:
        await context.bot.send_message(
            chat_id=sub["telegram_id"],
            text=report,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Could not notify user {sub['telegram_id']} of rejection: {e}")

    await query.edit_message_text(
        f"✅ Submission #{submission_id} rejected. User notified.",
        parse_mode="HTML",
    )
    logger.info(f"Submission #{submission_id} rejected by admin.")


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN FLOW: Approve — then enter job-text conversation
# ─────────────────────────────────────────────────────────────────────────────

async def sub_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicked Approve Job — ask them to paste the job text."""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return ConversationHandler.END

    submission_id = int(query.data.split("_")[-1])
    sub = await get_submission(submission_id)
    if not sub:
        await query.edit_message_text("❌ Submission not found.")
        return ConversationHandler.END

    # Store context for the next step
    context.user_data["pending_submission_id"] = submission_id
    context.user_data["pending_submission_url"] = sub["url"]
    context.user_data["pending_submission_user"] = sub["telegram_id"]
    context.user_data["pending_submission_checks"] = context.user_data.get(f"sub_checks_{submission_id}", {})

    await query.edit_message_text(
        f"✅ <b>Approved!</b> Submission #{submission_id}\n\n"
        "Now paste the full job description text below so I can parse it.\n"
        "Use the same format as <code>/addjob</code>:\n\n"
        "<code>React Developer - Oracle\n"
        "Job link: https://...\n"
        "📍 Remote | Fulltime | 25K/Month\n"
        "🎓 2025/2026 | 0-2 YOE\n"
        "🏷 React, TypeScript, CSS\n"
        "👤 HR | Jane Doe | jane@company.com | linkedin.com/in/jane</code>\n\n"
        "Type /cancelsubmission to abort.",
        parse_mode="HTML",
    )
    return WAITING_FOR_SUBMISSION_JOB_TEXT


async def parse_and_add_submitted_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parse job text for an approved submission and insert it."""
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return ConversationHandler.END

    text = update.message.text.strip()
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    submission_id = context.user_data.get("pending_submission_id")
    submitter_id  = context.user_data.get("pending_submission_user")
    checks        = context.user_data.get("pending_submission_checks", {})

    if not submission_id:
        await update.message.reply_text("⚠️ No active submission context. Please start over.")
        return ConversationHandler.END

    if len(lines) < 5:
        await update.message.reply_text(
            "⚠️ <b>Not enough lines.</b> Need at least 5.\n"
            "Paste the corrected job again or type /cancelsubmission.",
            parse_mode="HTML",
        )
        return WAITING_FOR_SUBMISSION_JOB_TEXT

    try:
        import re
        from datetime import datetime, timedelta, timezone

        # Line 1: Title - Company
        title_company = lines[0].split("-", 1)
        title   = title_company[0].strip()
        company = title_company[1].strip() if len(title_company) > 1 else "Unknown"

        # Line 2: URL — prefer the admin-pasted URL; fall back to original submission URL
        url_line = lines[1]
        url = url_line.replace("Job link:", "").strip()
        if not url.startswith("http"):
            url = context.user_data.get("pending_submission_url", url)

        # Line 3: Location | Job Type | Salary
        loc_type_sal = lines[2].replace("📍", "").split("|")
        location  = loc_type_sal[0].strip() if len(loc_type_sal) > 0 else "Remote"
        job_type_str = loc_type_sal[1].strip() if len(loc_type_sal) > 1 else "Fulltime"
        job_type  = "internship" if "intern" in job_type_str.lower() else "fulltime"
        duration  = job_type_str if job_type == "internship" else None
        salary    = loc_type_sal[2].strip() if len(loc_type_sal) > 2 else "Not disclosed"

        # Line 4: Batches | YOE
        batch_yoe = lines[3].replace("🎓", "").split("|")
        batch_str = batch_yoe[0].strip()
        yoe_str   = batch_yoe[1].strip() if len(batch_yoe) > 1 else "0"

        batches = []
        for p in batch_str.split("/"):
            p = p.strip()
            if p.isdigit():
                batches.append(int(p))

        min_yoe = 0
        yoe_digits = re.findall(r"\d+", yoe_str)
        if yoe_digits:
            min_yoe = int(yoe_digits[0])

        # Line 5: Skills
        skills_str = lines[4].replace("🏷", "").strip()
        skills = [s.strip() for s in skills_str.split(",")]

        # Optional Line 6: posted_at
        posted_at = None
        if len(lines) > 5 and "⏰" in lines[5]:
            time_str = lines[5].replace("⏰", "").replace("ago", "").replace("(Optional)", "").strip()
            try:
                num = int("".join(filter(str.isdigit, time_str)))
                if "d" in time_str:
                    posted_at = datetime.now(timezone.utc) - timedelta(days=num)
                elif "h" in time_str:
                    posted_at = datetime.now(timezone.utc) - timedelta(hours=num)
            except Exception:
                pass

        # Optional: Hiring Manager line
        hm_role_val = hm_name_val = hm_email_val = hm_linkedin_val = None
        for line in lines[5:]:
            if "👤" in line:
                hm_raw   = line.replace("👤", "").strip()
                hm_parts = [p.strip() for p in hm_raw.split("|")]
                if len(hm_parts) >= 1: hm_role_val     = hm_parts[0] or None
                if len(hm_parts) >= 2: hm_name_val     = hm_parts[1] or None
                if len(hm_parts) >= 3:
                    v = hm_parts[2]
                    if "@" in v: hm_email_val = v
                    elif "linkedin" in v.lower(): hm_linkedin_val = v
                if len(hm_parts) >= 4:
                    v = hm_parts[3]
                    if "linkedin" in v.lower(): hm_linkedin_val = v
                    elif "@" in v: hm_email_val = v
                break

        data = {
            "title": title, "company": company, "url": url,
            "location": location, "salary": salary,
            "job_type": job_type, "duration": duration,
            "skills": skills, "min_yoe": min_yoe,
            "eligible_batches": batches,
            "added_by": submitter_id,   # credit the original submitter
            "posted_at": posted_at,
            "hm_name": hm_name_val, "hm_role": hm_role_val,
            "hm_email": hm_email_val, "hm_linkedin": hm_linkedin_val,
        }

        job_id = await add_manual_job(data)
        await mark_submission_approved(submission_id, job_id)

        # Build and send Legitimacy Report to the submitting user
        report = _build_report_text(checks, approved=True)
        report += (
            "\n\n✅ <b>This job passed our Legitimacy Check and has been added to the board!</b>\n\n"
            f"🎯 <b>{title} @ {company}</b> is now live.\n"
            "Tap the button below to get your Apply Smart Kit ready in one click! 🚀"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Apply Smart", callback_data=f"apply_smart_{job_id}")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        try:
            await context.bot.send_message(
                chat_id=submitter_id,
                text=report,
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning(f"Could not notify submitter {submitter_id} of approval: {e}")

        await update.message.reply_text(
            f"✅ <b>Job added!</b> ID: {job_id}\n{title} @ {company}\nSubmitter notified.",
            parse_mode="HTML",
        )

        # Clean up context
        for key in ("pending_submission_id", "pending_submission_url",
                    "pending_submission_user", "pending_submission_checks"):
            context.user_data.pop(key, None)

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error parsing submitted job: {e}")
        await update.message.reply_text(
            f"⚠️ <b>Format Error:</b> {e}\n\nFix the text and paste again, or type /cancelsubmission.",
            parse_mode="HTML",
        )
        return WAITING_FOR_SUBMISSION_JOB_TEXT


async def cancel_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the submission approval conversation."""
    for key in ("pending_submission_id", "pending_submission_url",
                "pending_submission_user", "pending_submission_checks"):
        context.user_data.pop(key, None)
    await update.message.reply_text("❌ Submission approval cancelled.")
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN FLOW: Manual Duplicate Tagging
# ─────────────────────────────────────────────────────────────────────────────

async def sub_duplicate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicked Mark as Duplicate — ask for existing Job ID."""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return ConversationHandler.END

    submission_id = int(query.data.split("_")[-1])
    sub = await get_submission(submission_id)
    if not sub:
        await query.edit_message_text("❌ Submission not found.")
        return ConversationHandler.END

    context.user_data["pending_submission_id"] = submission_id
    context.user_data["pending_submission_user"] = sub["telegram_id"]

    await query.edit_message_text(
        f"🔗 <b>Mark as Duplicate</b> — Submission #{submission_id}\n\n"
        "What is the Job ID of the existing live job on the platform?\n\n"
        "<i>(Type the numeric ID below, or /cancelsubmission to abort)</i>",
        parse_mode="HTML"
    )
    return WAITING_FOR_DUPLICATE_JOB_ID

async def process_duplicate_job_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin typed the Job ID for the duplicate."""
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return ConversationHandler.END

    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ Please enter a valid numeric Job ID, or /cancelsubmission.")
        return WAITING_FOR_DUPLICATE_JOB_ID

    job_id = int(text)
    submission_id = context.user_data.get("pending_submission_id")
    submitter_id = context.user_data.get("pending_submission_user")

    if not submission_id:
        await update.message.reply_text("⚠️ No active submission context. Please start over.")
        return ConversationHandler.END

    # Verify job exists
    from db.manual_jobs import get_manual_job_by_id
    job = await get_manual_job_by_id(job_id)
    if not job:
        await update.message.reply_text("⚠️ No live job found with that ID. Try again or /cancelsubmission.")
        return WAITING_FOR_DUPLICATE_JOB_ID

    # Mark submission as rejected (duplicate)
    await mark_submission_rejected(submission_id)

    # Send the user the Apply Smart link for the duplicate
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Apply Smart", callback_data=f"apply_smart_{job_id}")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
    ])
    msg = (
        "🎯 <b>Great find!</b>\n\n"
        "This exact role was already added to our board from another platform.\n"
        "Tap below to get your Apply Kit for it! 🚀"
    )
    try:
        await context.bot.send_message(
            chat_id=submitter_id,
            text=msg,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning(f"Could not notify submitter {submitter_id} of duplicate: {e}")

    await update.message.reply_text(
        f"✅ <b>Marked as duplicate of Job #{job_id}.</b>\nUser notified with Apply Smart button.",
        parse_mode="HTML",
    )

    context.user_data.pop("pending_submission_id", None)
    context.user_data.pop("pending_submission_user", None)
    return ConversationHandler.END

async def cancel_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the admin submission flow."""
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return ConversationHandler.END
    context.user_data.pop("pending_submission_id", None)
    context.user_data.pop("pending_submission_user", None)
    await update.message.reply_text("❌ Action cancelled.")
    return ConversationHandler.END


def get_submission_conversation_handler() -> ConversationHandler:
    """ConversationHandler for the admin job-text entry and duplicate ID entry."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(sub_approve_callback, pattern=r"^sub_approve_\d+$"),
            CallbackQueryHandler(sub_duplicate_callback, pattern=r"^sub_duplicate_\d+$"),
        ],
        states={
            WAITING_FOR_SUBMISSION_JOB_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, parse_and_add_submitted_job),
            ],
            WAITING_FOR_DUPLICATE_JOB_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_duplicate_job_id),
            ]
        },
        fallbacks=[
            CommandHandler("cancelsubmission", cancel_submission),
            CallbackQueryHandler(sub_approve_callback, pattern=r"^sub_approve_\d+$"),
            CallbackQueryHandler(sub_duplicate_callback, pattern=r"^sub_duplicate_\d+$"),
        ],
        per_message=False,
    )



# ─────────────────────────────────────────────────────────────────────────────
# ADMIN FLOW: /links Dashboard
# ─────────────────────────────────────────────────────────────────────────────

async def _render_links_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
    limit = 10
    offset = (page - 1) * limit
    submissions, total = await get_pending_submissions(limit, offset)

    if not submissions and page == 1:
        text = "✅ <b>No pending submissions!</b> Queue is empty."
        kb = InlineKeyboardMarkup([])
    else:
        text = f"📋 <b>Pending Job Links</b> (Page {page})\nTotal pending: {total}\n\nSelect a submission to review:"
        rows = []
        for sub in submissions:
            domain = sub["url"].split("//")[-1].split("/")[0][:20]
            rows.append([InlineKeyboardButton(
                f"#{sub['id']} - {domain}", callback_data=f"sub_admin_view_{sub['id']}"
            )])
        
        # Pagination
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"links_page_{page-1}"))
        if offset + limit < total:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"links_page_{page+1}"))
        if nav_row:
            rows.append(nav_row)
        
        kb = InlineKeyboardMarkup(rows)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the admin links dashboard."""
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return
    await _render_links_dashboard(update, context, 1)

async def links_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pagination for links dashboard."""
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[-1])
    await _render_links_dashboard(update, context, page)

async def sub_admin_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin clicked on a specific submission in the dashboard."""
    if update.effective_user.id != settings.ADMIN_TELEGRAM_ID:
        return
    query = update.callback_query
    await query.answer()
    
    submission_id = int(query.data.split("_")[-1])
    sub = await get_submission(submission_id)
    if not sub:
        await query.edit_message_text("❌ Submission not found or already processed.")
        return
        
    if sub["status"] != "pending":
        await query.answer("This submission is no longer pending.", show_alert=True)
        return
        
    # Send the legitimacy check UI just like the initial alert
    # Init empty check state in context
    context.user_data[f"sub_checks_{submission_id}"] = {key: False for _, key in CHECKLIST_ITEMS}
    kb = _build_checklist_keyboard(submission_id, context.user_data[f"sub_checks_{submission_id}"])
    # Add a Back button to the dashboard
    new_keyboard = list(kb.inline_keyboard)
    new_keyboard.append([InlineKeyboardButton("🔙 Back to Dashboard", callback_data="links_page_1")])
    kb = InlineKeyboardMarkup(new_keyboard)

    await query.edit_message_text(
        f"🔍 <b>Legitimacy Check</b> — Submission #{submission_id}\n\n"
        f"URL: {sub['url']}\n\n"
        "Toggle each item, then submit your decision:",
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )
