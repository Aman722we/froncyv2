# 🧠 FroncyBot Project Brain & Master Architecture Handoff

> **CRITICAL INSTRUCTION FOR ALL AI AGENTS & COLLABORATORS:**  
> Read this entire document before making modifications or writing code. It captures the complete project evolution, architectural blueprints, live monetization models, database schema invariants, and hard-earned lessons from failed experiments that are not apparent from code alone.

---

## 1. Project Vision & Identity

* **Product Name:** Froncy / Applixy (`@FroncyJobsBot` / `getfroncy.com`).
* **Platform:** Python 3.11/3.12 Telegram Bot (`python-telegram-bot` v21 async) + FastAPI microservice (`main.py`) + Next.js web portal (`applixy-web`).
* **Target Audience:** Software engineers across **all experience tiers (0 to 5+ YOE)**, from freshers to mid-level and senior engineers looking to switch into product companies.
* **Core Value Proposition:**
  1. **Sub-15 Minute Career-Page Alerts:** Ingests jobs directly from 525+ official company ATS portals (Greenhouse, Lever, Ashby) before they are syndicated to public job boards like LinkedIn or Naukri.
  2. **100-Point Smart Matching:** Replaces spam with a transparent matching score (Skills + Taxonomy Expansion + YOE Gap + Role Preference).
  3. **Multi-Tenant White-Labeling:** Allows creators, communities, and tech influencers to launch their own branded career bot (`bot_id`) sharing the underlying 525+ company ingestion pipeline.

---

## 2. Core Architectural Pillars

### A. Career Page Sync Engine (`services/career_sync.py`, `services/career_fetcher.py`)
* Monitors **525+ verified company career sources** via direct REST endpoints (Greenhouse, Lever, Ashby).
* **Strict Gatekeeper (`is_relevant_tech_job`)**: Filters out sales, marketing, HR, support, and foreign non-remote roles *before* invoking any LLM, saving database storage and AI token costs.
* **LLM Metadata Enrichment (`extract_job_metadata`)**: Normalizes raw job descriptions into structured arrays: required skills, minimum YOE, salary ranges, workplace types (Remote/Hybrid/On-site), and normalized role categories.

### B. Unified 100-Point Matching Engine (`utils/messages.py`)
All surfaces (**Instant Alerts**, **Daily Morning Feed**, and **Browse Jobs**) share the exact same scoring logic (`compute_manual_job_match`):
* **40% Skills:** Taxonomy & synonym graph expansion (e.g., matching React to Next.js/Redux).
* **25% Experience:** Candidate YOE compared against minimum job requirement (rewards exact/fresher-friendly matches; scores slight/major experience gaps).
* **15% Recency:** Rewards newer job drops ($< 24\text{h}$).
* **10% Role Category:** Evaluates candidate role preference against title and `role_category`.
* **10% Salary Quality:** Rewards disclosed and competitive compensation.

**Surface Behavior:**
* **Instant Alerts (Real-Time):** Ingestion triggers evaluations across all Pro/Trial users; sends immediate alerts if score $\ge 50\%$.
* **Daily Feed (Scheduled Morning Drop):** Evaluates all active jobs, ranks descending by score, deduplicates against cooldowns (`jobs_sent_log`), and delivers top picks.
* **Browse Jobs (Interactive Pagination):** Evaluates pool against the user, displaying bold badges (`🟢 *High Match* (75%)`, `✅ *Match:* ...`, `⚠️ *Missing:* ...`, `✅ *Experience:* Matches`).

### C. Multi-Tenant Bot Network (`db/bots.py`, `bot_registry.py`)
* Enables running multiple Telegram bots simultaneously on the same container backend.
* **Database Isolation Rule:** All user lookups, state updates, seen jobs, and alert queues MUST scope by `bot_id`. Never execute global user updates without `bot_id` scoping.

### D. Analytics & Conversion Funnel (`handlers/analytics.py`, `db/tracker.py`)
* 5-page interactive dashboard accessible via `/analytics` and `/alertstats`:
  * **Page 1:** Users, Plans, Growth, Active Jobs.
  * **Page 2:** AI usage & Cover Letter generation stats.
  * **Page 3:** Link click tracking across legacy job boards.
  * **Page 4:** Instant Career Alert metrics (24h, 7d, 30d cohorts for Alerts Sent, Apply Clicks, HR Request Clicks, Daily Feed Clicks, Browse Jobs Clicks).
  * **Page 5:** Retention cohorts (Day-1, Day-7, Day-30).
