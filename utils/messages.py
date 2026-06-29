"""
Message templates for FroncyBot — MarkdownV2 formatted.
All bot-facing text lives here to keep handlers clean.
"""
from utils.helpers import escape_md


# ──────────────────────────────────────────────
# Onboarding
# ──────────────────────────────────────────────

ONBOARDING_STEPS = 2

def _step_bar(current: int) -> str:
    """Generate a visual progress bar for onboarding. current is 1-indexed."""
    filled = "🟢"
    empty  = "⚪"
    bar = "".join(filled if i < current else empty for i in range(ONBOARDING_STEPS))
    return f"\\[{bar}\\] Step {escape_md(str(current))} of {ONBOARDING_STEPS}"

def welcome_message(first_name: str = "there") -> str:
    safe_name = escape_md(first_name)
    return (
        f"👋 Hey {safe_name}\\!\n\n"
        "Struggling to land your first frontend job?\n\n"
        "Froncy curates the best frontend jobs & internships for freshers, "
        "writes cover letters that actually get read, and tracks "
        "every application so nothing falls through the cracks\\.\n\n"
        "*3 days free\\. No card needed\\. Cancel anytime\\.* \n\n"
        "Let's get you interviews, not just applications\\. 🎯\n\n"
        "What best describes you?"
    )


def skills_prompt(first_name: str = None) -> str:
    bar = _step_bar(1)
    greeting = f"👋 Hey {escape_md(first_name)}\\! " if first_name else ""
    return (
        f"{bar}\n\n"
        f"{greeting}*Pick your skills* 🛠️\n"
        "Which frontend technologies do you work with?\n"
        "\\(Select all that apply, then tap *Done*\\)"
    )


def trial_activated_message(trial_expires_at) -> str:
    """Shown after onboarding completes — announces the 3-day Pro trial."""
    if trial_expires_at:
        from datetime import timezone
        expires_str = escape_md(
            trial_expires_at.strftime("%A, %B %-d at %-I:%M %p UTC")
        )
    else:
        expires_str = "72 hours from now"
    return (
        "🎉 *3\\-Day Pro Trial — Activated\\!*\n\n"
        "For the next 72 hours you have full Pro access:\n"
        "✅ Unlimited jobs\n"
        "✅ 10 cover letters/day\n"
        "✅ Full match scores on every job\n"
        "✅ 5 ATS checks/day\n"
        "✅ Unlimited application tracking\n"
        "✅ 7\\-day follow\\-up reminders\n\n"
        "*No card needed\\. No auto\\-charge\\. Ever\\.* \n\n"
        "After 3 days you choose — upgrade or stay free\\.\n"
        "Either way, your data stays\\.\n\n"
        f"Your trial expires: {expires_str}\n\n"
        "*What would you like to do first?*"
    )


def onboarding_complete(skills: list[str], location: str, has_resume: bool) -> str:
    """Legacy fallback — now replaced by trial_activated_message in most flows."""
    skills_text = escape_md(", ".join(skills)) if skills else "None selected"
    loc_map = {"remote": "🌏 Remote", "india": "🇮🇳 India", "both": "🌐 Both"}
    loc_text = loc_map.get(location, location)
    resume_text = "✅ Uploaded" if has_resume else "❌ Not uploaded yet"

    return (
        "✅ *You're all set\\!*\n\n"
        f"*Skills:* {skills_text}\n"
        f"*Location:* {escape_md(loc_text)}\n"
        f"*Resume:* {resume_text}\n\n"
        "I'll send your first job alerts tomorrow morning\\.\n\n"
        "What would you like to do now?"
    )


# ──────────────────────────────────────────────
# Main Menu
# ──────────────────────────────────────────────

def main_menu(user: dict, pricing: dict | None = None) -> str:
    plan = user.get("plan", "free")

    if plan == "pro":
        expires_at = user.get("plan_expires_at")
        date_str = expires_at.strftime("%b %d") if expires_at else "soon"
        early_tag = " \\(Early Adopter 🔒\\)" if user.get("is_early_adopter") else ""
        return (
            "🏠 *Froncy*\n"
            f"Plan: ⭐ Pro{early_tag} \\(Unlimited jobs · 10 cover letters · 5 ATS checks/day\\)\n"
            f"Renews: {escape_md(date_str)}\n"
        )

    is_trial = user.get("is_trial", False)
    
    if is_trial:
        trial_expires = user.get("trial_expires_at")
        from datetime import datetime, timezone
        if trial_expires:
            remaining = trial_expires - datetime.now(timezone.utc)
            hours_left = max(0, int(remaining.total_seconds() / 3600))
            if hours_left > 0:
                time_str = f"{hours_left}h remaining"
                return (
                    "🏠 *Froncy*\n"
                    f"⚡ Pro Trial — {escape_md(time_str)}\n"
                )
            # If hours_left <= 0, fall through to free plan
        else:
            return (
                "🏠 *Froncy*\n"
                f"⚡ Pro Trial — active\n"
            )

    # Free plan — no upgrade text in message body (keyboard has the button)
    return (
        "🏠 *Froncy*\n"
        "Plan: Free \\(5 jobs · 1 cover letter · 1 ATS check/day\\)"
    )


