# ApplixyBot — Complete Feature List & Functionality Details

ApplixyBot is a fully autonomous, AI-powered Telegram bot designed to drastically improve the job hunting experience for web developers. Below is a comprehensive breakdown of all the features and systems built into the MVP.

---

## 1. Onboarding & Profile Management
**How it works:**
- When a user types `/start`, they are guided through an interactive onboarding flow.
- Users select their core skills (React, Node.js, Python, etc.), location preference (Remote, India, Both), Years of Experience (YOE), and graduation batch.
- They set a preferred **Daily Alert Time** for their customized job feed.
- **Resume Parsing:** Users are prompted to upload their resume (PDF). The bot uses specialized APIs to extract the text and permanently save it to their profile. This powers all downstream AI features without the user ever needing to re-upload it.

## 3. Manual Job Curation (Admin Panel)
**How it works:**
- Admins can use the hidden `/addjob` command to manually inject high-quality, curated jobs directly into the database.
- The bot parses the admin's copy-pasted text (including emojis) to extract the salary, YOE, skills, and posted date.
- Manually curated jobs bypass standard scraping limits and are guaranteed to be shown to users.

## 4. Smart Job Scoring & Matching Engine
**How it works:**
- Instead of showing random jobs, ApplixyBot calculates a personalized **Match Score (0-100%)** for every job against the user's specific profile.
- The algorithm uses a highly optimized 5-factor mathematical model:
  - **Skills Match (40%):** Cross-references user skills with job requirements.
  - **Experience Fit (25%):** Heavily penalizes experience gaps (the #1 reason for early rejection).
  - **Recency (15%):** Decays over 30 days. Jobs ≤ 3 days old get maximum points.
  - **Role Preference (10%):** Tiebreaker for alignment with frontend/backend goals.
  - **Salary Quality (10%):** Smart parsing mechanism that rewards jobs with disclosed salaries (especially high-value markers like $, €, or high LPA) and penalizes "Not Disclosed" listings.

## 5. Daily Feed & Browse Jobs
**How it works:**
- **Daily Feed:** At the user's preferred time (e.g., 09:00 IST), the bot automatically sends a carousel of the top 12 best-matching jobs. Jobs with high salaries and perfect YOE/Skill matches are mathematically forced to the top.
- **Browse Jobs:** Users can manually trigger a search anytime to view the absolute best matches currently in the database, beautifully formatted in Markdown with direct apply links.

## 6. AI Cover Letter Generation
**How it works:**
- When a user views a job, they can click "Generate Cover Letter".
- The bot connects to an advanced LLM (LLaMA 3.1 70B via NVIDIA NIM/Groq).
- It injects the user's previously saved **Resume Text** and the **Target Job Description** into a highly engineered prompt.
- The AI outputs a tailored, highly persuasive, ATS-friendly cover letter that highlights exactly why the candidate is a fit for the role.

## 7. On-the-fly ATS Resume Analysis
**How it works:**
- Users can click "ATS Check" on any job.
- The AI compares their saved resume against the job description.
- It returns an actionable report: A match percentage, a list of "Missing Keywords", and 2-3 specific bullet-point tweaks the user should make to their resume before applying to get past automated filters.

## 8. Kanban-Style Application Tracking
**How it works:**
- Users can click "Save Job" to add it to their personal tracker.
- Using inline keyboards, users can move jobs through a pipeline: `Saved ➡️ Applied ➡️ Interview ➡️ Rejected/Offer`.
- **Follow-up Reminders:** When a user marks a job as `Applied`, the bot schedules an automatic background task. Exactly 7 days later, it sends a push notification reminding the user to follow up with the recruiter.

## 9. Dynamic Subscription System & Payments
**How it works:**
- **Tiered Plans:** The bot supports Free, Pro Trial (3 days), and Pro tiers.
- **Usage Limits:** Limits are dynamically enforced on premium features (e.g., Free = 1 Cover Letter/day, Pro = 10 Cover Letters/day).
- **Early Adopter Pricing:** A built-in scarcity engine tracks the first 200 slots. It offers early adopters a ₹199/month rate, before automatically falling back to the standard ₹499/month rate.
- **Razorpay Integration:** The bot automatically connects to the Razorpay API to dynamically generate recurring subscription plans on the fly.
- **Asynchronous Webhooks:** A FastAPI server runs alongside the Telegram bot. When a user pays (or cancels), Razorpay sends a webhook. The server instantly verifies the cryptographic signature and silently upgrades or downgrades the user in the database, sending them a congratulatory push notification.

## 10. Weekly Summary & Analytics
**How it works:**
- Every weekend, the bot aggregates the user's activity.
- It generates a summary report: "You applied to X jobs, generated Y cover letters, and have Z interviews coming up."
- It utilizes psychological gamification to encourage consistency in the job hunt.

---
*Built with Python, python-telegram-bot (v20+), asyncpg (PostgreSQL), FastAPI, Razorpay, and LLaMA 3.1.*
