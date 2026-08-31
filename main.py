"""
Main Application Entry Point.
FastAPI server that manages the Telegram webhook and Razorpay callbacks.
Also handles bot initialization and the background scheduler.

Multi-Tenant Architecture:
  - One FastAPI server serves all Guru bots.
  - Each bot has its own PTB Application instance in `bot_registry`.
  - Webhooks are routed via /webhook/{token} to the correct Application.
  - Backward-compatible /telegram-webhook routes to the primary bot.
"""
import sys
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from config import settings
from db.connection import init_db, close_db
from bot import build_bot
from bot_registry import boot_all_bots, shutdown_all_bots, get_primary_app, get_app_for_token
from services.scheduler import start_scheduler, stop_scheduler, set_bot_app
from utils.error_alert import send_error_alert


# Initialize logs
logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>")


async def _set_webhook(app, token: str, bot_id: int) -> None:
    """Set the Telegram webhook for a single bot Application."""
    import os
    webhook = settings.WEBHOOK_URL or os.getenv("RAILWAY_PUBLIC_DOMAIN") or ""
    if not webhook:
        raise ValueError("CRITICAL: WEBHOOK_URL is missing. Please set it in Railway variables!")
    webhook = webhook if webhook.startswith("http") else f"https://{webhook}"
    webhook = webhook.rstrip('/')
    webhook_url = f"{webhook}/webhook/{token}"
    logger.info(f"Setting webhook for bot_id={bot_id}: {webhook_url[:60]}...")
    await app.bot.set_webhook(url=webhook_url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI."""
    logger.info("🚀 Starting FroncyBot (Multi-Tenant)...")

    # 1. Init Database — this runs migrations including bots table creation
    await init_db()

    # 2. Boot all Guru bots from the database
    set_webhook_fn = _set_webhook if settings.ENVIRONMENT == "production" else None
    
    if settings.ENVIRONMENT != "production":
        # Dev: boot just the primary bot in polling mode
        primary_app = build_bot(settings.TELEGRAM_BOT_TOKEN)
        await primary_app.initialize()
        logger.info("Dev mode: deleting any stale webhook...")
        await primary_app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Polling mode enabled (development).")
        await primary_app.updater.start_polling(drop_pending_updates=True)
        await primary_app.start()
        from bot_registry import _registry
        _registry[settings.TELEGRAM_BOT_TOKEN] = (primary_app, 1)
    else:
        await boot_all_bots(
            primary_token=settings.TELEGRAM_BOT_TOKEN,
            build_fn=build_bot,
            set_webhook_fn=set_webhook_fn,
        )

    # 3. Start Background Scheduler (uses primary bot for alerts)
    primary_app = get_primary_app()
    set_bot_app(primary_app)
    start_scheduler()

    yield

    # Shutdown sequence
    logger.info("🛑 Shutting down FroncyBot...")
    stop_scheduler()

    if settings.ENVIRONMENT != "production":
        primary_app = get_primary_app()
        if primary_app and primary_app.updater:
            await primary_app.updater.stop()

    await shutdown_all_bots()
    await close_db()


# FastAPI App
app = FastAPI(title="FroncyBot API", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all FastAPI exception handler — alerts admin on any unhandled API error."""
    logger.error(f"Unhandled FastAPI exception on {request.url.path}: {exc}", exc_info=True)
    try:
        primary = get_primary_app()
        if primary:
            await send_error_alert(
                bot=primary.bot,
                source=f"FastAPI — {request.method} {request.url.path}",
                error=exc,
                extra=f"client={request.client.host if request.client else 'unknown'}",
            )
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"status": "error", "detail": "Internal server error"})


@app.get("/health")
async def health_check():
    """Railway healthcheck endpoint."""
    return {"status": "ok", "bot": "FroncyBot"}


from fastapi.responses import RedirectResponse

@app.get("/r/{job_id}")
async def apply_redirector(job_id: int, uid: int | None = None):
    """
    Job application link tracker + redirector.
    When a user clicks 'Open Link', they hit this endpoint first.
    We log the click then instantly redirect them to the real job URL.
    """
    from db.manual_jobs import get_manual_job_by_id
    from db.jobs import get_job_by_id
    from db.tracker import log_link_click

    # Log the click (completely non-blocking for the user)
    if uid:
        await log_link_click(uid, job_id)

    # Fetch the real URL from the database
    job = await get_manual_job_by_id(job_id)
    if not job:
        job = await get_job_by_id(job_id)
        
    if job and job.get("url"):
        return RedirectResponse(url=job["url"], status_code=302)

    # Fallback if job not found — send to bot
    return RedirectResponse(url="https://t.me/FroncyJobsBot", status_code=302)




