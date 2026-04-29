import asyncio
from db.connection import get_pool, init_db

async def main():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT id, title, salary FROM manual_jobs ORDER BY id DESC LIMIT 5')
        for r in rows:
            print(dict(r))

if __name__ == "__main__":
    asyncio.run(main())