# ──────────────────────────────────────────────
# Jobs
# ──────────────────────────────────────────────

def compute_match_details(user_skills: list[str], job_skills: list[str], user_exp: str = "0", job_exp: int | None = None) -> dict:
    """Compute a weighted match score: 70% skills + 30% experience."""
    
    # ── Skills Component (70% weight) ──
    if not job_skills:
        skill_pct = 50  # unknown job requirements = neutral
        matched_disp, missing_disp = [], []
    else:
        user_set = set(s.lower() for s in user_skills)
        matched_disp, missing_disp = [], []
        matched_count = 0
        
        for raw_jskill in job_skills:
            jskill_lower = raw_jskill.lower()
            if "/" in jskill_lower:
                # Treat as an "OR" condition (e.g. "React/Angular/Vue")
                sub_skills = [s.strip() for s in jskill_lower.split("/")]
                if any(sub in user_set for sub in sub_skills):
                    matched_count += 1
                    matched_disp.append(raw_jskill)
                else:
                    missing_disp.append(raw_jskill)
            else:
                if jskill_lower in user_set:
                    matched_count += 1
                    matched_disp.append(raw_jskill)
                else:
                    missing_disp.append(raw_jskill)
                    
        skill_pct = int((matched_count / len(job_skills)) * 100) if job_skills else 50
    
    # ── Experience Component (30% weight) ──
    u_map = {"0": 0, "1": 1, "2": 2, "3_5": 4, "5_plus": 6, "5+": 6}
    u_exp_years = u_map.get(str(user_exp), 0)
    
    exp_pct = 50  # default: unknown job requirement
    exp_note = None
    
    if job_exp is not None and job_exp > 0:
        gap = u_exp_years - job_exp
        if gap >= 0:
            exp_pct = 100  # meets or exceeds
            if gap > 2:
                exp_note = f"✅ You exceed the {job_exp}+ yr requirement"
            else:
                exp_note = f"✅ You meet the {job_exp}+ yr requirement"
        elif gap == -1:
            exp_pct = 60  # close
            exp_note = f"⚠️ Requires {job_exp}+ yrs — you have {u_exp_years}"
        else:
            exp_pct = max(0, 100 + (gap * 25))  # steep penalty
            exp_note = f"🔴 Requires {job_exp}+ yrs — you have {u_exp_years}"
    
    # ── Weighted Total ──
    total_score = int(skill_pct * 0.70 + exp_pct * 0.30)
    
    # Severe penalty for massive experience gaps (hard filters)
    if job_exp is not None and job_exp > 0:
        gap = u_exp_years - job_exp
        if gap < -7:
            # Huge gap (e.g. 0-1 yr applying for 10+ yrs)
            total_score = int(total_score * 0.20)
        elif gap <= -5:
            # Major gap (e.g. fresher applying for Senior 5-8+ role)
            total_score = int(total_score * 0.35)
        elif gap <= -3:
            # Significant gap
            total_score = int(total_score * 0.60)
        elif gap == -2:
            # Small gap, minor penalty
            total_score = int(total_score * 0.85)

    total_score = max(0, min(100, total_score))
    
    return {
        "score": total_score,
        "skill_pct": skill_pct,
        "exp_pct": exp_pct,
        "matched": matched_disp,
        "missing": missing_disp,
        "exp_note": exp_note,
        "job_exp": job_exp,
    }

