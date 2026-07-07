import asyncio
import asyncpg
from config import settings

async def main():
    conn = await asyncpg.connect(settings.DATABASE_URL)
    rows = await conn.fetch("SELECT column_name, is_nullable, data_type FROM information_schema.columns WHERE table_name = 'applications'")
    for row in rows:
        print(dict(row))
    await conn.close()

asyncio.run(main())
