"""
bot_registry.py -- Multi-Tenant Bot Registry (Runtime Layer)

Manages a dict of {bot_token: PTB Application} at runtime.
On startup, main.py calls `boot_all_bots()` to initialize every
active Guru bot from the database. New bots can be hot-added via
`add_bot()` without a server restart.
"""
import asyncio
from typing import Dict
from loguru import logger
from telegram import Bot
from telegram.ext import Application
from telegram.request import HTTPXRequest


# The global in-memory registry: token -> (PTB Application, bot_id)
_registry: Dict[str, tuple] = {}

# The primary default bot token (from settings) - used as fallback
_primary_token: str = ""


def get_registry() -> Dict[str, tuple]:
    return _registry


def get_primary_app() -> Application | None:
    """Return the primary FroncyBot Application (for webhooks, admin alerts, etc.)."""
    return _registry.get(_primary_token, (None,))[0]



def get_app_for_bot_id(bot_id: int) -> Application | None:
    """Return the PTB Application for a given internal bot_id."""
    for token, (app, bid) in _registry.items():
        if bid == bot_id:
            return app
    return None

def get_app_for_token(token: str) -> Application | None:
    """Return the PTB Application for a given bot token."""
    entry = _registry.get(token)
    return entry[0] if entry else None


def get_bot_id_for_token(token: str) -> int | None:
    """Return the internal database bot_id for a given token."""
    entry = _registry.get(token)
    return entry[1] if entry else None


def _make_http_request() -> HTTPXRequest:
    """Shared HTTP pool config for all bot instances."""
    return HTTPXRequest(
        connection_pool_size=50,
        pool_timeout=5.0,
        connect_timeout=5.0,
        read_timeout=10.0,
    )


async def add_bot(token: str, bot_id: int, build_fn) -> Application:
    """
    Instantiate and start a PTB Application for the given token.
    build_fn is the `build_bot(token)` callable from bot.py.
    """
    if token in _registry:
        logger.info(f"Bot {token[:20]}... already in registry, skipping.")
        return _registry[token][0]

    app = build_fn(token)
    await app.initialize()
    await app.start()

    _registry[token] = (app, bot_id)
    logger.info(f"Registered bot token={token[:20]}... bot_id={bot_id}")
    return app


async def boot_all_bots(primary_token: str, build_fn, set_webhook_fn=None) -> None:
    """
    Called once at startup. Loads all active bots from the DB and
    registers them in the runtime registry.
    
    primary_token: the main TELEGRAM_BOT_TOKEN from settings
    build_fn: the build_bot(token) function from bot.py
    set_webhook_fn: async callable(app, token) that sets the webhook for each bot
    """
    global _primary_token
    _primary_token = primary_token

    from db.bots import get_all_active_bots

    try:
        all_bots = await get_all_active_bots()
    except Exception as e:
        logger.warning(f"Could not load bots from DB (probably first boot): {e}")
        all_bots = []

    # Always ensure the primary bot is included
    primary_in_db = any(b["bot_token"] == primary_token for b in all_bots)
    if not primary_in_db:
        all_bots.insert(0, {
            "bot_token": primary_token,
            "bot_username": "FroncyJobsBot",
            "guru_name": "Froncy (Primary)",
            "id": 1,
        })

    for bot_cfg in all_bots:
        token = bot_cfg["bot_token"]
        bot_id = bot_cfg.get("id", 1)
        try:
            app = await add_bot(token, bot_id, build_fn)
            if set_webhook_fn:
                await set_webhook_fn(app, token, bot_id)
        except Exception as e:
            logger.error(f"Failed to boot bot {token[:20]}...: {e}")


async def shutdown_all_bots() -> None:
    """Gracefully stop all PTB Application instances."""
    for token, (app, bot_id) in list(_registry.items()):
        try:
            await app.stop()
            await app.shutdown()
            logger.info(f"Shut down bot_id={bot_id}")
        except Exception as e:
            logger.warning(f"Error shutting down bot_id={bot_id}: {e}")
    _registry.clear()
