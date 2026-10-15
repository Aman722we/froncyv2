# 🛠️ Froncy Admin Commands Reference Guide

> **Admin Access:** All admin commands are strictly protected and only accessible by `ADMIN_TELEGRAM_ID`. Unauthorized users are silently ignored or rejected.

---

## ⚡ Force Ping / Job Alert Testing

### `/pingjob <user_id> <job_id>`
* **Description:** Forcefully triggers an instant job alert to any user for any specific job stored in `manual_jobs`, bypassing freshness and match filters. Computes the user's live match score and delivers the full alert with Apply & HR Contact buttons.
* **Usage:**
  ```text
  /pingjob 7963303313 105
  ```
* **Rendered Format:**
  > 🚨 **NEW JOB ALERT**  
  > **Integration Developer** @ **Thoughtworks**  
  > 🟢 **Suitable for your profile (0–2 YOE)**  
  > 💡 **Role Category:** Backend & API Development  
  > 📍 Bengaluru, India (On-site)  
  > 💰 ₹12 - ₹18 LPA  
  > 🛠️ **Key Skills:** Java, REST APIs, SQL  
  > 🎯 **88% Match**  
  >  
  > ⚡ Direct from company careers  
  > 🕐 Posted 2h ago  
  > `[ 🔗 Apply Now ]` `[ 👤 Request HR Details ]`

---

## 📊 1. Job Ingestion & Career Scraper Management

### `/jobdashboard` (or `/jobstats`)
* **Description:** Real-time 24-hour job intelligence dashboard. Displays jobs published by monitored companies in the rolling last 24 hours (`posted_at >= NOW() - INTERVAL '24 hours'`), with:
  - Total fresh published jobs
  - Active hiring companies & sources monitored
  - Experience level breakdown (0 YOE, 1+, 2+, 3+, 4+, 5+) and discrete buckets
  - Seniority ratio (Senior vs Junior/Mid)
  - Desired Role Streams (Frontend, Backend, Fullstack, DevOps, Mobile, Data/AI)
  - Top hiring companies and the 5 latest published roles.
* **Usage:**
  ```text
  /jobdashboard
  ```

### `/syncnow [source_id]`
* **Description:** Manually triggers the career page sync engine immediately. If `source_id` is passed, syncs only that specific company; if omitted, syncs all active career sources.
* **Usage:**
  ```text
  /syncnow          (Syncs all configured company boards)
  /syncnow 12       (Syncs only source ID 12)
  ```

### `/addsource <provider> <board_token> <Company Name>`
* **Description:** Adds a new company career board to the automated 15-minute polling engine.
* **Supported Providers:** `GREENHOUSE`, `LEVER`, `ASHBY`
* **Usage:**
  ```text
  /addsource GREENHOUSE gatherai Gather AI
  /addsource LEVER notion Notion
  /addsource ASHBY linear Linear
  ```

### `/bulkadd <provider>\n<token> <Company Name>...`
* **Description:** Bulk adds dozens or hundreds of career sources at once in a single message.
* **Usage:**
  ```text
  /bulkadd GREENHOUSE
  stripe Stripe
  figma Figma
  datadog Datadog
  ```

### `/listsources`
* **Description:** Lists all configured company career sources with their IDs, active/inactive status (🟢/🔴), provider, board token, last check time, and any HTTP error details.
* **Usage:**
  ```text
  /listsources
  ```

### `/delsource <source_id>`
* **Description:** Deactivates or removes a career source from being monitored.
* **Usage:**
  ```text
  /delsource 14
  ```

### `/addjob`
* **Description:** Starts an interactive multi-step wizard to manually add a job into `manual_jobs` with structured format (Title, company, link, location/remote, YOE, skills, hiring manager details).
* **Usage:**
  ```text
  /addjob
  ```

---

## 💼 2. Monetization & Service Request Queue

### `/pending`
* **Description:** Displays all pending user requests requiring admin action:
  - **HR Contact Requests** (Users requesting direct HR/recruiter emails & LinkedIn)
  - **Resume Review Submissions** (Users requesting human resume review)
* **Usage:**
  ```text
  /pending
  ```