def compute_manual_job_match(user: dict, job: dict) -> dict:
    """
    Compute match score for manual jobs using 5 signals:
      40% Skills | 25% YOE | 15% Recency | 10% Role | 10% Salary Quality
    """
    from datetime import datetime, timezone
    import re

    # ── Skills (40%) ──
    user_skills = user.get("skills", [])
    job_skills = job.get("skills", [])

    if not job_skills:
        skill_pct = 50
        matched_disp, missing_disp = [], []
    else:
        user_set = set(s.lower() for s in user_skills)
        matched_disp, missing_disp = [], []
        matched_count = 0
        
        for raw_jskill in job_skills:
            jskill_lower = raw_jskill.lower()
            if "/" in jskill_lower:
                # Treat as an "OR" condition
                sub_skills = [s.strip() for s in jskill_lower.split("/")]
                if any(sub in user_set for sub in sub_skills):
                    matched_count += 1
                    matched_disp.append(raw_jskill)
                else:
                    missing_disp.append(raw_jskill)
            else:
                if jskill_lower in user_set:
                    matched_count += 1
                    matched_disp.append(raw_jskill)
                else:
                    missing_disp.append(raw_jskill)

        skill_pct = int((matched_count / len(job_skills)) * 100) if job_skills else 50

    # ── Experience (25%) ──
    user_exp = str(user.get("experience_level", "0"))
    u_map = {"0": 0, "1": 1, "2": 2, "2_plus": 3, "3_5": 4, "5_plus": 6, "5+": 6}
    u_exp_years = u_map.get(user_exp, 0)

    min_yoe = job.get("min_yoe") or job.get("experience_required") or 0
    if u_exp_years >= min_yoe:
        exp_pct = 100
        exp_note = f"✅ Meets experience ({min_yoe}+ yrs)"
    elif min_yoe - u_exp_years <= 1:
        exp_pct = 50
        exp_note = f"⚠️ Partial exp gap: needs {min_yoe}+ yrs, you have {u_exp_years}"
    else:
        exp_pct = 0
        exp_note = f"🔴 Exp gap: needs {min_yoe}+ yrs, you have {u_exp_years}"

    # ── Role Preference (10%) ──
    role_pref = (user.get("role_pref") or "fullstack").lower()
    job_title = (job.get("title") or "").lower()
    job_skills_lower = [s.lower() for s in (job.get("skills") or [])]

    ROLE_KEYWORDS = {
        "frontend": ["frontend", "front-end", "front end", "ui", "react", "vue", "angular", "svelte", "html", "css", "typescript", "javascript"],
        "backend": ["backend", "back-end", "back end", "server", "api", "node", "python", "java", "django", "express", "golang", "rust", "php"],
        "fullstack": ["fullstack", "full-stack", "full stack", "mern", "mean", "next.js", "nextjs"],
    }
    role_words = ROLE_KEYWORDS.get(role_pref, [])
    if role_pref == "fullstack":
        role_words = ROLE_KEYWORDS["frontend"] + ROLE_KEYWORDS["backend"] + ROLE_KEYWORDS["fullstack"]

    title_match = any(kw in job_title for kw in role_words)
    skills_match = any(kw in s for kw in role_words for s in job_skills_lower)

    if title_match:
        role_pct = 100
    elif skills_match:
        role_pct = 70
    else:
        role_pct = 20

    # ── Salary Quality (10%) ──
    salary = job.get("salary")
    has_salary = bool(salary and str(salary).strip() and str(salary).strip().lower() not in ["null", "none", "not disclosed", "n/a", "-"])
    
    if not has_salary:
        salary_pct = -20  # Penalty for not disclosing salary
    else:
        s_lower = str(salary).lower()
        if any(curr in s_lower for curr in ["$", "usd", "€", "£", "k"]):
            salary_pct = 100
        elif "lpa" in s_lower:
            nums = re.findall(r'\d+', s_lower)
            if nums:
                max_val = max(int(n) for n in nums)
                if max_val >= 15:
                    salary_pct = 100
                elif max_val >= 8:
                    salary_pct = 70
                else:
                    salary_pct = 40
            else:
                salary_pct = 50
        else:
            salary_pct = 50

    # ── Recency (15%) ──
    posted_at = job.get("posted_at")
    if posted_at:
        if isinstance(posted_at, str):
            try:
                from dateutil.parser import parse as parse_date
                posted_at = parse_date(posted_at)
            except Exception:
                posted_at = None

        if posted_at:
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - posted_at).days
            if age_days <= 3:
                recency_pct = 100
            elif age_days <= 7:
                recency_pct = 80
            elif age_days <= 14:
                recency_pct = 50
            elif age_days <= 30:
                recency_pct = max(0, 50 - int((age_days - 14) * 3))
            else:
                recency_pct = 0
        else:
            recency_pct = 50
    else:
        recency_pct = 50

    # ── Batch Year (tiebreaker / bonus, not weighted) ──
    user_batch = user.get("batch_year")
    eligible_batches = job.get("eligible_batches", [])
    if not eligible_batches:
        batch_pct = 100
        batch_note = "✅ Any batch eligible"
    elif user_batch in eligible_batches:
        batch_pct = 100
        batch_note = f"✅ Batch match ({user_batch})"
    else:
        batch_pct = 50
        batch_str = "/".join(str(b) for b in eligible_batches)
        batch_note = f"⚠️ Batch mismatch: Job requires {batch_str}, your batch is {user_batch or 'unknown'}"

    # ── Final weighted score ──
    total_score = int(
        (skill_pct * 0.40) +
        (exp_pct   * 0.25) +
        (recency_pct * 0.15) +
        (role_pct  * 0.10) +
        (salary_pct * 0.10)
    )
    total_score = max(0, min(100, total_score))

    return {
        "score": total_score,
        "skill_pct": skill_pct,
        "exp_pct": exp_pct,
        "role_pct": role_pct,
        "salary_pct": salary_pct,
        "recency_pct": recency_pct,
        "batch_pct": batch_pct,
        "matched": matched_disp,
        "missing": missing_disp,
        "exp_note": exp_note,
        "batch_note": batch_note,
        "job_exp": min_yoe,
        "has_salary": has_salary,
    }

