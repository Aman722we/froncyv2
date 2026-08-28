"""
Role configuration — maps user-selected roles to matching job title/skill keywords.
This is the single source of truth for role-based filtering across the whole app.
"""

# All supported roles a user can pick during onboarding
ACTIVE_ROLES = [
    "frontend", "backend", "fullstack", "devops", "mobile", "data", "other"
]

ACTIVE_EXPERIENCE = ["0", "1", "2", "3-5", "5+"]

# ── Role → Keywords mapping ────────────────────────────────────────────────────
# Used in db/manual_jobs.py to filter jobs by role_pref.
# A job matches a role if its title or skills contain ANY of these keywords.
ROLE_KEYWORDS: dict[str, list[str]] = {
    "frontend": [
        "frontend", "front-end", "front end", "ui developer", "ui engineer",
        "react", "vue", "angular", "next.js", "nextjs", "svelte",
        "html", "css", "javascript", "typescript", "tailwind",
    ],
    "backend": [
        "backend", "back-end", "back end", "server-side",
        "node.js", "node", "express", "django", "flask", "fastapi",
        "spring", "rails", "laravel", "php", "java developer",
        "python developer", "golang", "rust developer",
        "api developer", "rest api",
    ],
    "fullstack": [
        "fullstack", "full-stack", "full stack",
        "mern", "mean", "lamp",
        "react", "node.js", "django", "rails",
        "frontend", "backend",
    ],
    "devops": [
        "devops", "dev ops", "sre", "site reliability",
        "cloud engineer", "platform engineer", "infrastructure",
        "docker", "kubernetes", "k8s", "terraform", "ansible",
        "aws", "azure", "gcp", "ci/cd", "jenkins",
    ],
    "mobile": [
        "mobile", "android", "ios", "react native", "flutter",
        "kotlin", "swift", "xamarin", "mobile developer",
        "app developer",
    ],
    "data": [
        "data", "machine learning", "ml engineer", "ai engineer",
        "data scientist", "data analyst", "data engineer",
        "python", "r developer", "sql", "spark", "hadoop",
        "tensorflow", "pytorch",
    ],
    "other": [],  # Shows all jobs (no filtering)
}

# Legacy alias kept so old imports don't break immediately
FRONTEND_SKILLS = ROLE_KEYWORDS["frontend"]
