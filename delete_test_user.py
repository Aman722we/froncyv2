import asyncio
from db.connection import get_pool, init_db
from loguru import logger

async def delete_user(telegram_id: int):
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        logger.info(f"Deleting user {telegram_id} from database...")
        try:
            res = await conn.execute("DELETE FROM users WHERE telegram_id = $1", telegram_id)
            logger.info(f"Result: {res}")
        except Exception as e:
            logger.error(f"Error during deletion (maybe FK constraint): {e}")
            logger.info("Falling back to full reset of the user record instead.")
            await conn.execute("""
                UPDATE users 
                SET is_deleted = FALSE, 
                    is_onboarded = FALSE, 
                    skills = NULL,
                    location_pref = NULL,
                    batch_year = NULL,
                    resume_text = NULL,
                    resume_file_id = NULL
                WHERE telegram_id = $1
            """, telegram_id)
            logger.info("User reset successfully.")

if __name__ == "__main__":
    asyncio.run(delete_user(8619554269))
