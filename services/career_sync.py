"""
Froncy V2 — Career Page Sync Engine.
Polls active career sources, detects new jobs, stores them,
and triggers the existing notification pipeline.
"""
import asyncio
import re
from datetime import datetime, timezone
from loguru import logger
from db.career_sources import (
    get_active_career_sources, update_source_check, job_already_exists
)
from services.career_fetcher import fetch_jobs_for_source
from db.connection import get_pool


def normalize_job_datetime(raw_dt) -> datetime | None:
    """
    Safely normalizes various timestamp formats (datetime object, ISO 8601 string,
    epoch seconds/milliseconds) to a UTC-aware datetime object.
    Clamps future timestamps (clock skew) to now (UTC).
    """
    if raw_dt is None:
        return None
    
    dt = None
    if isinstance(raw_dt, datetime):
        dt = raw_dt
    elif isinstance(raw_dt, (int, float)):
        try:
            val = float(raw_dt)
            if val > 1e11:  # epoch milliseconds
                val /= 1000.0
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    elif isinstance(raw_dt, str):
        raw_str = raw_dt.strip()
        if not raw_str:
            return None
        if raw_str.isdigit():
            try:
                val = float(raw_str)
                if val > 1e11:
                    val /= 1000.0
                dt = datetime.fromtimestamp(val, tz=timezone.utc)
            except Exception:
                return None
        else:
            try:
                dt = datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
            except Exception:
                try:
                    from dateutil.parser import parse as parse_date
                    dt = parse_date(raw_str)
                except Exception:
                    return None

    if dt:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        
        # Clock handling: clamp future timestamps (clock skew) to now
        now_utc = datetime.now(timezone.utc)
        if dt > now_utc:
            dt = now_utc
            
    return dt


def is_relevant_tech_job(title: str, department: str, location: str) -> bool:
    """
    Gatekeeper function to filter out non-tech roles and non-India/non-Global jobs.
    Uses strict word boundaries so abbreviations like 'ai', 'ui', 'qa' don't match
    words like 'paid', 'campaign', 'acquisition', 'detail', etc.
    Saves LLM tokens and DB space.
    """
    title = (title or "").lower()
    dept = (department or "").lower()
    loc = (location or "").lower()

    # 1. Location Filter (Must be India or Global Remote, drop explicitly foreign)
    if loc:
        india_cities = [
            "india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "gurgaon", 
            "noida", "chennai", "kolkata", "remote - ind", "apac", "asia", "global", "anywhere"
        ]
        is_india = any(c in loc for c in india_cities)
        
        # If it doesn't explicitly mention India/Global AND doesn't mention Remote, it's a local foreign job
        if not is_india and "remote" not in loc:
            return False

        # Even if it says "Remote", drop it if it specifically locks to a foreign region and NOT India
        if not is_india:
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

    # 2. Department / Title Hard Veto (Non-Tech, Marketing, HR, Partnerships, Events)
    junk_keywords = [
        "sales", "marketing", "account executive", "hr", "human resources", "recruiter", "recruiting",
        "finance", "accounting", "legal", "counsel", "customer success", "advocacy", 
        "content", "copywriter", "business development", "payroll", "tax",
        "workplace", "facilities", "executive assistant", "vp", "chief",
        "solutions", "solution", "sales engineer", "support", "technical support",
        "partner", "partnerships", "activation", "activations", "brand", "event", "events",
        "buyer", "merchandising", "growth partner", "client partner", "pr", "public relations"
    ]
    for junk in junk_keywords:
        if re.search(r'\b' + re.escape(junk) + r'\b', title) or re.search(r'\b' + re.escape(junk) + r'\b', dept):
            return False

    # 3. Tech Whitelist (Must match at least one with word boundaries)
    tech_keywords = [
        "engineer", "developer", "sde", "programmer", "software", "coder", "architect",
        "data", "ml", "ai", "machine learning", "product", "designer", "ui", "ux",
        "security", "cloud", "sre", "devops", "platform", "backend", "frontend",
        "fullstack", "ios", "android", "mobile", "qa", "test", "systems", "research", "mle"
    ]
    for tech in tech_keywords:
        if re.search(r'\b' + re.escape(tech) + r'\b', title) or re.search(r'\b' + re.escape(tech) + r'\b', dept):
            return True
    
    return False


