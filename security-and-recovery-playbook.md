# FroncyBot Security & Disaster Recovery Playbook

This document outlines the architectural safeguards and emergency procedures to ensure FroncyBot survives platform risks (e.g., Telegram deleting or banning the bot). 

As the bot grows and new features are added, this file must be updated to reflect new protection strategies.

---

## The Core Safeguard: Data Independence
The most critical protection is already in place: **The Database is independent of Telegram.**
All user profiles, resumes, skills, match scores, and analytics are stored in a PostgreSQL database hosted securely (on Railway/Supabase). 

Because Telegram users have a universal `telegram_id` that never changes, their identity is tied to their *Telegram account*, not the bot. If the bot is deleted, **no user data is lost.**

---

## 🛡️ Preventative Measures (To implement as we scale)

### 1. Build an Official Telegram Channel (The Backup Comms)
*   **What:** Create an official channel (e.g., `@FroncyOfficial`).
*   **Why:** Telegram rarely deletes channels, even if bots trigger automated spam filters.
*   **Action:** Add a "📢 Join Official Channel" button in the bot's Main Menu. If the bot ever goes down, an announcement can be posted in the channel: *"Our bot is down, please use our new bot at @FroncyV2Bot"*, allowing users to instantly migrate.

### 2. Multi-Channel Contact (Email Collection)
*   **What:** Collect user emails as an optional premium feature (e.g., "Enter email for weekly job digests").
*   **Why:** If Telegram completely bans the project, having an email list is the ultimate safety net. You can email your entire user base with a link to a new bot or a web app.

### 3. Smart Link Routing (Cloudflare & Custom Domains)
*   **What:** Never use direct `t.me/FroncyJobsBot` links in marketing, ads, or LinkedIn posts. Route everything through a custom domain (e.g., `froncy.com/bot` or `linktr.ee`) managed by Cloudflare.
*   **Why:** If the bot gets banned, all existing ads and links on the internet will break. By routing through Cloudflare, if a ban occurs, you simply update the Cloudflare redirect rules to point `froncy.com/bot` to the new bot handle (`t.me/FroncyV2Bot`). New users will never know the difference.

---

## 🚨 Emergency Recovery Procedure (If the bot is deleted today)

If the Telegram handle `@FroncyJobsBot` is suddenly banned or deleted, follow these steps. **Expected downtime: < 5 minutes.**

1. **Create a New Bot:**
   * Open Telegram and message `@BotFather`.
   * Create a new bot (e.g., `@FroncyAppBot`).
   * Copy the new **API Token**.

2. **Update the Server:**
   * Go to the Railway dashboard (or wherever the backend is hosted).
   * Open the Environment Variables for the production deployment.
   * Replace the old `BOT_TOKEN` with the new API token.
   * Restart the server.

3. **Update Webhooks (If applicable):**
   * If running in webhook mode, ensure the `WEBHOOK_URL` is still correctly pointing to your server domain, and the bot registers the new webhook path automatically on startup.

4. **Migrate Users:**
   * Post an announcement in the Official Telegram Channel.
   * Send an email blast (if email collection is active).
   * Update Cloudflare/custom domain redirects to point to the new `@FroncyAppBot` handle.

**The Result:** When an existing user clicks the link to the new bot and hits `/start`, the database will instantly recognize their `telegram_id`. All their data (Pro trials, saved jobs, resumes) will perfectly resume exactly as they left it.
