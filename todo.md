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
- [ ] **Conversational correction for resume generator:** Allow users to chat with the bot to make manual edits to the generated ATS resume.
- [ ] **Apply Success Kit button:** A bundle (Cover letter, cold email, resume, interview prep) generated in one click.
- [ ] **Database Backup:** Automate backing up the PostgreSQL database using Cloudflare storage or AWS S3.
- [ ] **Tackle Expired Jobs:** Implement a system or cron job to automatically detect and prune expired jobs from the manual job board.
- [ ] **Remove button spinner suppressor:** Adjust UI logic to properly handle telegram button loading states.
- [ ] **Help Command Update:** Update `/help` command to explicitly direct users to message `FroncySupport` with issues.

## 📊 Analytics Backlog
- [x] **Daily Active Users / Feed Openers:** Tracking users who explicitly check their feed.
- [ ] **Job Link Click Tracking:** Track users who clicked at least one job application link today (closer to core value than simple logins).