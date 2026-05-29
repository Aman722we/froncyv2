"""
Niche configuration — single source of truth for ApplixyBot's active focus.
To expand scope in future: add to these lists and uncomment disabled code.
"""

# ── Active niche (current: Frontend Freshers only) ───────────────────────────
ACTIVE_ROLES = ["frontend"]
# FUTURE: ACTIVE_ROLES = ["frontend", "backend", "fullstack"]

ACTIVE_EXPERIENCE = ["0", "1"]
# FUTURE: ACTIVE_EXPERIENCE = ["0", "1", "2", "3-5", "5+"]

# All frontend-related skill keywords (lowercase) used for DB-level filtering
FRONTEND_SKILLS = [
    "html", "css", "javascript", "typescript",
    "react", "nextjs", "next.js", "vue", "angular",
    "svelte", "react native",
    "tailwind", "scss", "bootstrap",
    "figma", "framer",
]
