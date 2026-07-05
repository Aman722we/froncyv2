import asyncio
from db.connection import get_pool, init_db, close_db

async def find_user():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow('SELECT * FROM users WHERE telegram_id = 7963303313')
        if user:
            print(f'User Found:')
            print(f'ID: {user["telegram_id"]}')
            print(f'First Name: {user.get("first_name", "Unknown")}')
            print(f'Username: @{user.get("username", "Unknown")}')
            print(f'Onboarded: {user.get("is_onboarded", False)}')
        else:
            print('User not found.')
    await close_db()

if __name__ == "__main__":
    asyncio.run(find_user())
