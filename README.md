# Froncy Bot — AI-Powered Job Alert & Resume Platform

> A production-grade, multi-tenant Telegram SaaS that delivers hyper-personalized job alerts, AI-generated ATS resumes, and automated cover letters to job-seekers via their Telegram inbox.

---

## 📌 What the Product Does

Froncy Bot is a **white-label Telegram bot platform** built around job seekers. Instead of a traditional web app, the entire product is delivered through Telegram.

**Core user-facing features:**
- **Smart Job Alerts:** Scans job boards daily and delivers matched roles directly to a user's Telegram chat based on their skills, experience level, and location preferences.
- **Bring-Your-Own-Job (Link Submission):** Users paste any external job posting URL (LinkedIn, Indeed, Naukri, etc.) and the bot automatically generates a custom, ATS-optimized resume and cover letter tailored to that exact role.
- **ATS Resume Generator:** Produces a structured, keyword-optimized resume from a user's uploaded PDF, scored and formatted for Applicant Tracking Systems.
- **Cover Letter Generator:** Generates a personalized cover letter for any saved job or submitted link using the user's profile and the job's requirements.
- **Job Tracker:** A Kanban-style board inside Telegram for tracking application statuses (Applied, Interview, Offer, etc.).
- **Subscription Payments:** Integrated Razorpay subscription flow with Early Adopter pricing tiers, trial periods, and auto-renewal handling via webhooks.
- **Admin Concierge Resume Fix:** Admin-initiated manual resume correction flow — admin uploads a fixed PDF which is auto-parsed, saved, and the user is notified instantly.

---

## 🏗️ Architecture

The system is a **single FastAPI server** hosting multiple independent Telegram bots (multi-tenant), each scoped to its own Creator ("Guru") and their audience.

```
Internet (Telegram API)
        │
        ▼
  FastAPI Server (main.py)
  /webhook/{token}  ──── routes to ────►  PTB Application (per bot)
                                                │
                          ┌─────────────────────┼─────────────────────┐
                          ▼                     ▼                     ▼
                   Handler Layer          Services Layer          Data Layer
                  (handlers/*.py)       (services/*.py)          (db/*.py)
                          │                     │                     │
                          │              ┌──────┴──────┐              │
                          │         LLM Service    Resume Parser   asyncpg Pool
                          │         (Groq API)     (PyMuPDF)          │
                          │                                           ▼
                          └─────────────────────────────────►  Supabase (PostgreSQL)
```

**Multi-Tenancy Model:**
- Each Creator ("Guru") gets their own branded Telegram bot registered via `/addbot`.
- A single `bots` table stores each bot's token, username, creator, and revenue split.
- All user data is scoped by `(telegram_id, bot_id)` composite key — one user can exist independently on multiple bots.
- A single Railway deployment serves all bots concurrently via `/webhook/{token}` routing.

**Scheduler:**
- APScheduler runs inside the FastAPI process, firing daily job alert batches per user.
- Rate-limited to avoid Telegram flood limits.

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **Bot Framework** | python-telegram-bot v21 (async, webhook mode) |
| **Web Server** | FastAPI + Uvicorn |
| **Database** | PostgreSQL via Supabase |
| **DB Driver** | asyncpg (async connection pool) |
| **LLM / AI** | Groq API (llama-3.3-70b-versatile, llama-3.1-8b-instant) |
| **Resume Parsing** | PyMuPDF (fitz) |
| **Payments** | Razorpay Subscriptions + Webhooks |
| **Scheduler** | APScheduler |
| **Deployment** | Railway (Docker-less, Nixpacks) |
| **Frontend (Landing)** | Next.js 14 (App Router) + Tailwind CSS |
| **Language** | Python 3.11, TypeScript |

---

## 📦 Major Modules

### `main.py` & `bot.py`
Entry point. Initializes the FastAPI app, sets up all bot instances via `build_bot()`, registers webhooks, and starts the scheduler. Each bot is an identical PTB `Application` with `bot_id` injected into `bot_data` for tenant scoping.

### `handlers/`
All Telegram conversation logic. Each file handles a major product feature:
- `start.py` — Onboarding, profile setup conversation flow
- `jobs.py` — Job feed, saved jobs, job detail cards
- `resume.py` — Resume upload, AI parsing, manual fix flow, replacement
- `submissions.py` — Link submission (Bring-Your-Own-Job) pipeline
- `cover_letter.py` — Cover letter generation
- `tracker.py` — Application tracker board
- `payments.py` — Razorpay subscription initiation and webhook handling
- `settings.py` — User preferences (skills, experience, alerts)
- `admin.py` — Admin-only commands (`/addbot`, `/fixresume`, `/getresume`, `/setcreator`, `/sendmessage`, `/badresumes`)
- `guru.py` — Creator dashboard (`/dashboard`, `/broadcast`)
- `analytics.py` — Usage analytics commands
- `menu.py` — Main menu keyboard
- `feedback.py` — User feedback collection
- `refer.py` — Referral system

### `services/`
Business logic and external integrations:
- `llm_service.py` — All Groq API calls: ATS analysis, resume generation, cover letter generation, parseability checks, and robust JSON extraction via regex fallback
- `resume_parser.py` — PDF text extraction via PyMuPDF with raw-byte storage for admin concierge flow
- `resume_builder.py` — Jinja2-based LaTeX resume template rendering
- `ats_analyzer.py` — Multi-signal ATS scoring against job descriptions
- `scheduler.py` — Daily job alert dispatch with per-user rate limiting
- `payment_service.py` — Razorpay subscription creation and validation
- `pricing_service.py` — Early Adopter vs. Regular pricing tier logic
- `referral_service.py` — Referral tracking and reward logic
- `reset_service.py` — Account reset flow

