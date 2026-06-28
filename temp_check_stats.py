import asyncio
from db.connection import get_pool, init_db
from loguru import logger

async def check_stats():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        onboarded = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_onboarded = TRUE AND is_deleted = FALSE")
        resumes = await conn.fetchval("SELECT COUNT(*) FROM users WHERE resume_text IS NOT NULL AND is_deleted = FALSE")
        
        print(f"--- DB STATS ---")
        print(f"Completed Setup: {onboarded}")
        print(f"Uploaded Resume: {resumes}")

if __name__ == "__main__":
    asyncio.run(check_stats())
