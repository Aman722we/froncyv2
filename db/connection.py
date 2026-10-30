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
                    telegram_id BIGINT,
                    job_id INT,
                    seen_at TIMESTAMPTZ DEFAULT NOW(),
                    bot_id INT DEFAULT 1
                );
            """)
            await conn.execute("ALTER TABLE user_seen_jobs ADD COLUMN IF NOT EXISTS bot_id INT DEFAULT 1;")
            await conn.execute("UPDATE user_seen_jobs SET bot_id = 1 WHERE bot_id IS NULL;")
            await conn.execute("ALTER TABLE user_seen_jobs DROP CONSTRAINT IF EXISTS user_seen_jobs_telegram_id_job_id_key;")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_seen_jobs_unique ON user_seen_jobs (telegram_id, job_id, bot_id);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_seen_jobs_user_bot ON user_seen_jobs (telegram_id, bot_id, seen_at DESC);")
            
            # Create jobs_sent_log to track daily feed history (3-day cooldowns)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs_sent_log (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT,
                    job_id INT,
                    sent_at TIMESTAMPTZ DEFAULT NOW(),
                    bot_id INT DEFAULT 1
                );
            """)
            await conn.execute("ALTER TABLE jobs_sent_log ADD COLUMN IF NOT EXISTS bot_id INT DEFAULT 1;")
            await conn.execute("UPDATE jobs_sent_log SET bot_id = 1 WHERE bot_id IS NULL;")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_sent_log_user_bot ON jobs_sent_log (telegram_id, bot_id, sent_at DESC);")
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
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_url TEXT;")
        except Exception as e:
            logger.warning(f"Failed to apply concierge_resume migrations: {e}")

        # Referral system migrations
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_bonus_days INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_rewarded BOOLEAN DEFAULT FALSE;")
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
                    created_at   TIMESTAMPTZ DEFAULT NOW()
                );
                ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
                ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS used_at TIMESTAMPTZ DEFAULT NOW();
                UPDATE ai_usage_logs SET used_at = created_at WHERE used_at IS NULL AND created_at IS NOT NULL;
                UPDATE ai_usage_logs SET created_at = used_at WHERE created_at IS NULL AND used_at IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_ai_usage_logs_user ON ai_usage_logs(telegram_id);
            """)
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
                    created_at           TIMESTAMPTZ DEFAULT NOW(),
                    guru_telegram_id     BIGINT
                );
            """)
            # Handle existing installations by adding the column if missing
            await conn.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS guru_telegram_id BIGINT;")
            
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
                # Use CASCADE to automatically drop all foreign keys in other tables
                # that reference this primary key before creating the new composite one.
                await conn.execute(
                    "ALTER TABLE users DROP CONSTRAINT users_pkey CASCADE;"
                )
                await conn.execute(
                    "ALTER TABLE users ADD CONSTRAINT users_bot_telegram_pkey "
                    "PRIMARY KEY (telegram_id, bot_id);"
                )
                logger.info("Migrated users PK to composite (telegram_id, bot_id)")
        except Exception as e:
            logger.warning(f"Failed to apply multi-tenant migrations: {e}")

        # Career Page Sources (Froncy V2)
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS career_sources (
                    id                      SERIAL PRIMARY KEY,
                    company_name            TEXT NOT NULL,
                    provider                TEXT NOT NULL,  -- GREENHOUSE / LEVER / ASHBY
                    board_token             TEXT NOT NULL,
                    careers_url             TEXT,
                    is_active               BOOLEAN DEFAULT TRUE,
                    last_checked_at         TIMESTAMPTZ,
                    last_successful_check_at TIMESTAMPTZ,
                    last_error              TEXT,
                    created_at              TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_career_sources_provider_token ON career_sources (provider, board_token);")
            
            # Pre-seed the 6 companies the admin specified
            companies = [
                ("Sourcegraph",              "GREENHOUSE", "sourcegraph91"),
                ("G-P (Globalization Partners)", "GREENHOUSE", "globalizationpartners"),
                ("SingleStore",              "GREENHOUSE", "singlestore"),
                ("Gather AI",                "GREENHOUSE", "gatherai"),
                ("AlphaSense",               "GREENHOUSE", "alphasense"),
                ("Fingerprint",              "GREENHOUSE", "fingerprint"),
            ]
            for cname, provider, token in companies:
                await conn.execute(
                    """
                    INSERT INTO career_sources (company_name, provider, board_token)
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                    """,
                    cname, provider, token
                )
            
            # Add freshness tracking columns to manual_jobs
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'manual';")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS source_provider TEXT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS source_external_id TEXT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS description TEXT;")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_jobs_source ON manual_jobs (source_provider, source_external_id) WHERE source_external_id IS NOT NULL;")
            # Intelligent JD Metadata (Froncy V2.1)
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS max_yoe INT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS role_category TEXT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS role_summary TEXT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS workplace_type TEXT;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS is_fresher_friendly BOOLEAN DEFAULT FALSE;")
            # Clean up existing Lever and Ashby URLs so they open the JD page instead of the apply page
            await conn.execute("UPDATE manual_jobs SET url = regexp_replace(url, '/apply/?$', '') WHERE url LIKE '%/apply%' OR url LIKE '%/apply/';")
            await conn.execute("UPDATE manual_jobs SET url = regexp_replace(url, '/application/?$', '') WHERE url LIKE '%/application%' OR url LIKE '%/application/';")
            # Clean up raw HTML tags and escaped entities from job descriptions in DB
            await conn.execute("""
                UPDATE manual_jobs 
                SET description = regexp_replace(
                    regexp_replace(
                        replace(replace(replace(replace(replace(description, '&quot;', '"'), '&#39;', ''''), '&amp;', '&'), '&nbsp;', ' '), '&gt;', '>'),
                        '<[^>]+>', ' ', 'g'
                    ),
                    '\\s+', ' ', 'g'
                )
                WHERE description LIKE '%<%' OR description LIKE '%&quot;%' OR description LIKE '%&amp;%';
            """)
            # Track skills enrichment attempts to prevent infinite retry loops
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS skills_attempts INT DEFAULT 0;")
            await conn.execute("ALTER TABLE manual_jobs ADD COLUMN IF NOT EXISTS skills_attempted_at TIMESTAMPTZ;")
        except Exception as e:
            logger.warning(f"Failed to apply career_sources migrations: {e}")

    # ── Monetization V2 — HR Contacts, Resume Reviews, Request Queue ──
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS hr_requests_left INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_reviews_left INT DEFAULT 0;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS manual_requests (
                    id              SERIAL PRIMARY KEY,
                    user_id         BIGINT NOT NULL,
                    request_type    TEXT NOT NULL,
                    job_id          INT,
                    notes           TEXT,
                    status          TEXT DEFAULT 'PENDING',
                    completed_at    TIMESTAMPTZ,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await conn.execute("ALTER TABLE manual_requests ADD COLUMN IF NOT EXISTS admin_reply TEXT;")
            await conn.execute("ALTER TABLE manual_requests ADD COLUMN IF NOT EXISTS bot_id INT DEFAULT 1;")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_manual_requests_bot ON manual_requests (bot_id, request_type);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_manual_jobs_active_partial ON manual_jobs (posted_at DESC) WHERE is_active = TRUE;")
        except Exception as e:
            logger.warning(f"Failed to apply monetization_v2 migrations: {e}")

        # LinkedIn Posts tracking to prevent cross-post duplicate jobs
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS linkedin_featured_jobs (
                    id           SERIAL PRIMARY KEY,
                    job_id       INT REFERENCES manual_jobs(id) ON DELETE CASCADE,
                    stream       TEXT NOT NULL,
                    slot         TEXT,
                    featured_at  TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_linkedin_featured_jobs_job ON linkedin_featured_jobs (job_id, featured_at DESC);
            """)
        except Exception as e:
            logger.warning(f"Failed to apply linkedin_featured_jobs migration: {e}")

        # Engagement & Click Tracking migrations (Instant Alerts, Apply Intent, HR Details)
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS link_clicks (
                    id          SERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL,
                    job_id      INT,
                    source      TEXT DEFAULT 'other',
                    clicked_at  TIMESTAMPTZ DEFAULT NOW()
                );
                ALTER TABLE link_clicks ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'other';
                CREATE INDEX IF NOT EXISTS idx_link_clicks_source_time ON link_clicks (source, clicked_at DESC);
                CREATE INDEX IF NOT EXISTS idx_link_clicks_time ON link_clicks (clicked_at DESC);

                CREATE TABLE IF NOT EXISTS instant_alerts_sent (
                    id          SERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL,
                    job_id      INT NOT NULL,
                    sent_at     TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_instant_alerts_sent_time ON instant_alerts_sent (sent_at DESC);
                CREATE INDEX IF NOT EXISTS idx_instant_alerts_sent_user ON instant_alerts_sent (telegram_id, sent_at DESC);

                CREATE TABLE IF NOT EXISTS hr_request_clicks (
                    id          SERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL,
                    job_id      INT,
                    source      TEXT DEFAULT 'instant_alert',
                    clicked_at  TIMESTAMPTZ DEFAULT NOW()
                );
                ALTER TABLE hr_request_clicks ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'instant_alert';
                CREATE INDEX IF NOT EXISTS idx_hr_request_clicks_source_time ON hr_request_clicks (source, clicked_at DESC);
                CREATE INDEX IF NOT EXISTS idx_hr_request_clicks_time ON hr_request_clicks (clicked_at DESC);
            """)
        except Exception as e:
            logger.warning(f"Failed to apply engagement tracking migrations: {e}")

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
