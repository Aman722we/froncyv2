import asyncio
from db.connection import get_pool, init_db

async def main():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users LIMIT 1")
        if row:
            for key, val in dict(row).items():
                print(f"{key}: {type(val).__name__}")
        else:
            print("No users found.")

if __name__ == "__main__":
    asyncio.run(main())
