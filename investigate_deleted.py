import asyncio
import asyncpg
import json
from datetime import datetime, date
from config import settings

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

async def main():
    pool = await asyncpg.create_pool(settings.DATABASE_URL, statement_cache_size=0)
    async with pool.acquire() as conn:
        print("Checking for recently deleted users...")
        rows = await conn.fetch("""
            SELECT telegram_id, first_name, username, plan, created_at, updated_at 
            FROM users 
            WHERE is_deleted = TRUE 
            ORDER BY updated_at DESC 
            LIMIT 5
        """)
        
        if not rows:
            print("No deleted users found.")
        else:
            for row in rows:
                print(json.dumps(dict(row), indent=2, cls=DateTimeEncoder))
                
    await pool.close()

asyncio.run(main())
