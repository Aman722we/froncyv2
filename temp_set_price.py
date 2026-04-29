import asyncio
from db.connection import get_pool, init_db

async def main():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''
            UPDATE pricing_config 
            SET early_adopter_price = 199, 
                regular_price = 499, 
                razorpay_early_plan_id = NULL, 
                razorpay_reg_plan_id = NULL
        ''')
    print('Pricing updated to ₹199/₹499 successfully!')

if __name__ == "__main__":
    asyncio.run(main())
