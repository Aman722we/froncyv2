import asyncio
from db.connection import init_db, get_pool, close_db

CREATE_AI_USAGE_TABLE = """
CREATE TABLE IF NOT EXISTS ai_usage_logs (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    feature_type TEXT NOT NULL,  -- 'cover_letter' or 'ats_check'
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_date ON ai_usage_logs (feature_type, created_at DESC);
"""

async def run():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as c:
        await c.execute(CREATE_AI_USAGE_TABLE)
    await close_db()
    print("Migration complete: ai_usage_logs table created.")

asyncio.run(run())
