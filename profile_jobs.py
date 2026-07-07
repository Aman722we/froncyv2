import asyncio
import time
from db.connection import init_db, get_pool
from db.users import get_user
from services.reset_service import check_and_reset_daily
from db.manual_jobs import get_personalized_manual_jobs, count_manual_jobs, get_seen_jobs
from config import settings

async def main():
    print("Initializing DB...")
    await init_db()
    pool = get_pool()
    
    user_id = 1165801115
    
    print("Testing handler sequence...")
    
    start = time.time()
    await check_and_reset_daily(user_id, pool)
    print(f"check_and_reset_daily took: {time.time() - start:.3f}s")
    
    start = time.time()
    user = await get_user(user_id)
    print(f"get_user took: {time.time() - start:.3f}s")
    
    user_dict = {
        "telegram_id": user_id,
        "skills": user.get("skills", []),
        "location_pref": user.get("location_pref", "remote"),
        "plan": "free",
        "experience_level": user.get("experience_level", "0"),
        "batch_year": user.get("batch_year"),
        "role_pref": user.get("role_pref", "fullstack"),
    }
    
    start = time.time()
    seen_jobs = await get_seen_jobs(user_id)
    print(f"get_seen_jobs took: {time.time() - start:.3f}s")
    
    start = time.time()
    jobs = await get_personalized_manual_jobs(
        user_dict, 
        seen_job_ids=seen_jobs, 
        limit=5,
        exclude_sent_within_days=3,
        max_age_days=10
    )
    print(f"get_personalized_manual_jobs took: {time.time() - start:.3f}s")
    
    start = time.time()
    total_active_jobs = await count_manual_jobs()
    print(f"count_manual_jobs took: {time.time() - start:.3f}s")

    await pool.close()

asyncio.run(main())
