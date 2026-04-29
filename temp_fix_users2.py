import asyncio
from db.connection import get_pool, init_db

async def main():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''
            UPDATE users 
            SET is_trial = FALSE, 
                plan_expires_at = COALESCE(plan_expires_at, NOW() + INTERVAL '1 month') 
            WHERE plan = 'pro' AND (is_trial = TRUE OR plan_expires_at IS NULL);
        ''')
    print('Fixed users!')

if __name__ == "__main__":
    asyncio.run(main())