* **Redirect Tracking:** All job application buttons route through `/r/{job_id}?uid={telegram_id}&src={surface}` via FastAPI to ensure zero untracked clicks.

### E. Monetization & Credit Guardrails (`handlers/requests.py`, `handlers/admin.py`)
* **SaaS Subscription:** Free tier (limited preview, locked breakdown) vs Pro Trial / Pro Subscription (instant alerts, full match insight, daily curated feeds).
* **Concierge Services:** Request HR Details (`hr_requests_left`) and Human Resume Review (`resume_reviews_left`) are strictly separated from bot subscriptions.
* **Trial Economics:** `/masstrial <days> [message|silent]` grants Pro trial access without granting free manual request credits, protecting unit economics.

---

## 3. Historical Incidents & Safeguards

### 1. The Telegram Deletion Incident
* **What Happened:** Original bot username was suspended by Telegram without prior notice.
* **The Safeguard:** Never market direct `t.me` URLs. All public marketing links point to `getfroncy.com` through Cloudflare. In a disaster recovery scenario, a new bot token is plugged in and Cloudflare is re-pointed without losing any user database records (`telegram_id` remains the immutable key).

### 2. The Merge Conflict / Broken Production Incident
* **What Happened:** Unsynchronized merges directly into `main` dropped critical imports, taking down production.
* **The Safeguard:** **NEVER push directly to `main`.** All development occurs on `develop`. Pushes must be synchronized to both remotes:
  ```powershell
  git push origin develop
  git push froncyv2 develop
  ```

### 3. The MarkdownV2 Reserved Character Crash
* **What Happened:** Using raw hyphens `-` or brackets `[` in string templates caused Telegram to reject messages with `BadRequest: Can't parse entities: character '-' is reserved`.
* **The Safeguard:** All MarkdownV2 messages must pass dynamic text through `escape_md()`. Literal dashes between title and company must be written as `\\-`. Fallback number tags must use `\\[{i}\\]`.

### 4. Database Column Drift Handling
* **What Happened:** Production database had `created_at` on `ai_usage_logs` while staging had `used_at`, crashing `/analytics` page 2.
* **The Safeguard:** Database queries inspect column existence dynamically via `information_schema.columns` or handle safe schema migrations in `db/connection.py`.

---

## 4. The Graveyard (Failed Experiments & Hard Rules)

* **❌ 5-Step Onboarding:** Do not ask for user goals, location, batch year, and resume at `/start`. It produced a 50% drop-off. Keep `/start` to 2 quick taps (Skills ➔ Experience). Push everything else to `/settings`.
* **❌ Raw Message Hyperlinks:** Never embed raw application URLs in message text. Telegram bypasses the bot backend. Always use inline buttons routed through `/r/{job_id}`.
* **❌ Free Credits on Mass Trials:** Never bundle free human/API-costly credits (HR lookups, resume reviews) into free mass trials. Trials should only grant automated bot features.
* **❌ Pipe `|` Separators & `Not Disclosed` Clutter:** Do not dump pipe-separated database text into job cards. Use clean Unicode bullets `•` and omit undisclosed salaries to keep cards tight and mobile-friendly.

---

## 5. Coding Standards & Terminal Execution

1. **Strict Asynchronous Code:** Use `async`/`await` across all database (`asyncpg`), HTTP (`httpx`), and Telegram handlers. Never use blocking `requests` or `time.sleep()`.
2. **Windows PowerShell Encoding:** When running test scripts in PowerShell, always prepend:
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & '.\venv\Scripts\python.exe' -c "..."
   ```
3. **No Em-Dashes in Telegram Strings:** Never introduce em-dashes (`—`) or en-dashes (`–`) into bot messages. Use clean standard dashes (`-` escaped as `\\-`) or colons.
4. **Multi-Tenant Safety:** Every user-facing handler must obtain `bot_id = context.bot_data.get('bot_id', 1)` and scope queries accordingly.
