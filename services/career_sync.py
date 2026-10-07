"""
Froncy V2 — Career Page Sync Engine.
Polls active career sources, detects new jobs, stores them,
and triggers the existing notification pipeline.
"""
from datetime import datetime, timezone
from loguru import logger
from db.career_sources import (
    get_active_career_sources, update_source_check, job_already_exists
)
from services.career_fetcher import fetch_jobs_for_source
from db.connection import get_pool


def is_relevant_tech_job(title: str, department: str, location: str) -> bool:
    """
    Gatekeeper function to filter out non-tech roles and non-India/non-Global jobs.
    Saves LLM tokens and DB space.
    """
    title = (title or "").lower()
    dept = (department or "").lower()
    loc = (location or "").lower()

    # 1. Location Filter (Must be India or Global Remote, drop explicitly foreign)
    if loc:
        india_cities = ["india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "gurgaon", 
"noida", "chennai", "kolkata", "remote - ind", "apac", "asia", "global", "anywhere"]
        is_india = any(c in loc for c in india_cities)
        
        # If it doesn't explicitly mention India/Global AND doesn't mention Remote, it's a local foreign job
        if not is_india and "remote" not in loc:
            return False

        # Even if it says "Remote", drop it if it specifically locks to a foreign region and NOT India
        if not is_india:
            import re
            foreign_terms = [
                "us", "usa", "united states", "uk", "united kingdom", "london", "europe", "emea", 
                "amer", "latam", "canada", "australia", "spain", "sweden", "ireland", "germany", 
                "france", "singapore", "poland", "romania", "netherlands", "brazil", "mexico", 
                "colombia", "argentina", "new york", "san francisco", "seattle", "portugal", 
                "lisbon", "japan", "tokyo", "israel", "tel aviv", "dubai", "uae"
            ]
            for term in foreign_terms:
                if re.search(r'\b' + re.escape(term) + r'\b', loc):
                    return False  # Drop explicitly foreign jobs

    # 2. Department / Title Hard Veto (Non-Tech)
    junk_keywords = [
        "sales", "marketing", "account executive", "hr ", "human resources", "recruiter", 
        "finance", "accounting", "legal", "counsel", "customer success", "advocacy", 
        "content", "copywriter", "business development", "payroll", "tax",
        "workplace", "facilities", "executive assistant", "vp ", "chief ",
        "solutions", "solution", "sales engineer", "support", "technical support", "manager", "director"
    ]
    for junk in junk_keywords:
        if junk in title or junk in dept:
            return False

    # 3. Tech Whitelist (Must have at least one)
    tech_keywords = [
        "engineer", "developer", "sde", "programmer", "software", "coder", "architect",
        "data", "ml", "ai", "machine learning", "product", "designer", "ui", "ux",
        "security", "cloud", "sre", "devops", "platform", "backend", "frontend",
        "fullstack", "ios", "android", "mobile", "qa", "test", "systems", "research", "mle"
    ]
    is_tech = any(tech in title for tech in tech_keywords) or any(tech in dept for tech in tech_keywords)
    
    return is_tech


async def _save_career_job(normalized_job: dict, source: dict) -> int | None:
    """
    Save a new career-page job into the manual_jobs table.
    Returns the new job ID, or None if it's a duplicate.
    """
    provider = normalized_job["source_provider"]
    external_id = normalized_job["external_id"]

    # --- GATEKEEPER: Drop useless jobs instantly ---
    if not is_relevant_tech_job(
        normalized_job.get("title"), 
        normalized_job.get("department"), 
        normalized_job.get("location")
    ):
        return None
    # -----------------------------------------------
    
    if await job_already_exists(provider, external_id):
        return None

    # Call LLM to extract skills and min_yoe
    from services.llm_service import extract_job_metadata
    description = normalized_job.get("description") or ""
    metadata = await extract_job_metadata(description)
    extracted_skills = metadata.get("skills", [])
    extracted_min_yoe = metadata.get("min_yoe", 0)

    pool = get_pool()
    async with pool.acquire() as conn:
        now = datetime.now(timezone.utc)
        row = await conn.fetchrow(
            """
            INSERT INTO manual_jobs (
                title, company, url, location,
                job_type, skills, min_yoe, eligible_batches,
                posted_at, is_active, added_by,
                source_type, source_provider, source_external_id,
                first_seen_at, description
            ) VALUES (
                $1, $2, $3, $4,
                'fulltime', $10, $11, '{}',
                $5, TRUE, NULL,
                'CAREER_PAGE', $6, $7,
                $8, $9
            )
            ON CONFLICT (source_provider, source_external_id) WHERE source_external_id IS NOT NULL DO NOTHING
            RETURNING id
            """,
            normalized_job["title"],
            source["company_name"],
            normalized_job["apply_url"] or normalized_job["job_url"],
            normalized_job.get("location"),
            normalized_job.get("published_at") or now,
            provider,
            external_id,
            now,  # first_seen_at is always NOW()
            normalized_job.get("description"),
            extracted_skills,
            extracted_min_yoe
        )
        if row:
            return row["id"]
        return None