async def _save_career_job(normalized_job: dict, source: dict) -> tuple[int | None, str]:
    """
    Save a new career-page job into the manual_jobs table.
    Returns (job_id, status) where status is 'saved', 'non_tech', 'stale', or 'duplicate'.
    """
    provider = normalized_job["source_provider"]
    external_id = normalized_job["external_id"]

    # --- GATEKEEPER 1: Relevant Tech Filter (In-Memory Regex) ---
    if not is_relevant_tech_job(
        normalized_job.get("title"), 
        normalized_job.get("department"), 
        normalized_job.get("location")
    ):
        return None, "non_tech"

    # --- GATEKEEPER 2: Ingestion Age Gate (In-Memory Timestamp Check) ---
    from config import settings
    raw_pub = normalized_job.get("published_at")
    pub_at = normalize_job_datetime(raw_pub)
    has_verified_pub_date = (raw_pub is not None and pub_at is not None)

    if pub_at is not None:
        now_utc = datetime.now(timezone.utc)
        age_days = (now_utc - pub_at).total_seconds() / 86400.0
        if age_days > settings.JOB_INGEST_MAX_AGE_DAYS:
            logger.debug(
                f"⏳ Gatekeeper: Dropped stale job '{normalized_job.get('title')}' from {source.get('company_name')} "
                f"(posted {age_days:.1f} days ago > {settings.JOB_INGEST_MAX_AGE_DAYS}d limit)"
            )
            return None, "stale"

    # --- GATEKEEPER 3: DB Deduplication Check ---
    if await job_already_exists(provider, external_id):
        return None, "duplicate"

    # Call LLM to extract skills, yoe, salary, workplace, role category, role summary
    from services.llm_service import extract_job_metadata
    description = normalized_job.get("description") or ""
    metadata = await extract_job_metadata(
        job_description=description,
        job_title=normalized_job.get("title", ""),
        location=normalized_job.get("location", "")
    )
    extracted_skills = metadata.get("skills", [])
    if not extracted_skills:
        from services.llm_service import _infer_fallback_skills
        extracted_skills = _infer_fallback_skills(
            normalized_job.get("title", ""),
            description
        )
    extracted_min_yoe = metadata.get("min_yoe", 0)
    extracted_max_yoe = metadata.get("max_yoe")
    extracted_salary = metadata.get("salary") or "Not disclosed"
    extracted_workplace = metadata.get("workplace_type") or "On-site"
    extracted_role_category = metadata.get("role_category") or "Software Engineering"
    extracted_role_summary = metadata.get("role_summary") or ""
    extracted_fresher_friendly = metadata.get("is_fresher_friendly", extracted_min_yoe <= 2)

    clean_job_url = (normalized_job.get("job_url") or normalized_job.get("apply_url") or "").strip()
    if clean_job_url.endswith("/apply"):
        clean_job_url = clean_job_url[:-6]
    elif clean_job_url.endswith("/apply/"):
        clean_job_url = clean_job_url[:-7]
    elif clean_job_url.endswith("/application"):
        clean_job_url = clean_job_url[:-12]
    elif clean_job_url.endswith("/application/"):
        clean_job_url = clean_job_url[:-13]

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
                max_yoe, role_category, role_summary, workplace_type, is_fresher_friendly,
                has_verified_pub_date, company_id
            ) VALUES (
                $1, $2, $3, $4,
                'fulltime', $10, $11, '{}',
                $5, TRUE, NULL,
                'CAREER_PAGE', $6, $7,
                $8, $9, $12,
                $13, $14, $15, $16, $17,
                $18, $19
            )
            ON CONFLICT (source_provider, source_external_id) WHERE source_external_id IS NOT NULL DO NOTHING
            RETURNING id
            """,
            normalized_job["title"],
            source["company_name"],
            clean_job_url,
            normalized_job.get("location"),
            pub_at or now,
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
            extracted_fresher_friendly,
            has_verified_pub_date,
            source.get("company_id")
        )
        if row:
            from db.manual_jobs import invalidate_jobs_cache
            invalidate_jobs_cache()
            return row["id"], "saved"
        return None, "duplicate"


async def sync_one_source(source: dict) -> dict:
    """
    Sync a single career source.
    Returns a summary dict: {fetched, new, duplicates, errors, deactivated}.
    """
    source_id = source["id"]
    company = source["company_name"]
    provider = source["provider"].upper()
    summary = {
        "company": company,
        "fetched": 0,
        "new": 0,
        "duplicates": 0,
        "stale_dropped": 0,
        "non_tech_dropped": 0,
        "errors": 0,
        "deactivated": 0
    }

    try:
        jobs = await fetch_jobs_for_source(source)
        summary["fetched"] = len(jobs)

        new_job_ids = []
        active_ext_ids = []
        for job in jobs:
            try:
                ext_id = str(job.get("external_id") or "")
                if ext_id:
                    active_ext_ids.append(ext_id)

                new_id, reason = await _save_career_job(job, source)
                if new_id:
                    summary["new"] += 1
                    new_job_ids.append(new_id)
                    # Throttle between successive new job extractions to protect LLM limits
                    await asyncio.sleep(1.2)
                elif reason == "stale":
                    summary["stale_dropped"] += 1
                elif reason == "non_tech":
                    summary["non_tech_dropped"] += 1
                else:
                    summary["duplicates"] += 1
            except Exception as e:
                logger.warning(f"Error saving job '{job.get('title')}' from {company}: {e}")
                summary["errors"] += 1

        # Circuit breaker / drop rate telemetry: if >90% of board dropped as stale, log warning
        if summary["fetched"] > 10 and (summary["stale_dropped"] / summary["fetched"]) > 0.90:
            logger.warning(
                f"⚠️ High stale drop rate for {company}: {summary['stale_dropped']}/{summary['fetched']} "
                f"({(summary['stale_dropped']/summary['fetched']):.0%}) dropped as stale. Verify ATS timestamp parser."
            )

        # ── EXPIRED JOBS DEACTIVATION ──────────────────────────────────────────
        # If the ATS returned a list of jobs, any job in our DB for this company
        # that is NOT in the current ATS list has been closed/removed.
        # Deactivate them immediately so users never see 404 dead links!
        if active_ext_ids:
            pool = get_pool()
            async with pool.acquire() as conn:
                res = await conn.execute(
                    """
                    UPDATE manual_jobs
                    SET is_active = FALSE
                    WHERE source_provider = $1
                      AND source_external_id IS NOT NULL
                      AND company = $2
                      AND is_active = TRUE
                      AND NOT (source_external_id = ANY($3::text[]))
                    """,
                    provider,
                    company,
                    active_ext_ids
                )
                deactivated = int(res.split(" ")[1]) if "UPDATE" in res else 0
                if deactivated > 0:
                    logger.info(f"🗑️ Deactivated {deactivated} expired/closed jobs from {company}")
                    summary["deactivated"] = deactivated
                    from db.manual_jobs import invalidate_jobs_cache
                    invalidate_jobs_cache()

                # Reactivate any job that was reopened on the ATS
                await conn.execute(
                    """
                    UPDATE manual_jobs
                    SET is_active = TRUE
                    WHERE source_provider = $1
                      AND company = $2
                      AND source_external_id = ANY($3::text[])
                      AND is_active = FALSE
                    """,
                    provider,
                    company,
                    active_ext_ids
                )

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
    and send them an instant Telegram notification (RFC-001 & RFC-002).
    
    Architecture features:
    - Upstream scoping: excludes blocked users, paused users, and users who disabled instant alerts.
    - Silent Night Delivery: Between 10 PM and 8 AM IST, messages are delivered silently without vibration.
    - In-Message Escape Hatch: Direct [ ⚙️ Manage Alerts ] button on every alert.
    - Bulk Circuit Breaker: If >5 jobs match in a single crawl, sends 1 consolidated bundle card.
    - Safe delivery wrapper with auto-pruning of users who blocked the bot.
    """
    from services.scheduler import _bot_app
    if not _bot_app:
        logger.warning("Bot app not set — cannot send career page notifications")
        return

    pool = get_pool()
    PRO_PLANS = ("pro", "trial", "proplus", "premium")

    # 1. Fetch candidate jobs and eligible Pro users
    async with pool.acquire() as conn:
        job_rows = await conn.fetch(
            "SELECT * FROM manual_jobs WHERE id = ANY($1::int[])",
            job_ids
        )
        user_rows = await conn.fetch(
            """
            SELECT telegram_id, bot_id, skills, location_pref, plan,
                   experience_level, batch_year, role_pref, is_trial, trial_expires_at,
                   notify_instant_alerts, silent_night_mode, alerts_paused_until, is_blocked,
                   company_filter_mode
            FROM users
            WHERE is_onboarded = TRUE
              AND (is_deleted IS NULL OR is_deleted = FALSE)
              AND (is_blocked IS NULL OR is_blocked = FALSE)
              AND (notify_instant_alerts IS NULL OR notify_instant_alerts = TRUE)
              AND (alerts_paused_until IS NULL OR alerts_paused_until < NOW())
              AND plan IN ('pro', 'trial', 'proplus', 'premium')
            """
        )

    if not job_rows:
        return

    # Filter eligible jobs by RFC-001 freshness and undated board safety
    from config import settings
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    from zoneinfo import ZoneInfo
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    is_night_window = (now_ist.hour >= 22 or now_ist.hour < 8)

    eligible_jobs = []
    for r in job_rows:
        job = dict(r)
        if not job.get("has_verified_pub_date", True):
            continue
        posted = job.get("posted_at")
        if posted:
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            hours_ago = (now_utc - posted).total_seconds() / 3600.0
            if hours_ago > settings.ALERT_FRESHNESS_MAX_HOURS:
                continue
        job["is_manual"] = True
        eligible_jobs.append(job)

    if not eligible_jobs:
        return

    from utils.messages import compute_manual_job_match, escape_md
    from utils.helpers import get_effective_plan, get_base_url
    from utils.safe_send import safe_send_message
    from bot_registry import get_app_for_bot_id
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from db.tracker import log_instant_alert_sent
    from db.manual_jobs import log_jobs_sent
    from db.company_prefs import load_all_active_company_prefs
    from utils.visibility import is_job_visible_to_user

    all_user_mutes, all_user_follows = await load_all_active_company_prefs()

    base_url = get_base_url()

    for user_row in (user_rows or []):
        try:
            user = dict(user_row)
            plan = get_effective_plan(user)
            if plan not in PRO_PLANS:
                continue
            user["plan"] = plan

            # Match user against all eligible jobs (RFC-004 visibility & threshold)
            uid = user["telegram_id"]
            u_mutes = all_user_mutes.get(uid, set())
            u_follows = all_user_follows.get(uid, set())

            matched_items = []
            for job in eligible_jobs:
                if not is_job_visible_to_user(user, job, u_mutes, u_follows, context="instant", now_utc=now_utc):
                    continue

                match = compute_manual_job_match(user, job)
                score = match.get("score", 0)

                # Relax threshold to 40% if company is followed and role category matches user preference
                job_cid = job.get("company_id")
                threshold = 50
                if job_cid and job_cid in u_follows:
                    u_role = (user.get("role_pref") or "").lower()
                    j_role = (job.get("role_category") or "").lower()
                    if u_role and (u_role in j_role or j_role in u_role or "software" in j_role):
                        threshold = 40

                if score >= threshold:
                    matched_items.append((job, score, match))

            if not matched_items:
                continue

            bot_id = user.get("bot_id", 1)
            target_app = get_app_for_bot_id(bot_id) or _bot_app
            silent_delivery = is_night_window and user.get("silent_night_mode", True)

            # --- BULK CIRCUIT BREAKER (>5 jobs in one crawl) ---
            if len(matched_items) > 5:
                count = len(matched_items)
                bundle_lines = [
                    f"🚨 *NEW JOBS BUNDLE* \({count} Openings\)\n",
                    f"We just uncovered *{count} new positions* matching your profile:\n"
                ]
                matched_items.sort(key=lambda x: x[1], reverse=True)
                for i, (job, score, _) in enumerate(matched_items[:7], 1):
                    j_title = escape_md(job.get("title", "Job"))
                    j_comp = escape_md(job.get("company", "Company"))
                    bundle_lines.append(f"{i}\\. *{j_title}* @ *{j_comp}* — 🎯 *{score}% Match*")

                if count > 7:
                    bundle_lines.append(f"\n_...and {count - 7} more positions direct from company careers!_")

                bundle_lines.append("\n⚡ Direct from company careers")
                bundle_text = "\n".join(bundle_lines)

                bundle_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Open Daily Feed", callback_data="menu_daily")],
                    [InlineKeyboardButton("⚙️ Manage Alerts", callback_data="settings_notifications")],
                ])

                await safe_send_message(
                    bot=target_app.bot,
                    chat_id=user["telegram_id"],
                    text=bundle_text,
                    parse_mode="MarkdownV2",
                    reply_markup=bundle_kb,
                    disable_notification=silent_delivery,
                    disable_web_page_preview=True,
                    bot_id=bot_id
                )

                job_ids_sent = [j["id"] for j, _, _ in matched_items]
                await log_jobs_sent(user["telegram_id"], job_ids_sent, bot_id=bot_id)
                for jid in job_ids_sent:
                    await log_instant_alert_sent(user["telegram_id"], jid)

                continue

            # --- STANDARD SINGLE-JOB ALERTS (<=5 jobs) ---
            for job, score, _ in matched_items:
                job_id = job["id"]
                posted = job.get("posted_at")
                if posted:
                    if posted.tzinfo is None:
                        posted = posted.replace(tzinfo=timezone.utc)
                    mins_ago = int((now_utc - posted).total_seconds() / 60)
                    if mins_ago < 0: mins_ago = 0
                    freshness = f"{mins_ago} min ago" if mins_ago < 60 else f"{mins_ago // 60}h ago"
                else:
                    freshness = "just now"

                title = escape_md(job.get("title", "New Job"))
                company = escape_md(job.get("company", "Unknown"))
                job_url = job.get("url", "")

                min_yoe = job.get("min_yoe") or 0
                max_yoe = job.get("max_yoe")
                if max_yoe and max_yoe > min_yoe:
                    yoe_label = f"{min_yoe}-{max_yoe} YOE"
                elif min_yoe == 0:
                    yoe_label = "0-2 YOE"
                else:
                    yoe_label = f"{min_yoe}+ YOE"

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

                role_category = job.get("role_category") or "Software Engineering"
                role_cat_escaped = escape_md(role_category)

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

                salary = job.get("salary")
                salary_line = ""
                if salary and str(salary).strip().lower() not in ("not disclosed", "none", "null", "not specified", ""):
                    salary_line = f"💰 {escape_md(str(salary).strip())}\n"

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

                u_id = user.get("telegram_id")
                if base_url and u_id:
                    apply_btn_url = f"{base_url}/r/{job_id}?uid={u_id}&src=instant_alert"
                else:
                    apply_btn_url = job_url or "https://t.me/FroncyJobsBot"

                job_cid = job.get("company_id")
                action_row = []
                if job_cid:
                    is_following = (job_cid in u_follows)
                    cname = (job.get("company") or "Company")[:15]
                    if is_following:
                        action_row.append(InlineKeyboardButton("✅ Following", callback_data=f"cf_unfw:{job_cid}"))
                    else:
                        action_row.append(InlineKeyboardButton(f"⭐ Follow {cname}", callback_data=f"cf_fw:{job_cid}"))
                    action_row.append(InlineKeyboardButton("🔕 Mute", callback_data=f"cf_mt:{job_cid}"))

                kb_rows = [
                    [InlineKeyboardButton("🔗 Apply Now", url=apply_btn_url)]
                ]
                if action_row:
                    kb_rows.append(action_row)
                kb_rows.append([InlineKeyboardButton("⚙️ Manage Alerts", callback_data="settings_notifications")])
                kb = InlineKeyboardMarkup(kb_rows)

                sent_msg = await safe_send_message(
                    bot=target_app.bot,
                    chat_id=user["telegram_id"],
                    text=msg,
                    parse_mode="MarkdownV2",
                    reply_markup=kb,
                    disable_notification=silent_delivery,
                    disable_web_page_preview=True,
                    bot_id=bot_id
                )

                if sent_msg:
                    await log_instant_alert_sent(user["telegram_id"], job_id)
                    await log_jobs_sent(user["telegram_id"], [job_id], bot_id=bot_id)

                await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"Failed to process alerts for user {user_row.get('telegram_id')}: {e}")

    # ── FREE USER WEEKLY SAMPLE DROPS (RFC-003) ──
    try:
        async with pool.acquire() as conn:
            free_user_rows = await conn.fetch(
                """
                SELECT telegram_id, bot_id, skills, location_pref, plan,
                       experience_level, batch_year, role_pref, is_trial, trial_expires_at,
                       notify_instant_alerts, silent_night_mode, alerts_paused_until, is_blocked,
                       last_sample_alert_at, company_filter_mode
                FROM users
                WHERE is_onboarded = TRUE
                  AND (is_deleted IS NULL OR is_deleted = FALSE)
                  AND (is_blocked IS NULL OR is_blocked = FALSE)
                  AND (notify_instant_alerts IS NULL OR notify_instant_alerts = TRUE)
                  AND (alerts_paused_until IS NULL OR alerts_paused_until < NOW())
                  AND (last_sample_alert_at IS NULL OR last_sample_alert_at < NOW() - INTERVAL '7 days')
                  AND (plan IS NULL OR plan = 'free')
                """
            )

        for f_user_row in free_user_rows:
            try:
                f_user = dict(f_user_row)
                f_plan = get_effective_plan(f_user)
                if f_plan != "free":
                    continue
                f_uid = f_user["telegram_id"]

                # Find single highest-scoring match >= 80% (RFC-004 visibility & tie-break)
                f_mutes = all_user_mutes.get(f_uid, set())
                f_follows = all_user_follows.get(f_uid, set())

                best_job = None
                best_score = 0
                best_effective_score = 0
                for job in eligible_jobs:
                    if not is_job_visible_to_user(f_user, job, f_mutes, f_follows, context="sample", now_utc=now_utc):
                        continue
                    m = compute_manual_job_match(f_user, job)
                    s = m.get("score", 0)
                    if s >= 80:
                        is_followed = (job.get("company_id") in f_follows)
                        effective = s + (8 if is_followed else 0)
                        if effective > best_effective_score:
                            best_effective_score = effective
                            best_score = s
                            best_job = job

                if not best_job:
                    continue

                # Atomic claim on weekly slot (prevents race conditions)
                async with pool.acquire() as conn:
                    claimed = await conn.fetchval(
                        """
                        UPDATE users
                        SET last_sample_alert_at = NOW()
                        WHERE telegram_id = $1
                          AND (last_sample_alert_at IS NULL OR last_sample_alert_at < NOW() - INTERVAL '7 days')
                        RETURNING telegram_id
                        """,
                        f_uid
                    )
                if not claimed:
                    continue

                job_id = best_job["id"]
                title = escape_md(best_job.get("title", "New Job"))
                company = escape_md(best_job.get("company", "Unknown"))
                job_url = best_job.get("url", "")

                posted = best_job.get("posted_at")
                if posted:
                    if posted.tzinfo is None:
                        posted = posted.replace(tzinfo=timezone.utc)
                    mins_ago = int((now_utc - posted).total_seconds() / 60)
                    if mins_ago < 0: mins_ago = 0
                    freshness = f"{mins_ago} min ago" if mins_ago < 60 else f"{mins_ago // 60}h ago"
                else:
                    freshness = "just now"

                min_yoe = best_job.get("min_yoe") or 0
                max_yoe = best_job.get("max_yoe")
                yoe_label = f"{min_yoe}-{max_yoe} YOE" if (max_yoe and max_yoe > min_yoe) else ("0-2 YOE" if min_yoe == 0 else f"{min_yoe}+ YOE")
                user_exp_raw = str(f_user.get("experience_level", "0")).strip()
                u_map = {"0": 0, "1": 1, "2": 2, "2_plus": 3, "3_5": 4, "5_plus": 6, "5+": 6}
                u_exp = int(user_exp_raw) if user_exp_raw.isdigit() else u_map.get(user_exp_raw, 0)

                suitability_escaped = escape_md(f"Suitable for your profile ({yoe_label})") if u_exp >= min_yoe else escape_md(f"Requires {yoe_label}")
                suitability_line = f"🟢 *{suitability_escaped}*"

                role_category = best_job.get("role_category") or "Software Engineering"
                role_cat_escaped = escape_md(role_category)

                raw_loc = (best_job.get("location") or "").strip()
                workplace = (best_job.get("workplace_type") or "").strip().title()
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

                salary = best_job.get("salary")
                salary_line = ""
                if salary and str(salary).strip().lower() not in ("not disclosed", "none", "null", "not specified", ""):
                    salary_line = f"💰 {escape_md(str(salary).strip())}\n"

                skills_list = best_job.get("skills") or []
                skills_line = ""
                if skills_list:
                    top_skills = [str(s).strip() for s in skills_list[:5] if str(s).strip()]
                    if top_skills:
                        skills_line = f"🛠️ *Key Skills:* {escape_md(', '.join(top_skills))}\n"

                sample_msg = (
                    f"🚨 *WEEKLY PRO SAMPLE ALERT*\n\n"
                    f"*{title}* @ *{company}*\n"
                    f"{suitability_line}\n"
                    f"💡 *Role Category:* {role_cat_escaped}\n"
                    f"📍 {location_escaped}\n"
                    f"{salary_line}"
                    f"{skills_line}"
                    f"🎯 *{best_score}% Match*\n\n"
                    f"⚡ Direct from company careers • Posted {escape_md(freshness)}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⭐ *Pro members get instant drops like this for every opening.*\n"
                    f"_This high\\-match weekly sample is on us!_"
                )

                if base_url:
                    apply_btn_url = f"{base_url}/r/{job_id}?uid={f_uid}&src=free_sample_alert"
                else:
                    apply_btn_url = job_url or "https://t.me/FroncyJobsBot"

                f_job_cid = best_job.get("company_id")
                f_action_row = []
                if f_job_cid:
                    is_following = (f_job_cid in f_follows)
                    cname = (best_job.get("company") or "Company")[:15]
                    if is_following:
                        f_action_row.append(InlineKeyboardButton("✅ Following", callback_data=f"cf_unfw:{f_job_cid}"))
                    else:
                        f_action_row.append(InlineKeyboardButton(f"⭐ Follow {cname}", callback_data=f"cf_fw:{f_job_cid}"))
                    f_action_row.append(InlineKeyboardButton("🔕 Mute", callback_data=f"cf_mt:{f_job_cid}"))

                sample_kb_rows = [
                    [InlineKeyboardButton("🔗 Apply Now", url=apply_btn_url)],
                ]
                if f_action_row:
                    sample_kb_rows.append(f_action_row)
                sample_kb_rows.extend([
                    [InlineKeyboardButton("⭐ Get Instant Drops (Pro)", callback_data="upgrade_pro")],
                    [InlineKeyboardButton("👥 Get Pro Free (Refer Friends)", callback_data="menu_refer")],
                    [InlineKeyboardButton("⚙️ Manage Alerts", callback_data="settings_notifications")],
                ])
                sample_kb = InlineKeyboardMarkup(sample_kb_rows)

                f_bot_id = f_user.get("bot_id", 1)
                f_target_app = get_app_for_bot_id(f_bot_id) or _bot_app

                # Delivered silently without buzzer
                sent_msg = await safe_send_message(
                    bot=f_target_app.bot,
                    chat_id=f_uid,
                    text=sample_msg,
                    parse_mode="MarkdownV2",
                    reply_markup=sample_kb,
                    disable_notification=True,
                    disable_web_page_preview=True,
                    bot_id=f_bot_id
                )

                if sent_msg:
                    await log_instant_alert_sent(f_uid, job_id)
                    await log_jobs_sent(f_uid, [job_id], bot_id=f_bot_id)
                else:
                    async with pool.acquire() as conn:
                        await conn.execute("UPDATE users SET last_sample_alert_at = NULL WHERE telegram_id = $1", f_uid)

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"Failed to process sample alert for user {f_user_row.get('telegram_id')}: {e}")
    except Exception as e:
        logger.error(f"Failed to process free weekly sample alerts: {e}")


