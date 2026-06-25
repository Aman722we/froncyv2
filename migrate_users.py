import asyncio
from telegram import Bot
from loguru import logger
import asyncpg
from config import settings

# Migration message text
MESSAGE = """🚨 <b>Important Update!</b> 🚨

Froncy is rebranding to <b>Froncy</b>! Due to trademark reasons, this bot is shutting down immediately.

All your PRO limits, profile data, and saved jobs have already been safely transferred.

👉 <b>Please click here to continue using the service:</b> @FroncyBot"""

async def run_migration():
    logger.info("Starting user migration broadcast...")
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    
    # 1. Connect to DB
    conn = await asyncpg.connect(settings.DATABASE_URL)
    
    try:
        # 2. Get all users who aren't deleted
        users = await conn.fetch("SELECT telegram_id FROM users WHERE is_deleted IS NULL OR is_deleted = False")
        
        logger.info(f"Found {len(users)} active users to migrate.")
        
        success_count = 0
        fail_count = 0
        
        # 3. Broadcast message
        for user in users:
            tid = user['telegram_id']
            try:
                await bot.send_message(
                    chat_id=tid,
                    text=MESSAGE,
                    parse_mode="HTML"
                )
                logger.info(f"✅ Migration message sent to {tid}")
                success_count += 1
                await asyncio.sleep(0.5)  # Respect Telegram rate limits
            except Exception as e:
                logger.error(f"❌ Failed to send to {tid}: {e}")
                fail_count += 1
                
        logger.info(f"🎉 Broadcast complete! Success: {success_count}, Failed: {fail_count}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
