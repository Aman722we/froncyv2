import asyncio
from db.connection import init_db, get_pool, close_db
import json

async def check_users():
    await init_db()
    pool = get_pool()
    user_ids = [5692824902]
    
    async with pool.acquire() as conn:
        for uid in user_ids:
            row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", uid)
            if row:
                print(f"User {uid}:")
                # Print non-null fields to see how far they got
                progress = {k: v for k, v in dict(row).items() if v is not None and v != [] and v != ""}
                print(json.dumps(progress, indent=2, default=str))
                print("-" * 40)
            else:
                print(f"User {uid} not found in database.")
                print("-" * 40)

    await close_db()

asyncio.run(check_users())