def format_job_list_message(jobs: list[dict], plan: str, total_count: int, user: dict = None) -> str:
    """Format a list of jobs for display."""
    showing = len(jobs)
    header = f"🔍 *Today's Frontend Jobs* \\({showing} of {total_count} available\\)\n"
    header += "━━━━━━━━━━━━━━━━━━\n\n"

    lines = []
    nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    for i, job in enumerate(jobs[:5]):
        # Keep 1, 2, 3, 4, 5 for the /jobs pagination display, though _render_job_line uses [1]
        # But _render_job_line takes `i` and uses `[{i}]`. Let's just pass `i+1` so it prints [1], [2] etc.
        lines.append(_render_job_line(i + 1, job, user, plan))

    footer = "━━━━━━━━━━━━━━━━━━\n"
    if plan == "free":
        footer += escape_md(f"Showing {showing} of {total_count} (Free plan)")

    return header + "".join(lines) + footer


def _render_job_line(i: int, job: dict, user: dict, plan: str) -> str:
    """Helper to render a single job for list/feed views."""
    nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    if i <= len(nums):
        num = nums[i - 1]
    else:
        num = f"[{i}]"
        
    title = escape_md(job.get("title", "Untitled"))
    company = escape_md(job.get("company") or "Unknown Company")
    location = escape_md(job.get("location", "Remote") or "Remote")
    salary = escape_md(job.get("salary", "")) if job.get("salary") else ""
    raw_url = job.get("url", "") or ""
    url = raw_url.strip() if raw_url.strip().startswith("http") else ""
    skills_list = job.get("skills", [])
    skills_text = escape_md(", ".join(s.title() for s in skills_list[:6])) if skills_list else ""

    posted = ""
    posted_raw = job.get("posted_at") or job.get("posted_time")
    if posted_raw:
        from datetime import datetime, timezone
        try:
            if isinstance(posted_raw, str):
                dt = datetime.fromisoformat(posted_raw.replace('Z', '+00:00'))
            else:
                dt = posted_raw
            diff = datetime.now(timezone.utc) - dt
            hours = int(diff.total_seconds() / 3600)
            if hours < 1:
                posted = "⏰ Just now"
            elif hours < 24:
                posted = f"⏰ {hours}h ago"
            else:
                posted = f"⏰ {hours // 24}d ago"
        except Exception:
            pass

    if url:
        safe_url = url.replace("(", "%28").replace(")", "%29")
        line = f"{num}  [{title}]({safe_url}) — {company}\n"
    else:
        line = f"{num}  *{title}* — {company}\n"
        
    job_type = job.get("job_type", "full-time")
    duration = job.get("duration")
    
    subtitle_parts = [f"📍 {location}"]
    if job_type.lower() == "internship":
        if duration:
            subtitle_parts.append(escape_md(f"🎓 Internship ({duration})"))
        else:
            subtitle_parts.append("🎓 Internship")
    elif job_type.lower() != "full-time":
        subtitle_parts.append(escape_md(f"💼 {job_type.title()}"))
        
    if salary:
        subtitle_parts.append(f"💰 {salary}")
        
    subtitle_joined = " \\| ".join(subtitle_parts)
    line += f"     {subtitle_joined}\n"
    if skills_text:
        line += f"     🏷 {skills_text}\n"
    
    if user is not None:
        job_exp = job.get("experience_required") or job.get("min_yoe") or 0
        details = compute_manual_job_match(user, job)
        score = details["score"]
        matched_skills = details["matched"]
        missing_skills = details["missing"]
        exp_note = details.get("exp_note")
        
        if plan in ("pro", "trial"):
            if score >= 70:
                match_text = f"🟢 High match \\({score}%\\)"
            elif score >= 40:
                match_text = f"🟡 Medium match \\({score}%\\)"
            else:
                match_text = f"🔴 Low match \\({score}%\\)"
            
            line += f"     {match_text}\n"
            
            if matched_skills:
                m_text = ", ".join(s.title() for s in matched_skills[:4])
                line += f"     ✅ Match: {escape_md(m_text)}\n"
            if missing_skills:
                ms_text = ", ".join(s.title() for s in missing_skills[:3])
                line += f"     ⚠️ Missing: {escape_md(ms_text)}\n"
            
            if exp_note:
                if "gap" in exp_note.lower():
                    if "partial" in exp_note.lower():
                        line += f"     💡 Slight experience gap \\({escape_md(str(job_exp))}\\+ yrs req\\)\n"
                    else:
                        line += f"     💡 Experience gap \\({escape_md(str(job_exp))}\\+ yrs req\\)\n"
                else:
                    line += f"     ✅ Experience matches \\({escape_md(str(job_exp))}\\+ yrs\\)\n"
                    
            batch_req = job.get("batch_required")
            if batch_req and str(batch_req).lower() != "any":
                line += f"     🎓 Batch: {escape_md(str(batch_req))}\n"
                
        elif plan == "free":
            if score >= 70:
                line += "     🟢 High match  🔒\n"
                line += "     \\[Upgrade to see breakdown\\]\n"
            elif score >= 40:
                line += "     🟡 Partial match  🔒\n"
                line += "     \\[See which skills you're missing → Pro\\]\n"
            else:
                line += "     🔴 Low match  🔒\n"
                line += "     \\[See what you're missing → Pro\\]\n"

    if posted:
        line += f"     {escape_md(posted)}\n"
    line += "\n"
    return line


