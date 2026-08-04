"""
Helper utilities — shared across handlers and services.
"""
import re
import hashlib

from datetime import datetime, timezone

def get_effective_plan(user: dict) -> str:
    """Returns 'free' if the user is on trial but it has expired, otherwise returns user.plan."""
    if not user:
        return "free"
    plan = user.get("plan", "free")
    is_trial = user.get("is_trial", False)
    
    if is_trial:
        trial_expires = user.get("trial_expires_at")
        if trial_expires and trial_expires <= datetime.now(timezone.utc):
            return "free"
    return plan
def escape_md(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2.
    Characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    if not text:
        return ""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for char in str(text):
        if char in special_chars:
            escaped += f"\\{char}"
        else:
            escaped += char
    return escaped


def detect_portal_type(url: str) -> str:
    """Detect if a job URL is from a supported auto-apply portal."""
    if not url:
        return "other"
    url_lower = url.lower()
    if "boards.greenhouse.io" in url_lower or "greenhouse.io" in url_lower:
        return "greenhouse"
    if "jobs.lever.co" in url_lower or "lever.co" in url_lower:
        return "lever"
    if "apply.workable.com" in url_lower or "workable.com" in url_lower:
        return "workable"
    return "other"


def normalize_job_url(url: str) -> str:
    """Normalize a URL for deduplication by stripping scheme, www, query params, and trailing slashes."""
    if not url:
        return ""
    
    # Remove http:// or https://
    url = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    
    # Remove www.
    if url.lower().startswith("www."):
        url = url[4:]
        
    # Remove query params
    if "?" in url:
        url = url.split("?")[0]
        
    # Remove trailing slashes
    url = url.rstrip("/")
    
    return url


def hash_url(url: str) -> str:
    """Generate MD5 hash of a URL for deduplication."""
    return hashlib.md5(url.strip().lower().encode()).hexdigest()


def format_salary(salary_str: str | None) -> str:
    """Normalize salary display."""
    if not salary_str:
        return ""
    return salary_str.strip()


# Plan hierarchy for access checks
PLAN_LEVELS = {
    "free": 0,
    "pro": 1,
    "proplus": 2,
    "premium": 3,
}


def check_plan_access(user_plan: str, required_plan: str) -> bool:
    """Check if user's plan level meets the required minimum."""
    user_level = PLAN_LEVELS.get(user_plan, 0)
    required_level = PLAN_LEVELS.get(required_plan, 0)
    return user_level >= required_level


def get_plan_limits(plan: str) -> dict:
    """Get feature limits for a given plan."""
    limits = {
        "free": {
            "jobs_per_day": 5,
            "cover_letters_per_month": 3,
            "auto_applies_per_day": 0,
            "saved_jobs_max": 10,
            "quality_mode": False,
            "ats_analyzer": False,
            "salary_insights": False,
        },
        "pro": {
            "jobs_per_day": 20,
            "cover_letters_per_month": 999999,  # unlimited
            "auto_applies_per_day": 0,
            "saved_jobs_max": 50,
            "quality_mode": False,
            "ats_analyzer": False,
            "salary_insights": False,
        },
        "proplus": {
            "jobs_per_day": 20,
            "cover_letters_per_month": 999999,
            "auto_applies_per_day": 0,
            "saved_jobs_max": 50,
            "quality_mode": True,
            "ats_analyzer": True,
            "salary_insights": True,
        },
        "premium": {
            "jobs_per_day": 20,
            "cover_letters_per_month": 999999,
            "auto_applies_per_day": 10,
            "saved_jobs_max": 100,
            "quality_mode": True,
            "ats_analyzer": True,
            "salary_insights": True,
        },
    }
    return limits.get(plan, limits["free"])


def split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into first and last name."""
    parts = full_name.strip().split(maxsplit=1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return first, last


def normalize_skills(skills: list[str]) -> list[str]:
    """
    Normalize a list of skills to standard casing/naming for better DB matching.
    e.g., 'node' -> 'node.js', 'js' -> 'javascript'.
    """
    mapping = {
        "node": "node.js",
        "nodejs": "node.js",
        "js": "javascript",
        "ts": "typescript",
        "reactjs": "react",
        "react.js": "react",
        "vuejs": "vue",
        "vue.js": "vue",
        "next": "next.js",
        "nextjs": "next.js",
        "mongodb": "mongoDB",
        "mongo": "mongoDB",
        "postgres": "postgresql",
        "pgsql": "postgresql",
        "mysql": "mySQL",
        "expressjs": "express",
        "html5": "html",
        "css3": "css",
        "tailwind css": "tailwind",
        "tailwindcss": "tailwind",
        "graphql": "graphQL",
        "redis": "redis"
    }

    normalized = []
    for skill in skills:
        cleaned = skill.strip().lower()
        if not cleaned:
            continue
        # Apply mapping or title case default
        mapped = mapping.get(cleaned)
        if mapped:
            normalized.append(mapped)
        else:
            normalized.append(cleaned.title())

    # Return unique normalized skills
    return list(dict.fromkeys(normalized))
