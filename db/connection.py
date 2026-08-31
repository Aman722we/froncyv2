"""
Database connection pool management using asyncpg.
"""
import asyncpg
from pathlib import Path
from loguru import logger
from config import settings


_pool: asyncpg.Pool | None = None


async def init_db() -> asyncpg.Pool:
    """Initialize the database connection pool and run schema."""
    global _pool

    if _pool is not None:
        return _pool

    logger.info("Connecting to PostgreSQL...")
    _pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=30,
        max_inactive_connection_lifetime=300,
        statement_cache_size=0,
    )

    # Run schema on first boot
    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    async with _pool.acquire() as conn:
        await conn.execute(schema_sql)
        
        # Soft migrations for new columns
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS experience_level TEXT DEFAULT '0';")
            await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS experience_required INT NULL;")
            await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_type TEXT DEFAULT 'full-time';")
            await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duration TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ats_checks_today INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ats_checks_reset DATE DEFAULT CURRENT_DATE;")
        except Exception as e:
            logger.warning(f"Failed to apply DB migrations: {e}")

        # Drop restrictive foreign keys so applications/saved_jobs can hold manual_jobs IDs
        try:
            await conn.execute("ALTER TABLE applications DROP CONSTRAINT IF EXISTS applications_job_id_fkey;")
            await conn.execute("ALTER TABLE saved_jobs DROP CONSTRAINT IF EXISTS saved_jobs_job_id_fkey;")
            
            # Create user_seen_jobs for deduplication algorithm
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_seen_jobs (
                    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    job_id INT,
                    seen_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(telegram_id, job_id)
                );
            """)
            
            # Create jobs_sent_log to track daily feed history (3-day cooldowns)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs_sent_log (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    job_id INT,
                    sent_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_sent_log_user ON jobs_sent_log (telegram_id, job_id, sent_at DESC);")
        except Exception as e:
            logger.warning(f"Failed to apply constraint/seen_jobs migrations: {e}")

        # Trial & pricing migrations
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMPTZ;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_trial BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role_pref VARCHAR(50) DEFAULT 'fullstack';")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_early_adopter BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT NOW();")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS batch_year INT;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pricing_config (
                    id                   SERIAL PRIMARY KEY,
                    early_adopter_price  INT DEFAULT 199,
                    regular_price        INT DEFAULT 499,
                    early_adopter_slots  INT DEFAULT 200,
                    slots_filled         INT DEFAULT 0,
                    early_adopter_active BOOLEAN DEFAULT TRUE,
                    launch_date          TIMESTAMPTZ DEFAULT NOW(),
                    razorpay_early_plan_id TEXT,
                    razorpay_reg_plan_id   TEXT
                );
            """)
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS razorpay_customer_id TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS razorpay_subscription_id TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status TEXT;")
            await conn.execute("ALTER TABLE pricing_config ADD COLUMN IF NOT EXISTS razorpay_early_plan_id TEXT;")
            await conn.execute("ALTER TABLE pricing_config ADD COLUMN IF NOT EXISTS razorpay_reg_plan_id TEXT;")
            await conn.execute("""
                INSERT INTO pricing_config (
                    early_adopter_price, regular_price, early_adopter_slots,
                    slots_filled, early_adopter_active, launch_date
                )
                SELECT 199, 499, 200, 0, TRUE, NOW()
                WHERE NOT EXISTS (SELECT 1 FROM pricing_config);
            """)
        except Exception as e:
            logger.warning(f"Failed to apply trial/pricing migrations: {e}")

        # Manual jobs & batch year migrations
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS batch_year INT;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS manual_jobs (
                    id               SERIAL PRIMARY KEY,
                    title            TEXT NOT NULL,
                    company          TEXT NOT NULL,
                    url              TEXT NOT NULL,
                    location         TEXT,
                    salary           TEXT,
                    job_type         TEXT DEFAULT 'fulltime',
                    duration         TEXT,
                    skills           TEXT[] DEFAULT '{}',
                    min_yoe          INT DEFAULT 0,
                    eligible_batches INT[] DEFAULT '{}',
                    posted_at        TIMESTAMPTZ DEFAULT NOW(),
                    is_active        BOOLEAN DEFAULT TRUE,
                    added_by         BIGINT
                );
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_manual_jobs_active ON manual_jobs (is_active, posted_at DESC);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_manual_jobs_skills ON manual_jobs USING GIN (skills);")
            # Add manual_job_id to saved_jobs so users can bookmark manual jobs too
            await conn.execute("ALTER TABLE saved_jobs ADD COLUMN IF NOT EXISTS manual_job_id INT REFERENCES manual_jobs(id) ON DELETE CASCADE;")
            # Apply Smart — Hiring Manager columns on manual_jobs
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS hm_name TEXT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS hm_role TEXT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS hm_linkedin TEXT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS hm_email TEXT;")
        except Exception as e:
            logger.warning(f"Failed to apply manual_jobs migrations: {e}")

        # Apply Smart usage tracking on users
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS apply_smart_used INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS apply_smart_reset DATE DEFAULT CURRENT_DATE;")
        except Exception as e:
            logger.warning(f"Failed to apply apply_smart migrations: {e}")

        # Concierge Resume Fix — flag for users with unparseable resumes
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS needs_manual_resume BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS raw_resume_bytes BYTEA;")
        except Exception as e:
            logger.warning(f"Failed to apply concierge_resume migrations: {e}")

        # Referral system migrations
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_bonus_days INT DEFAULT 0;")
        except Exception as e:
            logger.warning(f"Failed to apply referral migrations: {e}")

        # Community Job Submissions
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_submissions (
                    id           SERIAL PRIMARY KEY,
                    telegram_id  BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    url          TEXT NOT NULL,
                    status       TEXT DEFAULT 'pending',  -- pending/approved/rejected
                    submitted_at TIMESTAMPTZ DEFAULT NOW(),
                    reviewed_at  TIMESTAMPTZ,
                    manual_job_id INT REFERENCES manual_jobs(id) ON DELETE SET NULL
                );
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_submissions_status ON user_submissions(status, submitted_at DESC);"
            )
        except Exception as e:
            logger.warning(f"Failed to apply user_submissions migrations: {e}")

        # AI Usage Tracking
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_usage_logs (
                    id           SERIAL PRIMARY KEY,
                    telegram_id  BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    feature_type TEXT NOT NULL,
                    used_at      TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_usage_logs_user ON ai_usage_logs(telegram_id, used_at DESC);"
            )
        except Exception as e:
            logger.warning(f"Failed to apply ai_usage_logs migrations: {e}")

        # ── Multi-Tenant Architecture ─────────────────────────────────────────
        # Creates the `bots` table for Guru white-label bots and adds a `bot_id`
        # foreign key to `users` so each tenant's audience is fully isolated.
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bots (
                    id                   SERIAL PRIMARY KEY,
                    bot_token            TEXT UNIQUE NOT NULL,
                    bot_username         TEXT NOT NULL,
                    guru_name            TEXT NOT NULL,
                    razorpay_account_id  TEXT DEFAULT '',
                    split_percentage     INT DEFAULT 50,
                    is_active            BOOLEAN DEFAULT TRUE,
                    created_at           TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Add bot_id FK to users. NULL = original primary FroncyBot (bot_id = 1)
            await conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS bot_id INT REFERENCES bots(id) ON DELETE SET NULL;"
            )
            # Composite B-Tree index: all user lookups go through (bot_id, telegram_id)
            # O(log N) lookup time regardless of total user count across all tenants
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_bot_telegram ON users (bot_id, telegram_id);"
            )
            # Ensure the primary FroncyBot always has a row in bots (id=1)
            # We use ON CONFLICT so this is idempotent on every restart
            from config import settings as _s
            await conn.execute("""
                INSERT INTO bots (id, bot_token, bot_username, guru_name, split_percentage)
                VALUES (1, $1, 'FroncyJobsBot', 'Froncy (Primary)', 100)
                ON CONFLICT (bot_token) DO NOTHING
            """, _s.TELEGRAM_BOT_TOKEN)
            
            # Fix sequence since we manually inserted id=1
            await conn.execute("SELECT setval('bots_id_seq', (SELECT COALESCE(MAX(id), 1) FROM bots));")
            
            # Add guru_telegram_id so the Creator can access their own dashboard
            await conn.execute(
                "ALTER TABLE bots ADD COLUMN IF NOT EXISTS guru_telegram_id BIGINT;"
            )

            # ── Multi-Tenant User Isolation ──────────────────────────────────────
            # Change the users PK from telegram_id alone to (telegram_id, bot_id).
            # This means the same Telegram user is treated as a SEPARATE new user
            # on each Creator bot — proper white-label isolation.
            # We do this in two safe steps:
            #   1. Ensure bot_id is NOT NULL for all existing rows (default to 1)
            #   2. Drop the old single-column PK and add the composite PK
            await conn.execute(
                "UPDATE users SET bot_id = 1 WHERE bot_id IS NULL;"
            )
            await conn.execute(
                "ALTER TABLE users ALTER COLUMN bot_id SET DEFAULT 1;"
            )
            await conn.execute(
                "ALTER TABLE users ALTER COLUMN bot_id SET NOT NULL;"
            )
            # Only add composite PK if the old one still exists
            pk_exists = await conn.fetchval(
                """
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name='users' AND constraint_type='PRIMARY KEY'
                  AND constraint_name='users_pkey'
                """
            )
            composite_pk_exists = await conn.fetchval(
                """
                SELECT 1 FROM pg_indexes
                WHERE tablename='users' AND indexname='users_bot_telegram_pkey'
                """
            )
            if pk_exists and not composite_pk_exists:
                # We MUST drop any foreign keys that reference the old primary key
                # before we can drop the primary key itself!
                try:
                    await conn.execute(
                        "ALTER TABLE ai_usage_logs DROP CONSTRAINT IF EXISTS ai_usage_logs_telegram_id_fkey;"
                    )
                except Exception as e:
                    logger.warning(f"Could not drop ai_usage_logs_telegram_id_fkey: {e}")
                
                await conn.execute(
                    "ALTER TABLE users DROP CONSTRAINT users_pkey;"
                )
                await conn.execute(
                    "ALTER TABLE users ADD CONSTRAINT users_bot_telegram_pkey "
                    "PRIMARY KEY (telegram_id, bot_id);"
                )
                logger.info("Migrated users PK to composite (telegram_id, bot_id)")
        except Exception as e:
            logger.warning(f"Failed to apply multi-tenant migrations: {e}")

    logger.info("Database initialized successfully.")
    return _pool


def get_pool() -> asyncpg.Pool:
    """Get the active connection pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


async def close_db():
    """Gracefully close the database pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")
