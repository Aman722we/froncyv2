import asyncio
from db.connection import get_pool, init_db, close_db

async def main():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT first_name, username, resume_text FROM users WHERE telegram_id = $1", 1384292160)
        if user:
            print("User:", user["first_name"])
            print("-" * 40)
            text = user["resume_text"]
            if text:
                print("Length:", len(text))
                print("Preview:")
                print(text[:1000])
                with open("omi_resume.txt", "w", encoding="utf-8") as f:
                    f.write(text)
                print("Saved to omi_resume.txt")
            else:
                print("Resume text is EMPTY or NULL.")
        else:
            print("User not found in DB.")
    await close_db()

asyncio.run(main())
