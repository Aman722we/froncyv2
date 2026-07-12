import asyncio
from db.connection import get_pool, init_db
from datetime import datetime, timedelta, timezone

async def main():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        # Find all jobs where posted_at has no timezone info (timezone offset = 0 but stored as naive)
        # In PostgreSQL, TIMESTAMPTZ is always stored in UTC, so naive vs aware is not an issue 
        # there — but let's check the 6 jobs added today that are NOT showing in the 24h window.
        # The cutoff used is 24h ago from NOW()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        # Show ALL jobs ordered by posted_at descending (latest 15)
        rows = await conn.fetch(
            "SELECT id, title, company, posted_at FROM manual_jobs WHERE is_active = TRUE ORDER BY posted_at DESC LIMIT 20"
        )
        print(f"All active jobs (latest first):")
        print(f"24h cutoff: {cutoff}")
        print()
        for r in rows:
            age = datetime.now(timezone.utc) - r['posted_at']
            within_24h = r['posted_at'] > cutoff
            print(f"  [{'YES' if within_24h else ' NO'}] {r['title'][:45]} | posted={r['posted_at']} | age={str(age).split('.')[0]}")

if __name__ == "__main__":
    asyncio.run(main())
