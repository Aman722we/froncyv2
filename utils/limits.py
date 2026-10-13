PLAN_LIMITS = {
    "free": {
        "jobs_per_day": 5,
        "cover_letters_per_day": 1,
        "ats_checks_per_day": 1,
        "saved_jobs_max": 5,
        "application_tracking_max": 10,
        "job_match_score": False,
        "follow_up_reminders": False,
        "weekly_digest": False,
        "llm_model": "fast",        # Llama 3 8B
    },
    "trial": {
        # Trial = full Pro access for 7 days
        "jobs_per_day": 999,
        "cover_letters_per_day": 10,
        "ats_checks_per_day": 5,
        "saved_jobs_max": 200,
        "application_tracking_max": 999,
        "job_match_score": True,
        "follow_up_reminders": True,
        "weekly_digest": False,  # Too early for weekly digest
        "llm_model": "quality",
    },
    "pro": {
        "jobs_per_day": 999,        # effectively unlimited
        "cover_letters_per_day": 10,
        "saved_jobs_max": 200,
        "application_tracking_max": 999,
        "job_match_score": True,
        "follow_up_reminders": True,
        "weekly_digest": True,
        "llm_model": "quality",     # Llama 3 70B
    },
}


def get_limit(plan: str, feature: str):
    """Get limit for a feature based on plan. Defaults to 'free' for unknown plans."""
    if not plan or plan not in PLAN_LIMITS:
        plan = "free"
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).get(feature)
