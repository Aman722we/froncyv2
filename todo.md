# FroncyBot - Upcoming Tasks & Features

This file tracks the upcoming features, bug fixes, and improvements that need to be implemented.

## 🐛 Bug Fixes
- [ ] **"Mark as Applied" Sync Issue:** When clicking "Mark as Applied", the bot says "You have already tracked this job", but the job does not appear in the "My Applications" view. Need to trace the DB save logic and the tracker fetch logic to find the mismatch.
- [ ] **Job Detail UI Width:** After removing the raw job URL from the job detail message, the Telegram message bubble became too thin/narrow. **Fix:** Add a long horizontal line (e.g., `─────────────────────────`) to artificially widen the message bubble and improve readability.

## 🚀 New Features & Improvements
- [ ] **Duplicate Job Prevention Algorithm:** Verify or implement a system to ensure that jobs are never sent to the same user more than once (e.g., keeping track of `seen_jobs` or filtering out jobs they've already received in previous feeds).

## 📝 Backlog / Ideas
- [ ] 
