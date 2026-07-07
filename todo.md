# FroncyBot - Upcoming Tasks & Features

This file tracks the upcoming features, bug fixes, and improvements that need to be implemented.

## 🐛 Bug Fixes
- [x] **"Mark as Applied" Sync Issue:** When clicking "Mark as Applied", the bot says "You have already tracked this job", but the job does not appear in the "My Applications" view. Need to trace the DB save logic and the tracker fetch logic to find the mismatch.
- [x] **Job Detail UI Width:** After removing the raw job URL from the job detail message, the Telegram message bubble became too thin/narrow. **Fix:** Add a long horizontal line (e.g., `─────────────────────────`) to artificially widen the message bubble and improve readability.

## 🚀 New Features & Improvements
- [x] **Duplicate Job Prevention Algorithm:** Verify or implement a system to ensure that jobs are never sent to the same user more than once (e.g., keeping track of `seen_jobs` or filtering out jobs they've already received in previous feeds).

## 📝 Backlog / Ideas
- [ ]

## Create a testing varient of FroncyBot : when we add new feature or update the bot if it crahes it offects all the users 


## The metric I would add immediately

You already track:

DAU
WAU
Returning users

Good.

Now add:

Users who opened daily feed today

and

Users who clicked at least one job today

Those are closer to the core value than simple logins.

## BackUp the database useing cloudflare storage

## Create ATS friendly Resume generator

## Create Apply Success Kit button

## Create /braodcast command similar to /send command to send any message to every user togather

## Think how to tackle the expired jobs on the job boards.

## Remove the button spinner supressure 

## On the /help command tell user to message your problem on FroncySupport.

### ADVANCED FEATURES

## conversational correction for resume generator 