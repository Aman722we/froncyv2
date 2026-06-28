import asyncio
from db.connection import init_db, get_pool, close_db

MIGRATIONS = """
-- Retention: one row per user per day (UNIQUE prevents duplicates)
CREATE TABLE IF NOT EXISTS daily_active_users (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    active_date DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE(telegram_id, active_date)
);
CREATE INDEX IF NOT EXISTS idx_dau_date ON daily_active_users (active_date DESC);
CREATE INDEX IF NOT EXISTS idx_dau_user ON daily_active_users (telegram_id, active_date DESC);

-- Application intent: log every time a user clicks the Apply/Open Link button
CREATE TABLE IF NOT EXISTS link_clicks (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    job_id      INT,  -- manual_jobs id; NULL if somehow not tracked
    clicked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_link_clicks_date ON link_clicks (clicked_at DESC);
"""

async def run():
    await init_db()
    pool = get_pool()
    async with pool.acquire() as c:
        await c.execute(MIGRATIONS)
    await close_db()
    print("Migration complete: daily_active_users + link_clicks tables created.")

asyncio.run(run())
