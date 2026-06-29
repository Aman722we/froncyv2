"""
Main Application Entry Point.
FastAPI server that manages the Telegram webhook and Razorpay callbacks.
Also handles bot initialization and the background scheduler.
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
from services.scheduler import start_scheduler, stop_scheduler, set_bot_app
from utils.error_alert import send_error_alert


# Initialize logs
logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>")

# Global bot application instance
bot_app = build_bot()
set_bot_app(bot_app)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI."""
    logger.info("🚀 Starting FroncyBot...")

    # 1. Init Database
    await init_db()

    # 2. Start Bot
    await bot_app.initialize()
    if settings.ENVIRONMENT == "production":
        import os
        webhook = settings.WEBHOOK_URL or os.getenv("RAILWAY_PUBLIC_DOMAIN") or ""
        if not webhook:
            raise ValueError("CRITICAL: WEBHOOK_URL is missing. Please set it in Railway variables!")
            
        webhook = webhook if webhook.startswith("http") else f"https://{webhook}"
        webhook = webhook.rstrip('/')
        
        logger.info(f"Setting webhook URL: {webhook}")
        await bot_app.bot.set_webhook(url=f"{webhook}/telegram-webhook")
    else:
        logger.info("Polling mode enabled (development).")
        # In dev, we start polling natively
        await bot_app.updater.start_polling(drop_pending_updates=True)
    await bot_app.start()

    # 3. Start Background Scheduler
    start_scheduler()

    yield

    # Shutdown sequence
    logger.info("🛑 Shutting down FroncyBot...")
    stop_scheduler()
    
    
    # We consciously avoid deleting the webhook on production shutdown 
    # to prevent breaking Railway's zero-downtime deploys when the old container dies.
    if settings.ENVIRONMENT != "production":
        await bot_app.updater.stop()
        
    await bot_app.stop()
    await bot_app.shutdown()
    await close_db()


# FastAPI App
app = FastAPI(title="FroncyBot API", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all FastAPI exception handler — alerts admin on any unhandled API error."""
    logger.error(f"Unhandled FastAPI exception on {request.url.path}: {exc}", exc_info=True)
    try:
        await send_error_alert(
            bot=bot_app.bot,
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


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """Receive updates from Telegram in production."""
    if settings.ENVIRONMENT != "production":
        return {"status": "ignored", "reason": "Not in production mode"}
    
    from telegram import Update
    json_data = await request.json()
    update = Update.de_json(json_data, bot_app.bot)
    
    # Log what we received
    update_type = "unknown"
    if update.message:
        update_type = f"message: {update.message.text or '(non-text)'}"
    elif update.callback_query:
        update_type = f"callback: {update.callback_query.data}"
    logger.info(f"Webhook received: {update_type} from user {update.effective_user.id if update.effective_user else '?'}")
    
    # Process update with error catching
    try:
        await bot_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
        # bot_app error_handler will already fire — no double alert needed
        return {"status": "error", "message": str(e)}
    
    return {"status": "ok"}


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
            
            await bot_app.bot.send_message(
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