def format_daily_feed_message(jobs: list[dict], plan: str, total_count: int, user: dict) -> str:
    """Format the 12-job curated daily alert feed."""
    header = "📅 *Your Curated Daily Feed*\n"
    header += "━━━━━━━━━━━━━━━━━━\n\n"
    
    top_picks = jobs[:5]
    good_matches = jobs[5:12]
    
    lines = []
    
    if top_picks:
        lines.append("🎯 *Top Picks*\n\n")
        for i, job in enumerate(top_picks, 1):
            lines.append(_render_job_line(i, job, user, plan))
            
    if good_matches:
        lines.append("⚡ *Good Matches*\n\n")
        for i, job in enumerate(good_matches, len(top_picks) + 1):
            lines.append(_render_job_line(i, job, user, plan))

    footer = "━━━━━━━━━━━━━━━━━━\n"
    
    remaining = max(0, total_count - 12)
    if plan == "free":
        footer += f"🔒 \\+{remaining} more jobs available today\n"
        footer += "*Upgrade to unlock*\n"
    else:
        footer += f"✅ Showing top 12 matches\n"
        if remaining > 0:
            footer += f"\\+{remaining} more available \\(use /jobs command with filters to explore\\)\n"

    return header + "".join(lines) + footer




def job_detail_message(job: dict, plan: str = "free", user: dict = None) -> str:
    """Format single job detail view."""
    title = escape_md(job.get("title", "Untitled"))
    company = escape_md(job.get("company", "Unknown"))
    location = escape_md(job.get("location", "Remote") or "Remote")
    salary = escape_md(job.get("salary", "")) if job.get("salary") else "Not specified"
    job_type = job.get("job_type", "full-time")
    duration = job.get("duration")
    
    subtitle_parts = [f"📍 {location}"]
    if job_type.lower() == "internship":
        if duration:
            subtitle_parts.append(escape_md(f"🎓 Internship ({duration})"))
        else:
            subtitle_parts.append("🎓 Internship")
    elif job_type.lower() != "full-time":
        subtitle_parts.append(escape_md(f"💼 {job_type.title()}"))
        
    if job.get("salary"):
        subtitle_parts.append(f"💰 {salary}")
    else:
        subtitle_parts.append("💰 Not specified")
        
    subtitle_str = " \\| ".join(subtitle_parts)
    
    posted_raw = job.get("posted_time") or job.get("posted_at")
    posted_str = ""
    if posted_raw:
        from datetime import datetime, timezone
        try:
            if isinstance(posted_raw, str):
                dt = datetime.fromisoformat(posted_raw.replace('Z', '+00:00'))
            else:
                dt = posted_raw
            days = (datetime.now(timezone.utc) - dt).days
            if days == 0:
                posted_str = "⏰ Posted Today\n"
            else:
                posted_str = f"⏰ Posted {days}d ago\n"
        except Exception:
            # Fallback if parsing fails
            posted_str = f"⏰ Posted {escape_md(str(posted_raw))}\n"

    raw_url = job.get("url", "") or ""
    url = raw_url.strip() if raw_url.strip().startswith("http") else ""
    exp_req = job.get("experience_required")
    skills_list = job.get("skills", [])
    
    if skills_list:
        skills_text = escape_md(" • ".join(s.title() for s in skills_list))
    else:
        skills_text = "None listed"

    batch_str = ""
    batch_req = job.get("batch_required")
    if batch_req and str(batch_req).lower() != "any":
        batch_str = f"\n🎓 Batch: {escape_md(str(batch_req))}"
        
    match_section = ""
    if user is not None:
        job_exp = job.get("experience_required") or job.get("min_yoe") or 0
        if job.get("is_manual"):
            details = compute_manual_job_match(user, job)
        else:
            user_skills = user.get("skills", [])
            user_exp = str(user.get("experience_level", "0"))
            details = compute_match_details(user_skills, skills_list, user_exp, job_exp)

        score = details["score"]
        matched_skills = details["matched"]
        missing_skills = details["missing"]
        exp_note = details.get("exp_note")

        if plan in ("pro", "trial"):
            if score >= 70:
                badge = f"🟢 High match \\({score}%\\)"
            elif score >= 40:
                badge = f"🟡 Medium match \\({score}%\\)"
            else:
                badge = f"🔴 Low match \\({score}%\\)"
            
            match_section += f"\n\n🎯 *Match Insight*\n\n{badge}\n"
            
            if matched_skills:
                m_text = ", ".join(s.title() for s in matched_skills)
                match_section += f"✅ You match: {escape_md(m_text)}\n"
            if missing_skills:
                ms_text = ", ".join(s.title() for s in missing_skills)
                match_section += f"⚠️ Missing: {escape_md(ms_text)}\n"
                
            if exp_note:
                if "gap" in exp_note.lower():
                    if "partial" in exp_note.lower():
                       match_section += f"\n💡 Slight experience gap \\({escape_md(str(job_exp))}\\+ yrs required\\)\n"
                    else:
                        match_section += f"\n💡 Experience gap \\({escape_md(str(job_exp))}\\+ yrs required\\)\n"
                else:
                    match_section += f"\n✅ Experience matches \\({escape_md(str(job_exp))}\\+ yrs\\)\n"
        else:
            if score >= 70:
                match_section = (
                    "\n\n🎯 *Match Insight*\n\n"
                    "👆 *You're a strong match for this one\\.*\n"
                    "Upgrade to see your full skill breakdown\\.\n"
                )
            elif score >= 40:
                match_section = (
                    "\n\n🎯 *Match Insight*\n\n"
                    "⚠️ *You're a partial match for this one\\.*\n"
                    "Upgrade to see which skills you're missing\\.\n"
                )
            else:
                match_section = (
                    "\n\n🎯 *Match Insight*\n\n"
                    "⚠️ *You might be underqualified for this one\\.*\n"
                    "Upgrade to see which skills you're missing\\.\n"
                )

    return (
        f"*{title} \\- {company}*\n\n"
        f"{subtitle_str}\n"
        f"{posted_str}\n"
        f"🏷 *Skills*\n{skills_text}\n"
        f"{batch_str}"
        f"{match_section}\n"
        f"*Job link:* [{escape_md(url)}]({url.replace('(', '%28').replace(')', '%29')})\n\n" if url else "*Job link:* Not available\n\n"
        "What would you like to do?"
    )


