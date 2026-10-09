"""
HR Contact & Resume Review request handler.
Handles: req_hr_{job_id} and req_resume_review callbacks.
"""
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from loguru import logger

from config import settings
from db.users import get_user
from db.manual_requests import create_request


async def request_hr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle 👤 Request HR Details button.
    - Pro users with credits → deduct 1, add to queue, notify admin, confirm to user.
    - Pro users with 0 credits → inform monthly limit reached.
    - Free users → show ₹49 purchase option.
    """
    query = update.callback_query
    await query.answer()

    bot_id = context.bot_data.get("bot_id", 1)
    user_id = update.effective_user.id
    user = await get_user(user_id, bot_id=bot_id)

    if not user:
        await query.answer("Please /start the bot first.", show_alert=True)
        return

    # Parse job_id from callback_data: req_hr_{job_id}
    job_id = None
    try:
        job_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        pass

    plan = user.get("plan", "free")
    is_pro = plan in ("pro", "proplus", "premium")
    hr_left = user.get("hr_requests_left", 0) or 0

    if is_pro and hr_left > 0:
        # Deduct credit and queue request
        from db.connection import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET hr_requests_left = hr_requests_left - 1 WHERE telegram_id = $1",
                user_id,
            )
        req_id = await create_request(user_id, "HR_CONTACT", job_id=job_id)

        # Notify admin
        name = update.effective_user.first_name or "User"
        username = update.effective_user.username or "no_username"
        try:
            from db.manual_jobs import get_manual_job_by_id
            job = await get_manual_job_by_id(job_id) if job_id else None
            job_info = f"{job['title']} @ {job['company']}" if job else f"Job ID #{job_id}"
        except Exception:
            job_info = f"Job ID #{job_id}"

        try:
            await context.bot.send_message(
                chat_id=settings.ADMIN_TELEGRAM_ID,
                text=(
                    f"📬 <b>New HR Contact Request</b> [#{req_id}]\n\n"
                    f"👤 {name} (@{username} | ID: <code>{user_id}</code>)\n"
                    f"💼 Job: {job_info}\n"
                    f"🔗 Reply here when done: /completerequest {req_id}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Could not notify admin of HR request: {e}")

        new_left = hr_left - 1
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>HR Contact Request received!</b>\n\n"
                f"We'll research and send you the best hiring contact for this role shortly.\n\n"
                f"📊 Credits remaining this month: <b>{new_left}/5</b>"
            ),
            parse_mode="HTML",
        )

    elif is_pro and hr_left <= 0:
        # Pro but exhausted monthly credits
        await query.answer(
            "You've used all 5 HR contact requests this month. Resets on your next billing date.",
            show_alert=True,
        )

    else:
        # Free user → show ₹49 purchase option
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Get HR Contact — ₹49", callback_data=f"buy_hr_{job_id}")],
            [InlineKeyboardButton("💎 Go Pro (₹199/mo) — includes 5/month", callback_data="menu_upgrade")],
            [InlineKeyboardButton("🔙 Back to Job", callback_data=f"manual_view_{job_id}" if job_id else "back_menu")],
        ])
        await query.edit_message_text(
            text=(
                "👤 <b>Request HR Contact</b>\n\n"
                "Get the relevant hiring manager or recruiter contact for this job.\n\n"
                "💰 <b>One-time: ₹49</b> for this job\n"
                "💎 Or <b>Go Pro at ₹199/mo</b> to get 5 requests every month + instant alerts + resume review.\n\n"
                "<i>Contacts are sourced from public professional profiles only.</i>"
            ),
            parse_mode="HTML",
            reply_markup=kb,
        )


async def buy_hr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle 💳 Get HR Contact — ₹49 button.
    Creates a one-time Razorpay payment link for ₹49.
    """
    query = update.callback_query
    await query.answer()

    bot_id = context.bot_data.get("bot_id", 1)
    user_id = update.effective_user.id

    job_id = None
    try:
        job_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        pass

    try:
        import razorpay
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        order = client.order.create({
            "amount": 4900,  # ₹49 in paise
            "currency": "INR",
            "notes": {
                "telegram_id": str(user_id),
                "purchase_type": "hr_contact",
                "job_id": str(job_id or ""),
                "bot_id": str(bot_id),
            }
        })
        pay_url = f"https://rzp.io/l/froncy-hr"  # fallback — ideally use order short_url
        # Try to get a proper payment page link
        # Razorpay orders don't have short URLs; we send users to the UPI checkout page via payment link
        payment_link = client.payment_link.create({
            "amount": 4900,
            "currency": "INR",
            "description": "Froncy — HR Contact Request",
            "notes": {
                "telegram_id": str(user_id),
                "purchase_type": "hr_contact",
                "job_id": str(job_id or ""),
                "bot_id": str(bot_id),
            },
            "callback_url": f"https://t.me/{context.bot.username}",
            "callback_method": "get",
        })
        pay_url = payment_link.get("short_url", pay_url)
    except Exception as e:
        logger.error(f"Failed to create ₹49 HR payment link: {e}")
        await query.answer("Payment system error. Please try again shortly.", show_alert=True)
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay ₹49 — Tap Here", url=pay_url)],
        [InlineKeyboardButton("🔙 Back to Job", callback_data=f"manual_view_{job_id}" if job_id else "back_menu")],
    ])
    await query.edit_message_text(
        text=(
            "✅ <b>Your payment link is ready!</b>\n\n"
            "Tap below to pay ₹49 securely via Razorpay.\n\n"
            "After payment, your HR contact request will be queued automatically."
        ),
        parse_mode="HTML",
        reply_markup=kb,
    )


