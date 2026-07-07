"""
COMPREHENSIVE LATENCY PROFILER — Windows-safe version
"""
import asyncio
import time
import os
os.environ["PYTHONIOENCODING"] = "utf-8"

_times = []

async def timed(label, coro):
    start = time.perf_counter()
    result = await coro
    ms = (time.perf_counter() - start) * 1000
    print(f"  [{ms:7.1f}ms] {label}")
    _times.append((label, ms))
    return result

async def main():
    print("\n=== PHASE 1: DATABASE CONNECTION ===")
    from db.connection import init_db, get_pool
    start = time.perf_counter()
    await init_db()
    pool = get_pool()
    print(f"  [{(time.perf_counter()-start)*1000:.1f}ms] Pool init")

    print("\n=== PHASE 2: CONNECTION ACQUISITION (5 rounds) ===")
    for i in range(5):
        start = time.perf_counter()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        ms = (time.perf_counter() - start) * 1000
        print(f"  [{ms:7.1f}ms] acquire+query round {i+1}")

    print("\n=== PHASE 3: SIMULATED view_jobs HANDLER ===")
    user_id = 1165801115
    handler_start = time.perf_counter()

    from services.reset_service import check_and_reset_daily
    await timed("check_and_reset_daily()", check_and_reset_daily(user_id, pool))

    from db.users import get_user
    user = await timed("get_user()", get_user(user_id))

    if not user:
        print("  User not found, using dummy...")
        user = {"telegram_id": user_id, "skills": [], "location_pref": "remote",
                "plan": "free", "experience_level": "0", "batch_year": None, 
                "role_pref": "fullstack", "is_onboarded": True}

    from db.manual_jobs import get_seen_jobs, count_manual_jobs, get_personalized_manual_jobs
    from utils.helpers import get_effective_plan

    plan = get_effective_plan(user)
    user_dict = {
        "telegram_id": user.get("telegram_id", user_id),
        "skills": user.get("skills", []),
        "location_pref": user.get("location_pref", "remote"),
        "plan": plan,
        "experience_level": user.get("experience_level", "0"),
        "batch_year": user.get("batch_year"),
        "role_pref": user.get("role_pref", "fullstack"),
    }

    # Parallel queries
    start = time.perf_counter()
    seen_jobs, total_active_jobs = await asyncio.gather(
        get_seen_jobs(user_id),
        count_manual_jobs()
    )
    ms = (time.perf_counter() - start) * 1000
    print(f"  [{ms:7.1f}ms] gather(get_seen_jobs, count_manual_jobs)")
    _times.append(("gather(seen+count)", ms))

    all_jobs = await timed("get_personalized_manual_jobs(100)", 
                           get_personalized_manual_jobs(user_dict, limit=100))

    # Format message (CPU only)
    from utils import messages, keyboards
    start = time.perf_counter()
    if all_jobs:
        page_jobs = all_jobs[:5]
        msg = messages.format_job_list_message(page_jobs, plan, len(all_jobs), user=user)
        kb = keyboards.job_list_keyboard(page_jobs, plan, len(all_jobs), 1)
    ms = (time.perf_counter() - start) * 1000
    print(f"  [{ms:7.1f}ms] format_message + build_keyboard (CPU)")
    _times.append(("format+keyboard", ms))

    total_handler = (time.perf_counter() - handler_start) * 1000
    
    print(f"\n=== TOTAL HANDLER TIME: {total_handler:.0f}ms ===")
    print(f"\nNOT included: Telegram API call to edit_message (~500-1500ms)")
    print(f"NOT included: Network hops (User -> Telegram -> Railway -> Telegram -> User)")
    
    total_db = sum(ms for _, ms in _times)
    print(f"\nTotal measured server-side: {total_db:.0f}ms")
    print(f"Estimated Telegram API + network overhead: ~{6000 - total_db:.0f}ms")

    await pool.close()

asyncio.run(main())