def no_jobs_found() -> str:
    return (
        "😔 *No matching jobs found today*\n\n"
        "Try updating your skills or location in ⚙️ Settings\\.\n"
        "I'll keep searching and notify you when new jobs match\\!"
    )


# ──────────────────────────────────────────────
# Cover Letter
# ──────────────────────────────────────────────

def generating_cover_letter(mode_display: str) -> str:
    return f"⏳ Generating your cover letter\\.\\.\\.\n\n{escape_md(mode_display)}\n\\(This takes a few seconds\\)"


def cover_letter_result(job_title: str, company: str, letter: str, footer: str = "") -> str:
    title = escape_md(f"{job_title} — {company}")
    body = letter.replace("\\", "\\\\").replace("`", "\\`")
    
    msg = (
        f"✅ *Your Cover Letter — {title}*\n\n"
        f"```text\n{body}\n```\n\n"
        "👆 *Tap the box above to instantly copy it\\!*\n"
    )
    if footer:
        msg += f"\n{footer}"
    return msg


def cover_letter_limit_hit(used: int, max_cl: int, reset_date: str, pricing: dict | None = None) -> str:
    price_block = _pricing_block(pricing)
    return (
        "You've written your cover letter for today\\.\n\n"
        "Most callbacks come from applications where "
        "the cover letter is tailored — not copy\\-pasted\\. "
        "With 1/day you can only properly apply to 1 job\\.\n\n"
        "Pro members average 4 tailored applications per day\\. "
        "That's 4x more shots at getting hired\\.\n\n"
        f"{price_block}\n"
        f"_Resets: {escape_md(reset_date)}_"
    )


def no_resume_error() -> str:
    return (
        "📄 Please upload your resume first with /resume\\. "
        "I need it to write a personalised cover letter\\."
    )


def quality_mode_upgrade() -> str:
    return (
        "✨ Quality mode uses Llama 3 70B for richer writing\\.\n"
        "Available on *Pro\\+* \\(₹699/mo\\) and *Premium*\\."
    )


# ──────────────────────────────────────────────
# Auto-Apply
# ──────────────────────────────────────────────




# ──────────────────────────────────────────────
# Resume
# ──────────────────────────────────────────────

def resume_status(filename: str | None, uploaded: bool) -> str:
    if uploaded and filename:
        return (
            f"📄 *Your Resume*\n\n"
            f"Status: ✅ Uploaded \\({escape_md(filename)}\\)\n\n"
            "What would you like to do?"
        )
    return (
        "📄 *Resume*\n\n"
        "You haven't uploaded your resume yet\\.\n\n"
        "Upload it once — I'll use it for every cover letter "
        "and auto\\-apply automatically\\.\n\n"
        "Send me your resume as a PDF file \\(max 5MB\\)\\."
    )


def resume_uploaded_success(filename: str) -> str:
    return f"✅ Resume uploaded successfully\\! \\({escape_md(filename)}\\)"


# ──────────────────────────────────────────────
# ATS Analyzer
# ──────────────────────────────────────────────