async def request_resume_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle 📄 Request Resume Review button.
    - Pro users with credit → deduct 1, queue request, notify admin.
    - Pro users with 0 credit → inform about one-time ₹99 option.
    - Free users → show ₹99 purchase option.
    """
    query = update.callback_query
    await query.answer()

    bot_id = context.bot_data.get("bot_id", 1)
    user_id = update.effective_user.id
    user = await get_user(user_id, bot_id=bot_id)

    if not user:
        await query.answer("Please /start the bot first.", show_alert=True)
        return

    plan = user.get("plan", "free")
    is_pro = plan in ("pro", "proplus", "premium")
    reviews_left = user.get("resume_reviews_left", 0) or 0

    if is_pro and reviews_left > 0:
        from db.connection import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET resume_reviews_left = resume_reviews_left - 1 WHERE telegram_id = $1",
                user_id,
            )
        req_id = await create_request(user_id, "RESUME_REVIEW")

        name = update.effective_user.first_name or "User"
        username = update.effective_user.username or "no_username"
        try:
            await context.bot.send_message(
                chat_id=settings.ADMIN_TELEGRAM_ID,
                text=(
                    f"📄 <b>New Resume Review Request</b> [#{req_id}]\n\n"
                    f"👤 {name} (@{username} | ID: <code>{user_id}</code>)\n\n"
                    f"Use /getresume {user_id} to fetch their resume.\n"
                    f"Reply done with: /completerequest {req_id}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Could not notify admin of resume review request: {e}")

        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "✅ <b>Resume Review Request received!</b>\n\n"
                "A human reviewer will go through your resume and send you detailed feedback shortly.\n\n"
                "💡 Make sure your resume is uploaded under <b>My Resume</b> so we can review it."
            ),
            parse_mode="HTML",
        )

    else:
        # No credit — show ₹99 purchase option
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Get Resume Review — ₹99", callback_data="buy_resume_review")],
            [InlineKeyboardButton("💎 Go Pro (₹199/mo) — includes 1 review", callback_data="menu_upgrade")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        reason = "You've used your included review." if is_pro else ""
        await query.edit_message_text(
            text=(
                "📄 <b>Human Resume Review</b>\n\n"
                f"{reason + chr(10) if reason else ''}"
                "A real person will review your resume and tell you exactly why you might not be getting callbacks — and what to fix.\n\n"
                "💰 <b>One-time: ₹99</b>\n"
                "💎 Or <b>Go Pro at ₹199/mo</b> — includes 1 review + instant alerts + 5 HR contacts/month.\n\n"
                "<i>Please make sure your resume is uploaded before requesting.</i>"
            ),
            parse_mode="HTML",
            reply_markup=kb,
        )


async def buy_resume_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Creates a ₹99 Razorpay payment link for a one-time resume review."""
    query = update.callback_query
    await query.answer()

    bot_id = context.bot_data.get("bot_id", 1)
    user_id = update.effective_user.id

    try:
        import razorpay
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        payment_link = client.payment_link.create({
            "amount": 9900,  # ₹99 in paise
            "currency": "INR",
            "description": "Froncy — Human Resume Review",
            "notes": {
                "telegram_id": str(user_id),
                "purchase_type": "resume_review",
                "bot_id": str(bot_id),
            },
            "callback_url": f"https://t.me/{context.bot.username}",
            "callback_method": "get",
        })
        pay_url = payment_link.get("short_url", "https://getfroncy.com")
    except Exception as e:
        logger.error(f"Failed to create ₹99 resume review payment link: {e}")
        await query.answer("Payment system error. Please try again shortly.", show_alert=True)
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay ₹99 — Tap Here", url=pay_url)],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await query.edit_message_text(
        text=(
            "✅ <b>Your payment link is ready!</b>\n\n"
            "Tap below to pay ₹99 securely via Razorpay.\n\n"
            "After payment, your resume review will be queued automatically within 1 minute."
        ),
        parse_mode="HTML",
        reply_markup=kb,
    )
