# FroncyBot — Complete Feature List & Functionality Details

FroncyBot (formerly Applixy) is a fully autonomous, AI-powered Telegram bot designed exclusively to drastically improve the job hunting experience for frontend developers and freshers. Below is a comprehensive breakdown of all the features and systems built into the MVP.

---

## 1. High-Conversion Onboarding Flow
**How it works:**
- When a user types `/start`, they are guided through a gamified, 4-step onboarding flow.
- **Visual Progress Bars:** Users see a real-time progress indicator (e.g., `[🟢🟢⚪⚪] Step 2 of 4`) which psychologically reduces form abandonment.
- Users select their core skills (React, Vue, Typescript, etc.), location preference, and graduation batch year.
- **Resume Parsing:** Users are prompted to upload their resume (PDF). The bot uses specialized APIs to extract the text and permanently save it to their profile.
- **Admin Notifications:** The bot instantly alerts the admin via a private message whenever a user starts onboarding and when they complete it.

## 2. Smart Nudge System & Funnel Recovery
**How it works:**
- A custom script (`nudge_users.py`) queries the PostgreSQL database for users who typed `/start` but abandoned the flow before finishing setup.
- It sends a highly personalized, rate-limited message reminding them they are "one step away" from unlocking AI cover letters and job alerts.

## 3. Manual Job Curation (Admin Panel)
**How it works:**
- Admins can use the hidden `/addjob` command to manually inject high-quality, curated jobs directly into the database.
- The bot parses the admin's copy-pasted text (including emojis) to extract the salary, YOE, location, and job type.
- Manually curated jobs bypass standard scraping limits and guarantee premium quality for the users.

## 4. Smart Job Scoring & Matching Engine
**How it works:**
- Instead of showing random jobs, FroncyBot calculates a personalized **Match Score (0-100%)** for every job against the user's specific profile.
- The algorithm uses a highly optimized mathematical model that prioritizes:
  - **Skills Match:** Cross-references user skills with job requirements.
  - **Experience Fit:** Ensures 0-1 YOE jobs are perfectly matched to freshers.
  - **Recency:** Decays over time so users only see fresh listings.

## 5. AI Cover Letter Generation
**How it works:**
- When a user views a job, they can click "Generate Cover Letter".
- The bot connects to an advanced LLM (LLaMA 3.1 70B via NVIDIA NIM/Groq).
- It injects the user's previously saved **Resume Text** and the **Target Job Description** into a highly engineered prompt.
- The AI outputs a tailored, highly persuasive, ATS-friendly cover letter that highlights exactly why the candidate is a fit for the role.

## 6. On-the-fly ATS Resume Analysis
**How it works:**
- Users can click "ATS Check" on any job.
- The AI compares their saved resume against the job description.
- It returns an actionable report: A match percentage, a list of "Missing Keywords", and specific tweaks the user should make to their resume before applying.

## 7. Dynamic Subscription & Pricing Engine
**How it works:**
- **Tiered Plans:** The bot supports Free, Pro Trial, and Pro tiers.
- **3-Day Automatic Trials:** Every new user who finishes onboarding is instantly granted a 3-day Pro trial with full access to ATS checks and Cover Letters.
- **Usage Limits:** Limits are dynamically enforced on premium features (e.g., Free = 1 Cover Letter/day, Pro = Unlimited).
- **Early Adopter Pricing:** A built-in scarcity engine tracks the first 200 slots. It offers early adopters a ₹199/month rate, before falling back to the standard ₹499/month rate.
- **Razorpay Integration & Webhooks:** A FastAPI server handles recurring Razorpay subscriptions via cryptographic webhooks, automatically upgrading users in the DB.

## 8. Viral Referral System
**How it works:**
- Users can generate a unique referral link.
- When a new user clicks the link and completes onboarding, the system automatically detects the referrer.
- The referrer is instantly rewarded with bonus Pro days, and the bot sends them a congratulatory notification.

## 9. Advanced Analytics Dashboard
**How it works:**
- Admins can type `/analytics` to view a comprehensive real-time dashboard of the entire business.
- Tracks the complete funnel: Total Registered -> Completed Setup -> Uploaded Resume -> Deleted Accounts.
- Tracks financial health: Active Free users, Active Trials, and Paying Pro users.
- Tracks active job listings and day/week growth metrics.

## 10. Global Crash Alert System (Disaster Recovery)
**How it works:**
- FroncyBot includes a global error handler that intercepts any uncaught exceptions (e.g., `BadRequest`, API timeouts, Database failures).
- Instead of silently failing, the bot immediately sends a `❌ CRASH ALERT ❌` message to the admin.
- The alert includes the exact stack trace, the module where it failed, and the specific user context, allowing for instant debugging before users are affected.

## 11. ATS-Friendly Resume Generator
**How it works:**
- Users can click "Generate ATS Resume" on a job listing.
- The bot takes their original saved resume and the target job description, generating a highly optimized, tailored resume.
- Uses LaTeX to compile a professional, ATS-parseable PDF on the fly.
- Uses a diff-patch architecture to ensure the AI does not hallucinate false skills or change the layout unexpectedly.

## 12. Retention & FOMO Features
**How it works:**
- **Daily Feed Freshness Header:** Injects a "🔔 +X new jobs added in the last 24 hours" header to create FOMO and encourage daily checks.
- **Evening Digest:** A 6:30 PM automated alert reminding users of jobs they saved but haven't applied to yet.
- **Friday Scorecard:** A weekly summary sent on Fridays detailing how many jobs they viewed, ATS checks they ran, and cover letters they generated to keep them motivated.

## 13. Staging & Testing Pipeline
**How it works:**
- The repository follows a two-branch system (`main` for production, `develop` for testing).
- A separate Telegram Test Bot (`@FroncyTestBot`) is hooked up to the `develop` branch, allowing the admins to safely test new AI features without breaking the production bot for active users.

---
*Built with Python, python-telegram-bot (v20+), asyncpg (PostgreSQL), FastAPI, Razorpay, and LLaMA 3.1.*