def ats_result(result: dict) -> str:
    score = result["score"]
    bar = "\U0001f7e9" * (score // 10) + "\u2b1c" * (10 - score // 10)

    # Safely escape each keyword individually before joining
    def safe_list(items: list) -> str:
        return escape_md(", ".join(str(i) for i in items))

    matching = safe_list(result.get("matching_keywords", [])[:8])
    missing = safe_list(result.get("missing_keywords", [])[:8])
    tech_found = safe_list(result.get("tech_match", {}).get("found", [])[:6])
    tech_missing = safe_list(result.get("tech_match", {}).get("missing", [])[:6])

    # Escape each suggestion line independently
    suggestions = "\n".join(
        f"• {escape_md(str(s))}" for s in result.get("suggestions", [])
    )

    matching_line = f"✅ *Matching:* {matching}" if matching else "✅ *Matching:* None"
    missing_line = f"❌ *Missing:* {missing}" if missing else "❌ *Missing:* None"
    tech_found_line = f"🔧 *Tech Found:* {tech_found}" if tech_found else "🔧 *Tech Found:* None"
    tech_missing_line = f"⚠️ *Tech Missing:* {tech_missing}" if tech_missing else ""

    msg = (
        f"📊 *ATS Match Score: {score}%*\n"
        f"{bar}\n\n"
        f"{matching_line}\n"
        f"{missing_line}\n\n"
        f"{tech_found_line}\n"
    )
    if tech_missing_line:
        msg += f"{tech_missing_line}\n"
    if suggestions:
        msg += f"\n💡 *Suggestions:*\n{suggestions}"
    return msg


# ──────────────────────────────────────────────
# Upgrade
# ──────────────────────────────────────────────

def _pricing_block(pricing: dict | None) -> str:
    """Helper: returns the early adopter or regular pricing block for limit messages."""
    if not pricing:
        return ""
    if pricing.get("is_early_adopter_active"):
        price = pricing['current_price']
        reg = pricing['regular_price']
        days = pricing['days_remaining']
        return (
            f"🔥 Early adopter offer: ₹{price}/mo\n"
            f"Regular price after {days} days: ₹{reg}/mo"
        )
    return f"Pro: ₹{pricing.get('current_price', 499)}/mo"


def upgrade_early_adopter_message(pricing: dict) -> str:
    """Dynamic upgrade message shown during early adopter period."""
    ea_price = pricing['early_adopter_price']
    reg_price = pricing['regular_price']
    slots_left = pricing.get('slots_remaining', 200)

    return (
        f"🔥 *Early Adopter Offer*\n\n"
        f"*₹{ea_price}/month* \\(regular price ~₹{reg_price}~\\)\n"
        f"Lock this price in forever, it won't increase for you\\.\n\n"
        f"⏳ _Only {pricing.get('slots_remaining', 200)} of 200 early adopter slots remaining_\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*🎯 Why upgrade?*\n\n"
        "🚀 Apply to more relevant jobs faster\n"
        "🧠 Improve your resume match before applying\n"
        "📨 Generate tailored cover letters instantly\n"
        "⏰ Never miss follow\\-ups or opportunities\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*🔓 What you unlock*\n\n"
        "✅ Unlimited job alerts daily\n"
        "✅ Full job match scores\n"
        "✅ AI cover letters \\(10/day\\)\n"
        "✅ Resume ATS checks \\(5/day\\)\n"
        "✅ Application tracker \\+ reminders\n"
        "✅ Improved AI \\(Llama 3 70B\\)\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "_Built for devs who are serious about getting interviews faster\\._ 💡\n\n"
        "*Cancel anytime\\. No hidden charges\\.*"
    )


def upgrade_regular_message(pricing: dict) -> str:
    """Dynamic upgrade message after early adopter period ends."""
    price = pricing.get('current_price', 499)
    return (
        f"💎 *Froncy Pro — ₹{price}/month*\n\n"
        "*What you unlock:*\n"
        "✅ Unlimited web dev jobs daily\n"
        "✅ Full match scores on every listing\n"
        "✅ 10 tailored cover letters/day\n"
        "✅ 5 ATS checks/day\n"
        "✅ Application tracker \\+ 7\\-day reminders\n"
        "✅ Llama 3 70B \\(better AI quality\\)\n\n"
        "Less than one dinner out\\. ☕"
    )


def upgrade_plans(current_plan: str) -> str:
    """Legacy fallback — handlers now call upgrade_early_adopter_message or upgrade_regular_message."""
    return (
        "💎 *Upgrade to Pro*\n\n"
        "*What you unlock:*\n"
        "✅ Unlimited web dev jobs daily\n"
        "✅ Full match scores on every listing\n"
        "✅ 10 tailored cover letters/day\n"
        "✅ 5 ATS checks/day\n"
        "✅ Application tracker \\+ 7\\-day reminders\n\n"
        "All for less than a cup of chai\\. ☕"
    )


# ──────────────────────────────────────────────
# Settings & Status
# ──────────────────────────────────────────────

def settings_menu() -> str:
    return "⚙️ *Settings*\n\nWhat would you like to change?"


def user_status(user: dict) -> str:
    from datetime import datetime, timezone

    plan = user.get("plan", "free")
    is_trial = user.get("is_trial", False)
    trial_expires = user.get("trial_expires_at")

    # ── Plan badge ──
    if plan == "pro" and not is_trial:
        early_tag = " 🔒 Early Adopter" if user.get("is_early_adopter") else ""
        expires_at = user.get("plan_expires_at")
        date_str = expires_at.strftime("%b %d, %Y") if expires_at else "Unknown"
        sub_status = user.get("subscription_status", "")
        if sub_status == "cancelled":
            plan_label = escape_md(f"⭐ Pro{early_tag} — active till {date_str} (Cancelled)")
        else:
            plan_label = escape_md(f"⭐ Pro{early_tag} — renews {date_str}")
    elif is_trial and trial_expires:
        now = datetime.now(timezone.utc)
        remaining = trial_expires - now
        hours = max(0, int(remaining.total_seconds() / 3600))
        if hours > 0:
            plan_label = escape_md(f"⚡ Pro Trial — {hours}h left")
        else:
            plan_label = escape_md("🆓 Free (trial ended)")
            plan = "free"  # treat as free for limit display
            is_trial = False
    elif plan == "proplus":
        plan_label = "🚀 Pro\\+"
    elif plan == "premium":
        plan_label = "💎 Premium"
    else:
        plan_label = "🆓 Free"

    # ── Skills ──
    skills = escape_md(", ".join(user.get("skills", []))) or "None"

    # ── Role ──
    role_pref = user.get("role_pref")
    role_display = escape_md(str(role_pref).title()) if role_pref else "Fullstack"

    # ── Location ──
    loc_map = {"remote": "🌏 Remote", "india": "🇮🇳 India", "both": "🌐 Both"}
    location = escape_md(loc_map.get(user.get("location_pref", "remote"), "Remote"))

    # ── Alert time ──
    alert_time = escape_md(user.get("alert_time", "09:00"))

    # ── Experience ──
    exp_raw = user.get("experience_level", "0") or "0"
    exp_display_map = {"0": "Fresher (0 yrs)", "1": "1 Year", "2": "2 Years", "3_5": "3–5 Years", "5_plus": "5+ Years", "5+": "5+ Years"}
    exp_display = escape_md(exp_display_map.get(str(exp_raw), str(exp_raw)))

    # ── Batch year ──
    batch_year = user.get("batch_year")
    batch_display = escape_md(str(batch_year)) if batch_year else "Not set"

    # ── Cover letters ──
    cl_used = user.get("cover_letters_today", 0) or 0
    if plan in ("proplus", "premium"):
        cl_label = f"{cl_used}/∞ today"
    elif plan == "pro" or is_trial:
        cl_label = f"{cl_used}/10 today"
    else:
        cl_label = f"{cl_used}/1 today"

    # ── ATS checks ──
    ats_used = user.get("ats_checks_today", 0) or 0
    if plan in ("proplus", "premium"):
        ats_label = f"{ats_used}/∞ today"
    elif plan == "pro" or is_trial:
        ats_label = f"{ats_used}/5 today"
    else:
        ats_label = f"{ats_used}/1 today"

    resume_status = "✅ Uploaded" if user.get("resume_text") else "❌ Not uploaded"

    return (
        f"📊 *Your Status*\n\n"
        f"*Plan:* {plan_label}\n"
        f"*Role:* {role_display}\n"
        f"*Skills:* {skills}\n"
        f"*Location:* {location}\n"
        f"*Alert Time:* {alert_time} IST\n"
        f"*Resume:* {resume_status}\n"
        f"*YOE:* {exp_display}\n"
        f"*Batch:* {batch_display}\n\n"
        f"*Cover Letters:* {escape_md(cl_label)}\n"
        f"*ATS Checks:* {escape_md(ats_label)}"
    )


def confirm_delete() -> str:
    return (
        "⚠️ *Delete Account*\n\n"
        "This will permanently delete:\n"
        "• Your profile and preferences\n"
        "• Saved jobs and application history\n"
        "• Uploaded resume\n\n"
        "*This action cannot be undone\\!*"
    )


def account_deleted() -> str:
    return "✅ Your account and all data have been permanently deleted\\. Goodbye\\! 👋"


# ──────────────────────────────────────────────
# Error Messages
# ──────────────────────────────────────────────

def error_ai_failed() -> str:
    return "❌ Sorry, I couldn't generate your cover letter right now\\. Please try again in a minute\\. \\(/coverletter\\)"


def error_job_not_found() -> str:
    return "❌ This job listing may have been removed\\."


def error_rate_limit() -> str:
    return "⏳ Slow down\\! Please wait 30 seconds before trying again\\."


def error_subscription_expired() -> str:
    return "⚠️ Your plan has expired\\. Renew to continue using premium features\\."


def help_message() -> str:
    return (
        "ℹ️ *FroncyBot Help*\n\n"
        "*Commands:*\n"
        "/start — Open bot / main menu\n"
        "/menu — Show main menu\n"
        "/jobs — View today's job listings\n"
        "/coverletter — Generate a cover letter\n"
        "/resume — Manage your resume\n"
        "/saved — View saved jobs\n"
        "/settings — Change preferences\n"
        "/upgrade — View subscription plans\n"
        "/status — Your plan \\& usage stats\n"
        "/help — This help message\n"
        "/cancel — Cancel current flow\n"
        "/delete\\_account — Delete all your data"
    )
