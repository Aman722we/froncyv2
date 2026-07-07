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
    back_cb = "explore_loading_jobs"
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    loading_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Explore Other Jobs", callback_data=back_cb)
    ]])
    
    # Reset navigation state
    context.user_data["navigated_away_from_loading"] = False

    # Quality (70B) takes ~60-70s; Fast (8B) takes ~3-5s.
    if mode == LLMMode.QUALITY:
        stages = [
            r"🔍 *Analyzing job requirements\.\.\.*" + "\n\n" + r"_Feel free to explore other jobs, we'll send the cover letter here\!_",
            r"📄 *Scanning your resume skills\.\.\.*" + "\n\n" + r"_Feel free to explore other jobs, we'll send the cover letter here\!_",
            r"🧠 *Generating your cover letter\.\.\.*" + "\n" + r"_\(Quality AI · takes ~60 seconds\)_" + "\n\n" + r"_Feel free to explore other jobs, we'll send the cover letter here\!_",
            r"✨ *Polishing tone and structure\.\.\.*" + "\n\n" + r"_Feel free to explore other jobs, we'll send the cover letter here\!_",
            r"⚡ *Optimizing for ATS keywords\.\.\.*" + "\n\n" + r"_Feel free to explore other jobs, we'll send the cover letter here\!_",
            r"⏳ *Almost done\!* The AI is finishing up\.\.\." + "\n\n" + r"_Feel free to explore other jobs, we'll send the cover letter here\!_",
        ]
        stage_interval = 10  # seconds between each stage
    else:
        stages = [
            r"⚡ *Generating your cover letter\.\.\.*" + "\n\n" + r"_Feel free to explore other jobs, we'll send the cover letter here\!_",
            r"✨ *Polishing up\.\.\.*" + "\n\n" + r"_Feel free to explore other jobs, we'll send the cover letter here\!_",
        ]
        stage_interval = 6

    # Show first stage immediately
    await query.edit_message_text(stages[0], parse_mode="MarkdownV2", reply_markup=loading_kb)

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
            if not context.user_data.get("navigated_away_from_loading"):
                try:
                    await query.edit_message_text(stage_msg, parse_mode="MarkdownV2", reply_markup=loading_kb)
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
    final_text = messages.cover_letter_result(job.get("title", ""), job.get("company", ""), letter, footer)
    final_kb = keyboards.cover_letter_result_keyboard(job_id, is_manual=is_manual)
    
    if context.user_data.get("navigated_away_from_loading"):
        # Edit the loading message to say it's done
        try:
            await query.edit_message_text(f"✅ Your Cover Letter for {job.get('company', 'Company')} is ready! Check the new message below.")
        except Exception:
            pass
        # Send a new message so the user gets notified
        await context.bot.send_message(
            chat_id=user_id,
            text=final_text,
            reply_markup=final_kb,
            parse_mode="MarkdownV2"
        )
    else:
        # Just replace the loading message
        await query.edit_message_text(
            final_text,
            reply_markup=final_kb,
            parse_mode="MarkdownV2"
        )

async def copy_cover_letter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Since Telegram bots can't easily copy to the user's clipboard,
    we just reply with the raw text so they can easily copy it on mobile."""
    query = update.callback_query
    await query.answer("Sending raw text for copying...")

    is_manual = query.data.startswith("manual_cl_copy_")
    job_id = int(query.data.split("_")[-1])
    back_prefix = "manual_view" if is_manual else "job_view"

    user_id = update.effective_user.id

    # Extract the letter from the message text
    raw_text = query.message.text
    if raw_text:
        lines = raw_text.split('\n')
        start_idx = 0
        end_idx = len(lines)
        
        # Find the start (after "Your Cover Letter — ...")
        for i, line in enumerate(lines):
            if "Your Cover Letter" in line:
                start_idx = i + 1
                break
                
        # Find the end (before "Tap the box ...")
        for i in range(start_idx, len(lines)):
            curr_line = lines[i]
            if "Tap the box" in curr_line or (curr_line.strip().startswith("(") and "remaining" in curr_line.lower()):
                end_idx = i
                break
                
        letter_body = "\n".join(lines[start_idx:end_idx]).strip()
        
        if letter_body:
            # Log copy intent — best proxy for "did they actually use this letter?"
            await log_ai_usage(user_id, "cover_letter_copied")
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Job", callback_data=f"{back_prefix}_{job_id}")]
            ])
            await query.message.reply_text(letter_body, reply_markup=kb)
            return

    await query.message.reply_text("Error extracting text.")

