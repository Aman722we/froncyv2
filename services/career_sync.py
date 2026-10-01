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


async def _save_career_job(normalized_job: dict, source: dict) -> int | None:
    """
    Save a new career-page job into the manual_jobs table.
    Returns the new job ID, or None if it's a duplicate.
    """
    provider = normalized_job["source_provider"]
    external_id = normalized_job["external_id"]
    
    if await job_already_exists(provider, external_id):
        return None

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
                'fulltime', '{}', 0, '{}',
                $5, TRUE, NULL,
                'CAREER_PAGE', $6, $7,
                $8, $9
            )
            ON CONFLICT (source_provider, source_external_id) DO NOTHING
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
                    SELECT telegram_id, skills, location_pref, plan,
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

                    await _bot_app.bot.send_message(
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
