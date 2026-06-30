# 🧠 FroncyBot Project Brain & Handoff

**IMPORTANT INSTRUCTION FOR AI AGENTS:** 
If you are reading this, you are a new AI agent (or a new chat session) working on FroncyBot. **Read this entire document before writing any code.** It contains the project's history, architectural decisions, and critical lessons learned from failed experiments that are not visible in the source code.

---

## 1. Project Vision & Identity
*   **Name:** FroncyBot (`@FroncyJobsBot` / `getfroncy.com`)
*   **Target Audience:** Frontend Developers (specifically Freshers / 0-1 Years Experience).
*   **Core Value Proposition:** A Telegram bot that curates highly relevant frontend jobs, calculates ATS match scores against the user's resume, and generates tailored cover letters to help them land interviews, not just apply to more jobs.
*   **Monetization:** Freemium model. 3-Day Pro Trial (no card required). Pro gives unlimited jobs, 10 cover letters/day, and full ATS breakdowns.

---

## 2. Core Architectural Decisions
*   **Platform:** Telegram Bot (Python / `python-telegram-bot` v20+ async).
*   **Database:** PostgreSQL (hosted on Railway). We use `asyncpg` for high-performance connection pooling.
*   **AI Models:** NVIDIA NIM (Llama 3 70B) for high-quality cover letters. We prioritize quality over speed for generation.
*   **Data Independence:** The database uses `telegram_id` as the primary key. User data is strictly isolated from the bot instance. If the Telegram bot is banned, user data is perfectly preserved.

---

## 3. Historical Incidents & Safeguards
### The Telegram Deletion Incident
*   **What happened:** In the early days, the original bot account was deleted by Telegram without warning. 
*   **The Safeguard:** We never market the direct `t.me` link. We market `getfroncy.com` (routed through Cloudflare). If the bot gets banned again, we spin up a new bot token, update the backend, and change the Cloudflare redirect. The database seamlessly recognizes returning users via their `telegram_id`.

---

## 4. The Graveyard (Failed Experiments & Lessons)
*DO NOT REPEAT THESE MISTAKES.*

### ❌ Failed Experiment 1: The 5-Step Onboarding
*   **What we tried:** We asked users for their intent (Hunting/Exploring), Skills, Location, Batch Year (which required typing), and Resume upload immediately upon clicking `/start`.
*   **The Result:** A catastrophic **50% drop-off rate**. Users quit before seeing a single job.
*   **The Fix:** We ripped it down to 2 steps (Skills ➔ Experience). Drop-off fell to 5-10%. 
*   **Rule for AI:** NEVER add friction to the `/start` onboarding flow. Push secondary settings (Resume, Location) to the `/settings` menu.

### ❌ Failed Experiment 2: Raw Hyperlinks for Job Tracking
*   **What we tried:** We put the job application URL as a raw, clickable blue hyperlink directly in the message text.
*   **The Result:** Telegram opened the browser directly. Our backend `link_clicks` analytics permanently showed `0`.
*   **The Fix:** We completely removed hyperlinks from message bodies. We force users to click an `🔗 Open Link` inline keyboard button, which routes them through our `main.py` FastApi redirector (`/r/{job_id}`) to log the click before sending them to the job.
*   **Rule for AI:** NEVER put direct URLs in message text if we need to track intent. Always use inline buttons + the redirector.

### ❌ Failed Experiment 3: Silent AI Generation
*   **What we tried:** Generating a high-quality Llama 3 70B cover letter took 60-70 seconds. The bot sat in silence while processing.
*   **The Result:** Users thought the bot was broken and abandoned the process.
*   **The Fix:** Implemented a dynamic async loader (`"Analyzing job..." ➔ "Scanning resume..." ➔ "Writing..."`).
*   **Rule for AI:** Any backend process taking longer than 3 seconds MUST have a visible, updating loading state for the user.

---

## 5. Coding Standards & AI Rules
1. **Performance:** Always use `async`/`await` for DB calls (`asyncpg`) and Telegram API calls. Never use blocking `requests` or `time.sleep()`.
2. **UI Real Estate:** Mobile screens are small. Keep message text concise. We previously had a bug where the `[Step 1 of 2]` indicator was pushed off-screen because the text was too long.
3. **Analytics First:** Every major action (cover letter copied, job link clicked, ATS check run) must be logged in the `ai_usage_logs` or `link_clicks` tables. 

---
*End of Brain. If you have ingested this, acknowledge it and ask the user what they want to build today.*
