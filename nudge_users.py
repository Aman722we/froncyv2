import asyncio
from config import TELEGRAM_BOT_TOKEN
from telegram import Bot
from telegram.error import Forbidden, BadRequest
from db.database import get_pool
from loguru import logger

async def run_nudge():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    pool = get_pool()
    
    logger.info("Starting nudge broadcast for users who haven't completed onboarding...")
    
    async with pool.acquire() as conn:
        # Get users who are not onboarded and not deleted
        users = await conn.fetch("""
            SELECT telegram_id, first_name 
            FROM users 
            WHERE is_onboarded = FALSE 
            AND is_deleted = FALSE
        """)
        
    logger.info(f"Found {len(users)} users who dropped off during setup.")
    
    success = 0
    failed = 0
    
    for row in users:
        tid = row['telegram_id']
        name = row['first_name'] or "there"
        
        message = (
            f"Hey {name}! 👋\n\n"
            "You are just **one step away** from unlocking automated Frontend job alerts and AI cover letters!\n\n"
            "Type /start to pick up right where you left off and finish your profile. 🚀"
        )
        
        try:
            await bot.send_message(chat_id=tid, text=message, parse_mode="Markdown")
            logger.info(f"✅ Nudged user {tid}")
            success += 1
        except Forbidden:
            logger.error(f"❌ Failed to nudge {tid}: Bot was blocked")
            async with pool.acquire() as conn:
                await conn.execute("UPDATE users SET is_deleted = TRUE WHERE telegram_id = $1", tid)
            failed += 1
        except BadRequest as e:
            logger.error(f"❌ Failed to nudge {tid}: {e}")
            failed += 1
        except Exception as e:
            logger.error(f"❌ Error with {tid}: {e}")
            failed += 1
            
        await asyncio.sleep(0.5) # Rate limit protection
        
    logger.info(f"🎉 Nudge complete! Success: {success}, Failed: {failed}")

if __name__ == "__main__":
    asyncio.run(run_nudge())
