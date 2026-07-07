import asyncio
import asyncpg
from config import settings

async def main():
    pool = await asyncpg.create_pool(settings.DATABASE_URL)
    count = await pool.fetchval('SELECT count(*) FROM manual_jobs')
    print("COUNT:", count)
    await pool.close()

asyncio.run(main())