from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint — serves Razorpay compliance landing page."""
    from pathlib import Path
    html_path = Path(__file__).parent / "templates" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/bot")
async def redirect_to_bot():
    """
    Marketing link redirector. 
    Users go to getfroncy.com/bot and it redirects them to the actual Telegram bot.
    If the bot is ever deleted, you just update BOT_USERNAME in Railway variables.
    """
    import os
    bot_username = os.getenv("BOT_USERNAME", "FroncyJobsBot")
    return RedirectResponse(url=f"https://t.me/{bot_username}", status_code=302)


async def _process_telegram_update(request: Request, app_instance, log_prefix: str = ""):
    """Shared logic: parse the incoming update and dispatch to a PTB Application."""
    from telegram import Update
    import asyncio
    
    json_data = await request.json()
    update = Update.de_json(json_data, app_instance.bot)
    
    update_type = "unknown"
    if update.message:
        update_type = f"message: {update.message.text or '(non-text)'}"
    elif update.callback_query:
        update_type = f"callback: {update.callback_query.data}"
    logger.info(f"Webhook received{log_prefix}: {update_type} from user {update.effective_user.id if update.effective_user else '?'}")
    
    try:
        asyncio.create_task(app_instance.process_update(update))
    except Exception as e:
        logger.error(f"Error queueing update: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
    
    return {"status": "ok"}


@app.post("/webhook/{token}")
async def multi_tenant_webhook(token: str, request: Request):
    """
    Multi-Tenant Telegram Webhook.
    Telegram sends updates to /webhook/{bot_token}.
    We look up the correct PTB Application from the registry and dispatch to it.
    """
    if settings.ENVIRONMENT != "production":
        return {"status": "ignored", "reason": "Not in production mode"}
    
    app_instance = get_app_for_token(token)
    if not app_instance:
        logger.warning(f"Webhook received for unknown token: {token[:20]}...")
        raise HTTPException(status_code=404, detail="Bot not found")
    
    return await _process_telegram_update(request, app_instance, log_prefix=f" [token={token[:10]}...]")


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """
    Legacy single-bot webhook endpoint. Kept for backward compatibility.
    Routes to the primary FroncyBot application.
    """
    if settings.ENVIRONMENT != "production":
        return {"status": "ignored", "reason": "Not in production mode"}
    
    primary = get_primary_app()
    if not primary:
        raise HTTPException(status_code=503, detail="Primary bot not ready")
    
    return await _process_telegram_update(request, primary)


@app.post("/razorpay-webhook")
async def razorpay_webhook(request: Request):
    """Handle subscription events from Razorpay."""
    from services.payment_service import verify_webhook_signature, extract_payment_info
    from db.users import update_user_subscription
    from datetime import datetime, timezone
    from dateutil.relativedelta import relativedelta

    signature = request.headers.get("x-razorpay-signature")
    payload = await request.body()

    if not signature or not verify_webhook_signature(payload, signature):
        logger.warning("Invalid Razorpay webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = await request.json()
    event = data.get("event")
    
    # We care about subscription events
    if event not in ("subscription.charged", "subscription.cancelled", "subscription.halted", "payment.captured", "payment_link.paid"):
        return {"status": "ignored", "event": event}

    payment_info = extract_payment_info(data)
    if not payment_info:
        logger.error(f"Could not extract telegram_id from event: {data}")
        return {"status": "error", "message": "Missing reference data"}

    telegram_id = payment_info["telegram_id"]
    plan = payment_info["plan"]
    sub_id = payment_info.get("sub_id")
    customer_id = payment_info.get("customer_id")

    if event in ("subscription.charged", "payment.captured", "payment_link.paid"):
        # Calculate expiration (1 month from now)
        expires_at = datetime.now(timezone.utc) + relativedelta(months=1)
        await update_user_subscription(telegram_id, plan, expires_at, customer_id, sub_id, 'active')
        logger.info(f"Subscription charged/activated for user {telegram_id}")

        # Notify user via bot
        try:
            from utils.helpers import escape_md
            amount = data.get("payload", {}).get("payment", {}).get("entity", {}).get("amount", 0) / 100
            if amount == 0:
                amount = data.get("payload", {}).get("subscription", {}).get("entity", {}).get("total_count", 0) # Just fallback if we don't have it
            
            primary = get_primary_app()
            if primary:
                await primary.bot.send_message(
                chat_id=telegram_id,
                text=(
                    f"🎉 *You're now on Pro\\!*\n\n"
                    f"Valid until: {escape_md(expires_at.strftime('%B %d, %Y'))}\n\n"
                    "✅ Unlimited jobs\n"
                    "✅ 10 cover letters/day\n"
                    "✅ Full match scores\n"
                    "✅ 5 ATS checks/day\n\n"
                    "Type /menu to explore your new features\\."
                ),
                parse_mode="MarkdownV2"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {telegram_id} of upgrade: {e}")

    elif event in ("subscription.cancelled", "subscription.halted"):
        # The user's subscription won't auto-renew. We keep the current plan_expires_at.
        # But we update the status so the UI knows it's cancelled.
        await update_user_subscription(telegram_id, plan, None, customer_id, sub_id, 'cancelled')
        logger.info(f"Subscription {event} for user {telegram_id}")

    return {"status": "ok"}


@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "froncybot"}

if __name__ == "__main__":
    import uvicorn
    # Make sure python-dateutil is added to requirements for relativedelta
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