_sync_lock = asyncio.Lock()


def is_career_sync_running() -> bool:
    """Return True if career sync is currently running."""
    return _sync_lock.locked()


async def run_career_sync() -> list[dict]:
    """
    Main sync runner. Fetches all active sources and syncs them.
    One failing source does NOT stop others.
    Returns a list of per-source summary dicts.
    Guarded by _sync_lock: never runs concurrently with another sync.
    """
    if _sync_lock.locked():
        logger.warning("⚡ Career sync is already in progress. Skipping overlapping execution.")
        return []

    async with _sync_lock:
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

        # Auto-heal: only trigger if fresh jobs were ingested during this run
        if total_new > 0:
            try:
                repaired = await backfill_empty_skills_jobs(limit=10)
                if repaired > 0:
                    logger.info(f"✨ Auto-healed {repaired} new jobs with missing skills!")
            except Exception as e:
                logger.warning(f"Error during auto-heal backfill: {e}")

        return summaries


async def backfill_empty_skills_jobs(limit: int = 50) -> int:
    """
    Find jobs in manual_jobs that have empty skills array and re-extract their metadata.
    Returns the number of jobs repaired.
    """
    from services.llm_service import extract_job_metadata
    pool = get_pool()
    repaired = 0

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, title, description, location, url
                FROM manual_jobs
                WHERE (COALESCE(skills_attempts, 0) < 2)
                   AND (
                       skills = '{}' 
                       OR array_length(skills, 1) IS NULL 
                       OR array_length(skills, 1) = 0
                       OR role_category IS NULL
                   )
                ORDER BY id DESC
                LIMIT $1
                """,
                limit
            )

        if not rows:
            return 0

        from services.career_fetcher import _strip_html
        logger.info(f"🔄 Backfilling intelligence for {len(rows)} jobs needing enrichment...")
        for row in rows:
            job_id = row["id"]
            title = row["title"]
            try:
                # Mark attempt count immediately to prevent infinite retry loops
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE manual_jobs
                        SET skills_attempts = COALESCE(skills_attempts, 0) + 1,
                            skills_attempted_at = NOW()
                        WHERE id = $1
                        """,
                        job_id
                    )
                raw_desc = row["description"] or ""
                desc = _strip_html(raw_desc)
                loc = row["location"] or ""
                job_url = row.get("url") or ""

                # If description is missing from DB, attempt fetching directly from the job URL
                if len(desc) < 100 and job_url:
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                            resp = await client.get(job_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                            if resp.status_code == 200:
                                fetched_desc = _strip_html(resp.text)
                                if len(fetched_desc) > len(desc):
                                    desc = fetched_desc
                    except Exception:
                        pass

                metadata = await extract_job_metadata(
                    job_description=desc,
                    job_title=title,
                    location=loc
                )
                skills = metadata.get("skills", [])
                min_yoe = metadata.get("min_yoe", 0)
                max_yoe = metadata.get("max_yoe")
                salary = metadata.get("salary") or "Not disclosed"
                wpt = metadata.get("workplace_type") or "On-site"
                cat = metadata.get("role_category") or "Software Engineering"
                summary = metadata.get("role_summary") or ""
                fresher = metadata.get("is_fresher_friendly", min_yoe <= 2)

                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE manual_jobs
                        SET skills = $2, min_yoe = $3, max_yoe = $4, salary = $5,
                            workplace_type = $6, role_category = $7, role_summary = $8,
                            is_fresher_friendly = $9,
                            description = $10
                        WHERE id = $1
                        """,
                        job_id, skills, min_yoe, max_yoe, salary, wpt, cat, summary, fresher, desc
                    )
                repaired += 1
                logger.info(f"  ✓ Repaired job {job_id} ({title}): skills={skills}, cat={cat}, yoe={min_yoe}")
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.warning(f"Failed to backfill job {row['id']}: {e}")

        if repaired > 0:
            from db.manual_jobs import invalidate_jobs_cache
            invalidate_jobs_cache()

    except Exception as e:
        logger.error(f"Error in backfill_empty_skills_jobs: {e}")

    return repaired

