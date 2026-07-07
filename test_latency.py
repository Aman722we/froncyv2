import asyncio
import asyncpg
import time
from config import settings

async def main():
    print("Testing DB Latency...")
    start_pool = time.time()
    pool = await asyncpg.create_pool(settings.DATABASE_URL, statement_cache_size=0, min_size=1, max_size=1)
    print(f"Pool created in {time.time() - start_pool:.3f}s")
    
    async with pool.acquire() as conn:
        start_query = time.time()
        await conn.fetchval("SELECT 1")
        print(f"Query 1 (warmup) took {time.time() - start_query:.3f}s")
        
        start_query = time.time()
        await conn.fetchval("SELECT COUNT(*) FROM users")
        print(f"Query 2 (users count) took {time.time() - start_query:.3f}s")
        
        start_query = time.time()
        await conn.fetchval("SELECT COUNT(*) FROM jobs")
        print(f"Query 3 (jobs count) took {time.time() - start_query:.3f}s")
        
    await pool.close()

asyncio.run(main())