### `db/`
Async database access layer. Each file maps to a domain:
- `connection.py` — Pool initialization and all `CREATE TABLE / ALTER TABLE` migrations on startup
- `users.py` — CRUD for user profiles, resumes, subscriptions, flags
- `bots.py` — Bot registration, creator linking, Guru lookup
- `jobs.py` — External job feed queries
- `manual_jobs.py` — Admin-curated job management
- `submissions.py` — User-submitted job URLs and status tracking
- `tracker.py` — Application status tracking

### `utils/`
Shared utilities:
- `messages.py` — All user-facing message templates (Telegram MarkdownV2 / HTML)
- `keyboards.py` — All InlineKeyboard and ReplyKeyboard builders
- `error_alert.py` — Global crash reporter: sends formatted tracebacks to admin via Telegram
- `helpers.py` — Shared utility functions
- `limits.py` — Per-feature usage limits per plan tier
- `constants.py` — Shared constants
- `admin_notify.py` — Admin notification helpers

### `froncy-web/`
Next.js 14 landing page and marketing site for the platform. Built with App Router, Tailwind CSS, and deployed on Vercel.

---

## 📅 Development Timeline

| Period | Milestone |
|---|---|
| **April 2026** | Project initialized. Core bot scaffolding, database schema, onboarding flow. |
| **May 2026** | Resume upload + AI parsing pipeline. Job feed scraping. Daily scheduler. |
| **June 2026** | Razorpay payment integration. Subscription tiers, trial periods, Early Adopter pricing. |
| **July 2026** | Link submission (Bring-Your-Own-Job) feature. ATS analyzer. Cover letter generator. |
| **August 2026** | Multi-tenant architecture. Creator ("Guru") bot system. `/addbot` admin flow. |
| **September 2026** | Production hardening. Admin concierge resume fix. Full multi-tenant user isolation. AI parsing stability fixes. |

**Total active development period:** ~6 months (April 2026 – September 2026)

---

## 🚀 Production Status

**Status: Live in production**

- Deployed on Railway via Nixpacks (Python 3.11)
- Database hosted on Supabase (PostgreSQL)
- Webhook-based architecture (no polling) for near-instant message delivery
- All secrets and credentials managed via Railway environment variables
- Error monitoring via in-bot crash alerts to admin Telegram

---

## 👥 Current User Base

- **200+ active registered users** across deployed bot instances
- Live since May 2026
- Users span multiple Creator bot tenants (multi-tenant deployment)

---

## 🤖 AI-Assisted Development Disclosure

This codebase was developed with significant AI code generation assistance (Claude, Gemini). The human developer (solo founder) was responsible for:

- **System architecture and design decisions** — multi-tenancy model, webhook routing strategy, database schema, module boundaries
- **Product logic and feature specification** — defining every feature, conversation flow, and edge case
- **Integration orchestration** — connecting Telegram PTB, asyncpg, Groq, Razorpay, and APScheduler into a coherent system
- **Production debugging and iteration** — identifying and fixing real production bugs (e.g. AI JSON extraction failures, database constraint issues, silent crash handler failures)
- **Prompt engineering** — all LLM prompt design for resume generation, ATS analysis, and cover letter generation

AI tools were used to accelerate implementation of boilerplate, repetitive handler patterns, and SQL query construction. All code is fully functional and has been validated in a live production environment serving real users.

---

## 📊 Repository Statistics

| Metric | Value |
|---|---|
| **Total Lines of Code** | ~13,300+ (Python + TypeScript/React) |
| **Python / SQL files** | ~12,200 lines across 96 files |
| **Frontend (Next.js)** | ~1,100 lines across 11 components |
| **Total Commits** | 273 |
| **Development Period** | April 2026 – September 2026 (~6 months) |
| **Active Branches** | `main` (production), `develop` (staging) |
| **Largest modules** | `utils/messages.py` (1,127 lines), `handlers/jobs.py` (920 lines), `handlers/resume.py` (859 lines) |

---

## 📁 What Data Is Included / Excluded

### ✅ Included in this repository
- All application source code (Python bot, services, DB layer, utils)
- Database schema and all migration logic (`db/connection.py`)
- Jinja2 / LaTeX resume template (`assets/resume_template.tex.j2`)
- Next.js landing page source (`froncy-web/src/`)
- Deployment configuration (`nixpacks.toml`, `Procfile`, `railway.json`)
- Environment variable template (`.env.example`) with blank/placeholder values

### ❌ Excluded from this repository
- `.env` files — all secrets (API keys, tokens, DB credentials) are environment variables only
- `resumes/` directory — user-uploaded resume PDF files (user PII, not committed)
- `venv/` — Python virtual environment
- `node_modules/` — Node.js dependencies
- `.next/` — Next.js build output
- `__pycache__/` — Python bytecode cache
- Any real user data — no PII, no user records, no payment data is stored in the repository

---

## ⚙️ Environment Variables Required

See `.env.example` for the full list. Key variables:

```
TELEGRAM_BOT_TOKEN=          # Primary bot token from BotFather
WEBHOOK_URL=                 # Public Railway domain (https://your-app.up.railway.app)
DATABASE_URL=                # Supabase PostgreSQL connection string
ADMIN_TELEGRAM_ID=           # Your Telegram user ID for admin commands
NVIDIA_API_KEY_70B=          # Groq API key (used for llama-3.3-70b)
NVIDIA_API_KEY_8B=           # Groq API key (used for llama-3.1-8b)
RAZORPAY_KEY_ID=             # Razorpay public key
RAZORPAY_KEY_SECRET=         # Razorpay secret key
RAZORPAY_WEBHOOK_SECRET=     # Razorpay webhook signature secret
ENVIRONMENT=production
```
