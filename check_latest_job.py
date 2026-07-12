import asyncio
from db.connection import get_pool, init_db

async def main():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        latest = await conn.fetchval("SELECT MAX(posted_at) FROM manual_jobs WHERE is_active = TRUE")
        print(f"Latest job posted_at: {latest}")

if __name__ == "__main__":
    asyncio.run(main())