async def sync_one_source(source: dict) -> dict:
    """
    Sync a single career source.
    Returns a summary dict: {fetched, new, duplicates, errors}.
    """
    source_id = source["id"]
    company = source["company_name"]
    summary = {"company": company, "fetched": 0, "new": 0, "duplicates": 0, "errors": 0}

    try:
        jobs = await fetch_jobs_for_source(source)
        summary["fetched"] = len(jobs)

        new_job_ids = []
        for job in jobs:
            try:
                new_id = await _save_career_job(job, source)
                if new_id:
                    summary["new"] += 1
                    new_job_ids.append(new_id)
                else:
                    summary["duplicates"] += 1
            except Exception as e:
                logger.warning(f"Error saving job '{job.get('title')}' from {company}: {e}")
                summary["errors"] += 1

        await update_source_check(source_id, success=True)
        
        # Trigger notifications for new jobs
        if new_job_ids:
            await _notify_users_for_new_jobs(new_job_ids)

    except Exception as e:
        error_msg = str(e)[:500]
        logger.error(f"Failed to sync {company}: {error_msg}")
        await update_source_check(source_id, success=False, error=error_msg)
        summary["errors"] += 1

    return summary


async def _notify_users_for_new_jobs(job_ids: list[int]) -> None:
    """
    For each newly discovered career-page job, find matching users
    and send them a Telegram notification using the existing pipeline.
    """
    from services.scheduler import _bot_app
    if not _bot_app:
        logger.warning("Bot app not set — cannot send career page notifications")
        return

    pool = get_pool()
    
    for job_id in job_ids:
        try:
            async with pool.acquire() as conn:
                job_row = await conn.fetchrow(
                    "SELECT * FROM manual_jobs WHERE id = $1",
                    job_id
                )
                if not job_row:
                    continue
                
                job = dict(job_row)
                job["is_manual"] = True

                # Get all onboarded, non-deleted users
                users = await conn.fetch(
                    """
                    SELECT telegram_id, bot_id, skills, location_pref, plan,
                           experience_level, batch_year, role_pref, is_trial, trial_expires_at
                    FROM users
                    WHERE is_onboarded = TRUE
                    AND (is_deleted IS NULL OR is_deleted = FALSE)
                    """
                )

            from utils.messages import compute_manual_job_match, escape_md
            from utils.helpers import get_effective_plan
            from datetime import timedelta

            for user_row in users:
                try:
                    user = dict(user_row)
                    plan = get_effective_plan(user)
                    user["plan"] = plan

                    match = compute_manual_job_match(user, job)
                    score = match.get("score", 0)
                    
                    # Only notify if score >= 50 (meaningful match)
                    if score < 50:
                        continue

                    # Calculate freshness
                    first_seen = job.get("first_seen_at")
                    if first_seen:
                        if first_seen.tzinfo is None:
                            first_seen = first_seen.replace(tzinfo=timezone.utc)
                        mins_ago = int((datetime.now(timezone.utc) - first_seen).total_seconds() / 60)
                        freshness = f"{mins_ago} min ago" if mins_ago < 60 else f"{mins_ago // 60}h ago"
                    else:
                        freshness = "just now"

                    title = escape_md(job.get("title", "New Job"))
                    company = escape_md(job.get("company", "Unknown"))
                    location = escape_md(job.get("location") or "Remote / Global")
                    job_url = job.get("url", "")

                    msg = (
                        f"🚨 *NEW JOB ALERT*\n\n"
                        f"*{title}*\n"
                        f"🏢 {company}\n"
                        f"📍 {location}\n\n"
                        f"🎯 *{score}% match*\n\n"
                        f"⚡ Direct from company careers\n"
                        f"🕐 Detected {escape_md(freshness)}\n"
                        f"🔗 [Apply Now]({job_url})"
                    )

                    from bot_registry import get_app_for_bot_id
                    bot_id = user.get("bot_id", 1)
                    target_app = get_app_for_bot_id(bot_id) or _bot_app
                    
                    await target_app.bot.send_message(
                        chat_id=user["telegram_id"],
                        text=msg,
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True,
                    )

                except Exception as e:
                    logger.warning(f"Failed to notify user {user_row.get('telegram_id')} for job {job_id}: {e}")

        except Exception as e:
            logger.error(f"Failed to process notifications for job_id={job_id}: {e}")


async def run_career_sync() -> list[dict]:
    """
    Main sync runner. Fetches all active sources and syncs them.
    One failing source does NOT stop others.
    Returns a list of per-source summary dicts.
    """
    sources = await get_active_career_sources()
    if not sources:
        logger.info("Career sync: no active sources configured.")
        return []

    logger.info(f"⚡ Career sync starting: {len(sources)} active sources")
    summaries = []

    for source in sources:
        summary = await sync_one_source(source)
        summaries.append(summary)
        logger.info(
            f"  ✓ {source['company_name']}: "
            f"fetched={summary['fetched']}, new={summary['new']}, "
            f"dupes={summary['duplicates']}, errors={summary['errors']}"
        )

    total_new = sum(s["new"] for s in summaries)
    logger.info(f"⚡ Career sync complete. Total new jobs: {total_new}")
    return summaries

