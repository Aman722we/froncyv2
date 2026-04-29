-- ================================================
-- ApplixyBot Database Schema
-- PostgreSQL 15 (Supabase)
-- ================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    telegram_id      BIGINT PRIMARY KEY,
    username         TEXT,
    first_name       TEXT,
    plan             TEXT DEFAULT 'free',           -- free/pro/proplus/premium
    plan_expires_at  TIMESTAMPTZ,
    skills           TEXT[] DEFAULT '{}',            -- ['react','typescript','nextjs']
    location_pref    TEXT DEFAULT 'remote',          -- remote/india/both
    alert_time       TEXT DEFAULT '09:00',           -- HH:MM IST
    resume_text      TEXT,                           -- extracted PDF text
    resume_filename  TEXT,
    experience_level TEXT DEFAULT '0',               -- options: '0', '1', '2', '3-5', '5+'
    batch_year       INT,                            -- graduation year e.g. 2024, 2025
    cover_letters_used  INT DEFAULT 0,               -- resets monthly
    cover_letters_reset TIMESTAMPTZ DEFAULT NOW(),   -- when counter was last reset
    auto_applies_today  INT DEFAULT 0,               -- resets daily
    auto_applies_reset  DATE DEFAULT CURRENT_DATE,   -- when counter was last reset
    is_onboarded     BOOLEAN DEFAULT FALSE,          -- completed onboarding flow
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    razorpay_customer_id     TEXT,
    razorpay_subscription_id TEXT,
    subscription_status      TEXT,
    is_deleted               BOOLEAN DEFAULT FALSE,
    trial_used               BOOLEAN DEFAULT FALSE
);

-- Pricing Configuration
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

-- Jobs cache table
CREATE TABLE IF NOT EXISTS jobs (
    id            SERIAL PRIMARY KEY,
    url_hash      TEXT UNIQUE NOT NULL,              -- MD5 of job URL (dedup key)
    title         TEXT NOT NULL,
    company       TEXT,
    url           TEXT NOT NULL,
    location      TEXT,
    salary        TEXT,
    job_type      TEXT DEFAULT 'full-time',          -- full-time/internship/contract
    duration      TEXT,                              -- internship duration
    skills        TEXT[] DEFAULT '{}',
    experience_required INT NULL,                    -- requested years of experience
    source        TEXT,                              -- remotive/wwr/indeed/arbeitnow/jobicy
    portal_type   TEXT DEFAULT 'other',              -- greenhouse/lever/workable/other
    posted_at     TIMESTAMPTZ,
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    is_active     BOOLEAN DEFAULT TRUE
);

-- Index for fast skill-based job matching
CREATE INDEX IF NOT EXISTS idx_jobs_skills ON jobs USING GIN (skills);
CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs (is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_jobs_scraped ON jobs (scraped_at DESC);

-- Saved jobs (user bookmarks)
CREATE TABLE IF NOT EXISTS saved_jobs (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    job_id      INT REFERENCES jobs(id) ON DELETE CASCADE,
    saved_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(telegram_id, job_id)
);

-- Application log (auto-apply history)
CREATE TABLE IF NOT EXISTS applications (
    id           SERIAL PRIMARY KEY,
    telegram_id  BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    job_id       INT REFERENCES jobs(id) ON DELETE SET NULL,
    status       TEXT DEFAULT 'pending',             -- pending/submitted/failed/manual
    portal_type  TEXT,
    error_msg    TEXT,
    applied_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_applications_user ON applications (telegram_id, applied_at DESC);
-- 1. Update users table
ALTER TABLE users 
  ADD COLUMN IF NOT EXISTS cover_letters_today    INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cover_letters_reset_at DATE DEFAULT CURRENT_DATE,
  ADD COLUMN IF NOT EXISTS jobs_seen_today        INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS jobs_reset_at          DATE DEFAULT CURRENT_DATE;

-- Update plan column constraint (valid values)
-- free | pro  (pro+ is future, do not implement yet)

-- 2. Create applications tracking table
CREATE TABLE IF NOT EXISTS applications (
  id              SERIAL PRIMARY KEY,
  telegram_id     BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
  job_id          INT REFERENCES jobs(id) ON DELETE SET NULL,
  company_name    TEXT NOT NULL,
  job_title       TEXT NOT NULL,
  job_url         TEXT,
  status          TEXT DEFAULT 'applied',
  applied_at      TIMESTAMPTZ DEFAULT NOW(),
  last_reminded_at TIMESTAMPTZ,
  reminder_count  INT DEFAULT 0,
  notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_applications_telegram_id 
  ON applications(telegram_id);
CREATE INDEX IF NOT EXISTS idx_applications_status 
  ON applications(status);

-- 3. Create follow-up reminders queue table  
CREATE TABLE IF NOT EXISTS reminders (
  id            SERIAL PRIMARY KEY,
  telegram_id   BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
  application_id INT REFERENCES applications(id) ON DELETE CASCADE,
  remind_at     TIMESTAMPTZ NOT NULL,
  sent          BOOLEAN DEFAULT FALSE,
  reminder_type TEXT DEFAULT 'followup'
);

CREATE INDEX IF NOT EXISTS idx_reminders_remind_at 
  ON reminders(remind_at, sent);
