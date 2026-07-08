# FroncyBot Product & Growth Learnings

This document is a living record of the critical lessons we have learned while building, marketing, and iterating on FroncyBot. Documenting these ensures we don't repeat mistakes and continue doubling down on what actually works.

---

## 1. UX & Onboarding (Friction Kills Conversion)
**The Problem:** We originally built a comprehensive 5-step onboarding flow (Welcome message ➔ Skills ➔ Location ➔ Batch Year (typing) ➔ Resume Upload). Despite having users join, we were seeing a massive **~45-50% drop-off rate** before users even saw a single job.

**The Solution:** We ruthlessly cut friction. We realized every extra click loses users.
*   We completely ripped out the decorative Welcome banner and "Actively Hunting vs Exploring" questions.
*   We removed manual typing (Batch Year) and optional steps (Location, Resume).
*   **The New Flow:** `/start` ➔ Instantly pick Skills (1 click) ➔ Pick Experience (1 click) ➔ Done.

**The Result:** Drop-off plummeted to **~5-10%**. 
**Core Learning:** In a Telegram bot, speed is everything. Get the user to the core value (seeing jobs) as fast as humanly possible. Ask for extra details (like Resume or Location) *later* in the Settings menu when they are already hooked.

---

## 2. Analytics & Tracking (Enforcing the Funnel)
**The Problem:** Our job link click analytics were showing `0` or `1` even when we knew users were clicking links. 
**The Cause:** We had raw URLs printed as blue hyperlinks directly in the text of the job feed and job detail messages. When a user clicked a raw text link, Telegram opened the browser directly, completely bypassing our backend tracker.

**The Solution:** We removed *all* raw hyperlinks from the message bodies. We forced users to click the `🔗 Open Link` inline keyboard button below the message. 
**Core Learning:** If you want to track an action, you must force the user through a chokepoint (like an inline button) that pings your server (`/r/{job_id}`) before sending them to their final destination. Never give them a direct backdoor if you need the data.

---

## 3. Platform Risk & Architecture (Telegram Dependency)
**The Problem:** Building a business entirely on Telegram means if Telegram bans or deletes the bot (which happens to legit bots sometimes), you lose your entire communication channel with your users.
**The Solution:** 
*   We ensured our PostgreSQL database is 100% independent. User data is tied to `telegram_id`, not the bot itself.
*   We created a disaster recovery playbook (see `security-and-recovery-playbook.md`).
*   We learned the importance of routing marketing links through a custom domain (`getfroncy.com`) via Cloudflare so we can dynamically swap out the bot URL if needed.
*   **Next Step to implement:** Create an official Telegram Channel and collect user emails as a backup communication method.

---

## 4. Product Strategy & Perceived Value (The "Broken" Loader)
**The Problem:** Our AI Cover Letter generation was taking ~60-70 seconds because it uses a massive, high-quality 70B parameter model. Users thought the bot was broken because it just sat there frozen.
**The Solution:** Instead of trying to make the impossible happen (speeding up a 70B model), we fixed the *perception* of time. We implemented a dynamic, async loader that sends status updates every few seconds ("Analyzing job...", "Scanning resume...", "Writing..."). 
**Core Learning:** Users will wait for high-quality results if you communicate with them. A 60-second wait is unacceptable if the screen is frozen, but perfectly acceptable if they see the bot actively "working" for them.

---

## 5. AI Hallucinations vs. Strict Constraints (The Resume Generator)
**The Problem:** When generating ATS-friendly resumes, giving an LLM free rein to rewrite a resume resulted in massive hallucinations—inventing skills the user didn't have and ruining the formatting.
**The Solution:** We moved away from having the LLM "write a resume" and instead used a "Diff & Patch" architecture combined with **LaTeX**. We pass the user's base resume as a JSON structure, ask the AI *only* for structural updates, and compile it dynamically into a highly rigid LaTeX template.
**Core Learning:** Never trust an LLM to generate unstructured output for a high-stakes document like a resume. Constrain its output to specific JSON fields (like `MissingKeywords` or `SummaryTweaks`) and use traditional programmatic tools (LaTeX) to handle the formatting.

---

## 6. The Danger of "Direct to Main" Deployments
**The Problem:** We were developing complex features (like the Resume Generator) and fixing bugs on the main branch simultaneously. During a git merge, a single `import asyncio` line was lost, instantly crashing the entire bot for all users upon deployment to Railway.
**The Solution:** We established a strict two-environment pipeline using a separate `@FroncyTestBot` tied to a `develop` branch.
**Core Learning:** No matter how small the fix, AI and humans alike make mistakes during Git merges. The only way to protect users is to test in a sandbox first. In the future, we must implement automated Linters on GitHub to catch `NameError` bugs before they deploy.
