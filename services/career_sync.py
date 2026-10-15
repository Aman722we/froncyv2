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

    # Call LLM to extract skills, yoe, salary, workplace, role category, role summary
    from services.llm_service import extract_job_metadata
    description = normalized_job.get("description") or ""
    metadata = await extract_job_metadata(
        job_description=description,
        job_title=normalized_job.get("title", ""),
        location=normalized_job.get("location", "")
    )
    extracted_skills = metadata.get("skills", [])
    extracted_min_yoe = metadata.get("min_yoe", 0)
    extracted_max_yoe = metadata.get("max_yoe")
    extracted_salary = metadata.get("salary") or "Not disclosed"
    extracted_workplace = metadata.get("workplace_type") or "On-site"
    extracted_role_category = metadata.get("role_category") or "Software Engineering"
    extracted_role_summary = metadata.get("role_summary") or ""
    extracted_fresher_friendly = metadata.get("is_fresher_friendly", extracted_min_yoe <= 2)

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
                first_seen_at, description, salary,
                max_yoe, role_category, role_summary, workplace_type, is_fresher_friendly
            ) VALUES (
                $1, $2, $3, $4,
                'fulltime', $10, $11, '{}',
                $5, TRUE, NULL,
                'CAREER_PAGE', $6, $7,
                $8, $9, $12,
                $13, $14, $15, $16, $17
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
            extracted_min_yoe,
            extracted_salary,
            extracted_max_yoe,
            extracted_role_category,
            extracted_role_summary,
            extracted_workplace,
            extracted_fresher_friendly
        )
        if row:
            from db.manual_jobs import invalidate_jobs_cache
            invalidate_jobs_cache()
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
    For each newly discovered career-page job, find matching PRO users
    and send them an instant Telegram notification with the new V2 format.
    
    Free users are skipped here — they receive jobs in their daily digest.
    """
    from services.scheduler import _bot_app
    if not _bot_app:
        logger.warning("Bot app not set — cannot send career page notifications")
        return

    pool = get_pool()
    PRO_PLANS = ("pro", "trial", "proplus", "premium")

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
                
                # IMPORTANT: Trust & Quality Filter
                # If the job was posted more than 24 hours ago, DO NOT send an instant alert.
                # It will still be in the database for daily digests and browsing.
                # This prevents spamming users with old jobs when we first add a new company.
                posted = job.get("posted_at")
                if posted:
                    from datetime import datetime, timezone
                    if posted.tzinfo is None:
                        posted = posted.replace(tzinfo=timezone.utc)
                    hours_ago = (datetime.now(timezone.utc) - posted).total_seconds() / 3600
                    if hours_ago > 24:
                        from loguru import logger
                        logger.info(f"Skipping instant alert for job {job_id} ({job.get('title')}) because it is {hours_ago:.1f} hours old.")
                        continue
                
                job["is_manual"] = True

                # Only fetch Pro users — Free users get jobs in daily digest
                users = await conn.fetch(
                    """
                    SELECT telegram_id, bot_id, skills, location_pref, plan,
                           experience_level, batch_year, role_pref, is_trial, trial_expires_at
                    FROM users
                    WHERE is_onboarded = TRUE
                    AND (is_deleted IS NULL OR is_deleted = FALSE)
                    AND plan IN ('pro', 'trial', 'proplus', 'premium')
                    """
                )

            from utils.messages import compute_manual_job_match, escape_md
            from utils.helpers import get_effective_plan
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton

            for user_row in users:
                try:
                    user = dict(user_row)
                    plan = get_effective_plan(user)
                    user["plan"] = plan

                    # Skip if downgraded (trial expired, etc.)
                    if plan not in PRO_PLANS:
                        continue

                    match = compute_manual_job_match(user, job)
                    score = match.get("score", 0)

                    # Only notify if score >= 50 (meaningful match)
                    if score < 50:
                        continue

                    # Calculate freshness from posted_at (not first_seen_at)
                    posted = job.get("posted_at")
                    if posted:
                        if posted.tzinfo is None:
                            posted = posted.replace(tzinfo=timezone.utc)
                        mins_ago = int((datetime.now(timezone.utc) - posted).total_seconds() / 60)
                        if mins_ago < 0: mins_ago = 0
                        freshness = f"{mins_ago} min ago" if mins_ago < 60 else f"{mins_ago // 60}h ago"
                    else:
                        freshness = "just now"

                    # Build message fields
                    title = escape_md(job.get("title", "New Job"))
                    company = escape_md(job.get("company", "Unknown"))
                    job_url = job.get("url", "")

                    # 1. Experience Suitability Line
                    min_yoe = job.get("min_yoe") or 0
                    max_yoe = job.get("max_yoe")
                    if max_yoe and max_yoe > min_yoe:
                        yoe_label = f"{min_yoe}–{max_yoe} YOE"
                    elif min_yoe == 0:
                        yoe_label = "0–2 YOE"
                    else:
                        yoe_label = f"{min_yoe}+ YOE"

                    # Dynamic profile suitability check
                    user_exp_raw = str(user.get("experience_level", "0")).strip()
                    u_map = {"0": 0, "1": 1, "2": 2, "2_plus": 3, "3_5": 4, "5_plus": 6, "5+": 6}
                    u_exp = int(user_exp_raw) if user_exp_raw.isdigit() else u_map.get(user_exp_raw, 0)

                    if u_exp >= min_yoe and score >= 50:
                        suitability_escaped = escape_md(f"Suitable for your profile ({yoe_label})")
                        suitability_line = f"🟢 *{suitability_escaped}*"
                    elif min_yoe - u_exp <= 1 and score >= 50:
                        suitability_escaped = escape_md(f"Reach Opportunity ({yoe_label})")
                        suitability_line = f"🟡 *{suitability_escaped}*"
                    else:
                        suitability_escaped = escape_md(f"Requires {yoe_label} (Experience Gap)")
                        suitability_line = f"🔴 *{suitability_escaped}*"

                    # 2. Role Category
                    role_category = job.get("role_category") or "Software Engineering"
                    role_cat_escaped = escape_md(role_category)

                    # 3. Location & Workplace Type (e.g. 📍 Bengaluru, India (On-site) or 📍 Dubai (Remote) or 📍 Bengaluru, India (Hybrid))
                    raw_loc = (job.get("location") or "").strip()
                    workplace = (job.get("workplace_type") or "").strip().title()
                    if workplace.lower() in ("on-site", "onsite", "in-office"):
                        workplace = "On-site"
                    elif workplace.lower() in ("remote", "wfh"):
                        workplace = "Remote"
                    elif workplace.lower() in ("hybrid",):
                        workplace = "Hybrid"

                    if not raw_loc:
                        formatted_loc = "Remote" if workplace == "Remote" else ("Remote / Global" if not workplace else f"Global ({workplace})")
                    elif raw_loc.lower() in ("remote", "remote - us", "remote - global", "remote - india"):
                        formatted_loc = "Remote"
                    else:
                        if any(w in raw_loc.lower() for w in ("(remote)", "(hybrid)", "(on-site)", "(onsite)")):
                            formatted_loc = raw_loc
                        elif workplace in ("Remote", "Hybrid", "On-site"):
                            formatted_loc = f"{raw_loc} ({workplace})"
                        else:
                            formatted_loc = raw_loc

                    location_escaped = escape_md(formatted_loc)

                    # 4. Optional Salary Line
                    salary = job.get("salary")
                    salary_line = ""
                    if salary and str(salary).strip().lower() not in ("not disclosed", "none", "null", "not specified", ""):
                        salary_line = f"💰 {escape_md(str(salary).strip())}\n"

                    # 5. Key Skills Line
                    skills_list = job.get("skills") or []
                    skills_line = ""
                    if skills_list:
                        top_skills = [str(s).strip() for s in skills_list[:5] if str(s).strip()]
                        if top_skills:
                            skills_line = f"🛠️ *Key Skills:* {escape_md(', '.join(top_skills))}\n"

                    msg = (
                        f"🚨 *NEW JOB ALERT*\n\n"
                        f"*{title}* @ *{company}*\n"
                        f"{suitability_line}\n"
                        f"💡 *Role Category:* {role_cat_escaped}\n"
                        f"📍 {location_escaped}\n"
                        f"{salary_line}"
                        f"{skills_line}"
                        f"🎯 *{score}% Match*\n\n"
                        f"⚡ Direct from company careers\n"
                        f"🕐 Posted {escape_md(freshness)}"
                    )

                    # Inline buttons — HR Details is free for Pro, ₹49 for Free
                    kb = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("\U0001F517 Apply Now", url=job_url),
                            InlineKeyboardButton("\U0001F464 Request HR Details", callback_data=f"req_hr_{job_id}"),
                        ],
                    ])

                    from bot_registry import get_app_for_bot_id
                    bot_id = user.get("bot_id", 1)
                    target_app = get_app_for_bot_id(bot_id) or _bot_app

                    await target_app.bot.send_message(
                        chat_id=user["telegram_id"],
                        text=msg,
                        parse_mode="MarkdownV2",
                        reply_markup=kb,
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

