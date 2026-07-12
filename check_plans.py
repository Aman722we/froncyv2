import asyncio
from db.connection import get_pool, init_db
from db.users import downgrade_expired_trials

async def main():
    await init_db()
    
    # Run the downgrade logic first
    await downgrade_expired_trials()
    
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT plan, COUNT(*) FROM users GROUP BY plan")
        print("Plan distribution:")
        for row in rows:
            print(f"  {row['plan']}: {row['count']}")
        
        trial_rows = await conn.fetch("SELECT is_trial, COUNT(*) FROM users GROUP BY is_trial")
        print("\nTrial distribution:")
        for row in trial_rows:
            print(f"  {row['is_trial']}: {row['count']}")
            
        onboard_rows = await conn.fetch("SELECT plan, is_onboarded, COUNT(*) FROM users GROUP BY plan, is_onboarded")
        print("\nPlan + Onboarded distribution:")
        for row in onboard_rows:
            print(f"  plan={row['plan']}, onboarded={row['is_onboarded']}: {row['count']}")

if __name__ == "__main__":
    asyncio.run(main())
