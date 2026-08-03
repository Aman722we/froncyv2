# FroncyBot - Upcoming Tasks & Features

This file tracks the upcoming features, bug fixes, and improvements that need to be implemented.

## 🐛 Bug Fixes
- [x] **"Mark as Applied" Sync Issue:** When clicking "Mark as Applied", the bot says "You have already tracked this job", but the job does not appear in the "My Applications" view.
- [x] **Job Detail UI Width:** Add a long horizontal line to artificially widen the message bubble.
- [x] **Trial Expiration Tracking:** Added automated nightly CRON job to downgrade expired trials to the 'free' plan so analytics numbers remain accurate.

## 🚀 New Features & Improvements
- [x] **ATS-Friendly Resume Generator:** Generates perfectly formatted LaTeX PDFs customized specifically to the job description without hallucinating new skills.
- [x] **Test/Staging Variant of FroncyBot:** Created a `develop` branch workflow to test features safely before deploying to production (`main`).
- [x] **Broadcast Command:** Added `/broadcast` command to message all onboarded users simultaneously.
- [x] **Duplicate Job Prevention:** Prevent sending the same job to a user twice (`seen_jobs` logic).
- [x] **Retention Features:** Added Evening Digest, Friday Scorecard, and 24-hour freshness FOMO headers to Daily Feeds.

## 📝 Backlog / Ideas
- [ ] **Save the generated things:** Save the generated cover letter, ats resume, and whole apply success kit  so the use can find them later.
- [ ] **Conversational correction for resume generator:** Allow users to chat with the bot to make manual edits to the generated ATS resume.
- [ ] **Apply Success Kit button:** A bundle (Cover letter, cold email, resume, interview prep) generated in one click.
- [ ] **Apply smart button:**               
      Imagine this

Someone opens this job.

Frontend Engineer
VectorShift

They press

🚀 Apply Smart

Then

Step 1
Generate ATS Resume
Done.

Step 2
Generate Cover Letter
Done.

Step 3
Message Hiring Team
👤 Founder
LinkedIn
Email

Generate LinkedIn DM
Generate Cold Email
Done.

Step 4
Application Tracked
Follow-up reminder set for 3 days.

Finished.

- [ ] **Database Backup:** Automate backing up the PostgreSQL database using Cloudflare storage or AWS S3.
- [ ] **Tackle Expired Jobs:** Implement a system or cron job to automatically detect and prune expired jobs from the manual job board.
- [ ] **Remove button spinner suppressor:** Adjust UI logic to properly handle telegram button loading states.
- [ ] **Help Command Update:** Update `/help` command to explicitly direct users to message `FroncySupport` with issues.
- [ ] **Add linter and tests on github:** to catch bugs before release.
- [ ] **CodeRabbit:** try to find any good substitute of code rabbit.
- [ ] **Advanced Outreach:** Support parsing multiple `👤` contacts per job and generating outreach templates for all of them (e.g., both Founder and HR).
- [ ] **LLM Cost & Speed Optimization:** Split Apply Smart tasks between Llama 3.1 70B (ATS Resume, Cover Letter) and Llama 3.1 8B (Cold Email, LinkedIn DM) to improve concurrency and reduce API limits.
- [ ] **Remove Experience Limitation:** Modify the `min_yoe` filtering to allow all frontend jobs regardless of YoE, so more jobs can be matched to all users.
## 📊 Analytics Backlog
- [x] **Daily Active Users / Feed Openers:** Tracking users who explicitly check their feed.
- [ ] **Job Link Click Tracking:** Track users who clicked at least one job application link today (closer to core value than simple logins).