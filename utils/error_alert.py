"""
Global error alerting — sends loud Telegram alerts to admin when anything crashes.
Used by the Telegram error handler, FastAPI middleware, and scheduler jobs.
"""
import traceback
from loguru import logger
from config import settings


def _format_alert(source: str, error: Exception, extra: str = "") -> str:
    """Format a crash alert message with full traceback, truncated to Telegram's 4096 char limit."""
    tb = traceback.format_exc()
    # Truncate traceback if too long
    if len(tb) > 2000:
        tb = "..." + tb[-2000:]

    lines = [
        "❌❌❌ <b>CRASH ALERT</b> ❌❌❌",
        "",
        f"📍 <b>Source:</b> {source}",
        f"💥 <b>Error:</b> {type(error).__name__}: {str(error)[:300]}",
    ]
    if extra:
        lines.append(f"ℹ️ <b>Context:</b> {extra[:300]}")
    lines += [
        "",
        "🔍 <b>Traceback:</b>",
        f"<pre>{tb}</pre>",
        "",
        "⚠️ Fix this ASAP before users are affected.",
    ]
    return "\n".join(lines)


async def send_error_alert(bot, source: str, error: Exception, extra: str = "") -> None:
    """Send a crash alert to the admin. Silently fails if admin ID not configured."""
    if not settings.ADMIN_TELEGRAM_ID:
        return
    try:
        msg = _format_alert(source, error, extra)
        # Telegram limit is 4096 chars
        if len(msg) > 4096:
            msg = msg[:4050] + "\n\n... (truncated)"
        await bot.send_message(
            chat_id=settings.ADMIN_TELEGRAM_ID,
            text=msg,
            parse_mode="HTML",
        )
    except Exception as e:
        # Never let alerting itself crash the app
        logger.error(f"Failed to send error alert to admin: {e}")
