"""
Cover letter generation handlers.
"""
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger

from db.users import get_user, increment_cover_letters_today
from db.tracker import log_ai_usage
from db.jobs import get_job_by_id
from db.manual_jobs import get_manual_job_by_id
from db.connection import get_pool
from services.llm_service import generate_cover_letter, LLMMode, get_mode_display, get_fallback_cover_letter
from services.reset_service import check_and_reset_daily
from utils.limits import get_limit
from utils import keyboards, messages
from utils.helpers import escape_md, get_effective_plan


async def coverletter_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Cover Letter' command/button — guide user to pick a job first."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    query = update.callback_query
    
    msg_text = (
        "✍️ *Cover Letter Generator*\n\n"
        "To generate a cover letter, first select a job from the jobs list\\.\n\n"
        "Each job has ⚡ *Fast* and ✨ *Quality* cover letter buttons\\."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Browse Jobs", callback_data="menu_jobs")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])

    if query:
        await query.answer()
        await query.edit_message_text(
            msg_text,
            reply_markup=kb,
            parse_mode="MarkdownV2",
        )
    else:
        await update.message.reply_text(
            msg_text,
            reply_markup=kb,
            parse_mode="MarkdownV2",
        )


async def generate_cover_letter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle generation from a job detail view."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    await check_and_reset_daily(user_id, get_pool())
    user = await get_user(user_id)

    if not user.get("resume_text"):
        await query.message.reply_text(messages.no_resume_error(), parse_mode="MarkdownV2")
        return

    # Check limits
    plan = get_effective_plan(user)
    limit = get_limit(plan, "cover_letters_per_day")
    cover_letters_today = user.get("cover_letters_today", 0)

    if cover_letters_today >= limit:
        if plan == "free":
            msg = ("✍️ You've used your 1 free cover letter today.\n"
                   "Resets at midnight!\n\n"
                   "Upgrade to Pro for 10 cover letters/day\n"
                   "+ unlimited jobs + match scores.")
            kb = keyboards.InlineKeyboardMarkup([
                [keyboards.InlineKeyboardButton("💎 Upgrade — ₹99/mo", callback_data="upgrade_pro")],
                [keyboards.InlineKeyboardButton("⏰ See you tomorrow", callback_data="back_menu")]
            ])
            await query.edit_message_text(messages.escape_md(msg), reply_markup=kb, parse_mode="MarkdownV2")
        else:
            await query.message.reply_text("You've generated 10 cover letters today — \nthat's impressive hustle! Resets at midnight. 🔥")
        return

    data_parts = query.data.split("_")
    job_id = int(data_parts[-1])
    is_manual = query.data.startswith("manual_")
    tone = "formal"
    
    if "tone" in data_parts:
        tone = data_parts[-2]
        
    mode = LLMMode.QUALITY if plan in ("pro", "proplus", "premium", "trial") else LLMMode.FAST

    if is_manual:
        job = await get_manual_job_by_id(job_id)
    else:
        job = await get_job_by_id(job_id)
        
    if not job:
        await query.message.reply_text(messages.error_job_not_found(), parse_mode="MarkdownV2")
        return

    jd = f"{job.get('title')} at {job.get('company')} - {job.get('location')}. Skills: {', '.join(job.get('skills', []))}"

    # ── Animated progress loader ──────────────────────────────────────────
    # Quality (70B) takes ~60-70s; Fast (8B) takes ~3-5s.
    # We fire the generation task immediately and update the message every
    # STAGE_INTERVAL seconds so the user always sees forward progress.
    if mode == LLMMode.QUALITY:
        stages = [
            "🔍 *Analyzing job requirements\.\.\.*",
            "📄 *Scanning your resume skills\.\.\.*",
            "🧠 *Generating your cover letter\.\.\.*\n_\(Quality AI · takes ~60 seconds\)_",
            "✨ *Polishing tone and structure\.\.\.*",
            "⚡ *Optimizing for ATS keywords\.\.\.*",
            "⏳ *Almost done\!* The AI is finishing up\.\.\.",
        ]
        stage_interval = 10  # seconds between each stage
    else:
        stages = [
            "⚡ *Generating your cover letter\.\.\.*",
            "✨ *Polishing up\.\.\.*",
        ]
        stage_interval = 6

    # Show first stage immediately
    await query.edit_message_text(stages[0], parse_mode="MarkdownV2")

    # Fire generation in the background
    gen_task = asyncio.create_task(
        generate_cover_letter(user["resume_text"], jd, mode=mode, tone=tone)
    )

    letter = None
    for stage_msg in stages[1:]:
        try:
            letter = await asyncio.wait_for(asyncio.shield(gen_task), timeout=stage_interval)
            break  # Generation finished early — stop the loop
        except asyncio.TimeoutError:
            if gen_task.done():
                break  # Done between intervals (exception case)
            try:
                await query.edit_message_text(stage_msg, parse_mode="MarkdownV2")
            except Exception:
                pass  # If Telegram rate-limits the edit, just skip it

    # If we exhausted all stages but task still running, wait unconditionally
    if letter is None:
        try:
            letter = await gen_task
        except Exception as gen_err:
            logger.error(f"CL generation error: {gen_err}")
            letter = None
    elif gen_task.done() and letter is None:
        try:
            letter = gen_task.result()
        except Exception as gen_err:
            logger.error(f"CL generation error: {gen_err}")
            letter = None
    # ─────────────────────────────────────────────────────────────────────

    if not letter:
        letter = get_fallback_cover_letter(job.get('title', 'Developer'), job.get('company', 'the company'))

    await increment_cover_letters_today(user_id)
    await log_ai_usage(user_id, "cover_letter")

    remaining = limit - (cover_letters_today + 1)
    if plan == "free":
        footer = f"_\\({remaining} cover letters left today\\)_"
    else:
        footer = f"_\\({remaining} of 10 remaining today\\)_"

    # Send the final result
    await query.edit_message_text(
        messages.cover_letter_result(job.get("title", ""), job.get("company", ""), letter, footer),
        reply_markup=keyboards.cover_letter_result_keyboard(job_id, is_manual=is_manual),
        parse_mode="MarkdownV2"
    )

async def copy_cover_letter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Since Telegram bots can't easily copy to the user's clipboard,
    we just reply with the raw text so they can easily copy it on mobile."""
    query = update.callback_query
    await query.answer("Sending raw text for copying...")

    user_id = update.effective_user.id

    # Extract the letter from the message text
    msg_parts = query.message.text.split("─────────────────────────")
    if len(msg_parts) > 1:
        letter_body = msg_parts[1].strip()
        # Clean up any trailing usage limits
        if "_(" in letter_body:
            letter_body = letter_body.split("_(")[0].strip()
        elif "(" in letter_body and "remaining" in letter_body.lower():
            # In case italics formatting gets lost or weirdly parsed
            parts = letter_body.split("(")
            if len(parts) > 1:
                # Remove the last parenthetical if it looks like a limit
                letter_body = "(".join(parts[:-1]).strip()

        # Log copy intent — best proxy for "did they actually use this letter?"
        await log_ai_usage(user_id, "cover_letter_copied")
        await query.message.reply_text(letter_body)
    else:
        await query.message.reply_text("Error extracting text.")