### `/completerequest <req_id> <resolution_text>`
* **Description:** Fulfills a pending user request by request ID. Automatically updates the database and sends the user a formatted message with the HR contact card or resume review feedback.
* **Usage:**
  ```text
  /completerequest 42 Priya Sharma | Senior Recruiter | priya@company.com | https://linkedin.com/in/priya
  ```

### `/refundrequest <user_id>`
* **Description:** Views or handles refund requests and Razorpay subscription cancellations for a given user.
* **Usage:**
  ```text
  /refundrequest 7963303313
  ```

### `/masstrial <days> [all|active|expired]`
* **Description:** Extends trial days for multiple users simultaneously (great for marketing campaigns or service compensation).
* **Usage:**
  ```text
  /masstrial 3 all       (Gives 3 extra trial days to all onboarded users)
  /masstrial 7 expired   (Re-engages expired trial users with 7 more days)
  ```

---

## 👥 3. User CRM & Messaging

### `/send <user_id> <message>`
* **Description:** Sends a direct message from the bot to a specific user (one-on-one admin support).
* **Usage:**
  ```text
  /send 7963303313 Hello! Your HR request has been fulfilled. Let us know if you need anything else.
  ```

### `/broadcast <message>`
* **Description:** Broadcasts an announcement or alert to all active onboarded users.
* **Usage:**
  ```text
  /broadcast 🚀 We just added 50 new tech companies to our daily careers scanner! Check your /jobs feed now.
  ```

### `/users`
* **Description:** Paginated view of all registered users with their Telegram ID, username, plan tier, and onboarding status.
* **Usage:**
  ```text
  /users
  ```

### `/user <user_id>`
* **Description:** Deep-dive inspects a user profile: skills, experience level, stream, effective plan, trial expiry, total applications, and bot ID.
* **Usage:**
  ```text
  /user 7963303313
  ```

### `/deletedusers`
* **Description:** Lists users who blocked, stopped, or deleted the bot.
* **Usage:**
  ```text
  /deletedusers
  ```

---

## 📄 4. Concierge Resume Service & Fixes

### `/badresumes`
* **Description:** Lists users whose resume PDFs failed OCR/text parsing so admin can intervene.
* **Usage:**
  ```text
  /badresumes
  ```

### `/getresume <user_id>`
* **Description:** Downloads and forwards the user's uploaded resume PDF to the admin for manual inspection.
* **Usage:**
  ```text
  /getresume 7963303313
  ```

### `/fixresume <user_id> <skills> | <yoe> | <role>`
* **Description:** Manually overrides and repairs a user's extracted skills, experience level, and role preference after reviewing their resume.
* **Usage:**
  ```text
  /fixresume 7963303313 Python, React, PostgreSQL | 1 | fullstack
  ```

---

## 📈 5. SaaS Analytics & Growth

### `/analytics`
* **Description:** Comprehensive SaaS health metrics:
  - Total users, active users, churn rate
  - Free vs Trial vs Pro plan breakdown
  - Daily active users (DAU) & weekly engagement
  - Application conversion funnel
* **Usage:**
  ```text
  /analytics
  ```

### `/dashboard`
* **Description:** Influencer/Creator partner portal analytics dashboard.
* **Usage:**
  ```text
  /dashboard
  ```

### `/creator`
* **Description:** Creator referral overview and commission breakdown.
* **Usage:**
  ```text
  /creator
  ```

### `/links`
* **Description:** Creator referral links and click/signup attribution stats.
* **Usage:**
  ```text
  /links
  ```

---

## 🤖 6. Multi-Tenant Bot Network

### `/addbot <bot_token> <bot_name> <creator_id>`
* **Description:** Deploys a new white-labeled bot instance under a creator/partner while sharing the core backend database and jobs pool.
* **Usage:**
  ```text
  /addbot 123456789:ABCdefGhIJKlmNoPQRstuVWX TechJobsBot 5544332211
  ```

### `/setcreator <user_id> <creator_slug>`
* **Description:** Designates a user as an official creator/affiliate partner with a custom tracking slug.
* **Usage:**
  ```text
  /setcreator 7963303313 code_with_ayush
  ```
