"""
Role configuration — maps user-selected roles to matching job title/skill keywords.
This is the single source of truth for role-based filtering across the whole app.
"""

import re
from functools import lru_cache

# All supported roles a user can pick during onboarding
ACTIVE_ROLES = [
    "frontend", "backend", "fullstack", "devops", "mobile", "data", "other"
]

ACTIVE_EXPERIENCE = ["0", "1", "2", "3-5", "5+"]

# ── Unified Stream Taxonomy (RFC-010 Specification) ───────────────────────────
STREAM_TAXONOMY = {
    "frontend": {
        "titles": [
            "frontend", "front-end", "front end", "ui developer", "ui engineer",
            "web developer", "react developer", "angular developer", "vue developer",
        ],
        "core_skills": [
            "react", "vue", "angular", "next.js", "nextjs", "svelte", "html", "css",
            "tailwind", "redux", "vite",
        ],
        "neutral_skills": ["typescript", "javascript"],
    },
    "backend": {
        "titles": [
            "backend", "back-end", "back end", "server-side", "api developer",
            "java developer", "python developer", "golang developer", "node developer",
            "ruby developer", "php developer", "c++ developer", ".net developer",
        ],
        "core_skills": [
            "node.js", "express", "django", "fastapi", "spring boot", "golang", "rust",
            "postgresql", "mysql", "mongodb", "redis", "microservices", "c++", ".net",
            "c#", "graphql", "kafka",
        ],
        "neutral_skills": ["python", "java", "sql", "rest apis", "docker"],
    },
    "fullstack": {
        "titles": [
            "fullstack", "full-stack", "full stack", "mern",
        ],
        "core_skills": [
            "react", "node.js", "next.js", "django", "fastapi", "spring boot", "express",
        ],
        "neutral_skills": ["typescript", "javascript", "python", "sql", "rest apis", "docker"],
    },
    "data_ml": {
        "titles": [
            "data scientist", "machine learning", "ml engineer", "ai engineer",
            "ai/ml", "deep learning", "nlp engineer", "computer vision",
            "llm engineer", "genai engineer", "ai researcher", "applied scientist",
        ],
        "core_skills": [
            "machine learning", "deep learning", "nlp", "computer vision",
            "pytorch", "tensorflow", "scikit-learn", "langchain", "langgraph",
            "rag", "llms", "hugging face", "transformers", "keras",
        ],
        "neutral_skills": ["python", "pandas", "numpy", "sql"],
    },
    "data_eng": {
        "titles": [
            "data engineer", "analytics engineer", "etl developer",
            "data warehouse engineer", "big data engineer", "bi engineer",
            "database administrator", "dba",
        ],
        "core_skills": [
            "spark", "hadoop", "airflow", "kafka", "dbt", "snowflake",
            "databricks", "bigquery", "data pipelines", "data warehousing",
            "redshift", "power bi", "tableau",
        ],
        "neutral_skills": ["sql", "python", "pandas"],
    },
    "devops": {
        "titles": [
            "devops", "dev ops", "sre", "site reliability", "cloud engineer",
            "platform engineer", "infrastructure engineer", "systems engineer",
        ],
        "core_skills": [
            "docker", "kubernetes", "k8s", "terraform", "ansible", "aws", "azure",
            "gcp", "ci/cd", "jenkins", "linux", "helm", "prometheus", "grafana",
        ],
        "neutral_skills": ["bash", "git", "python"],
    },
    "mobile": {
        "titles": [
            "mobile developer", "mobile engineer", "android developer", "ios developer",
            "flutter developer", "react native developer", "mobile app developer",
        ],
        "core_skills": [
            "android", "ios", "react native", "flutter", "kotlin", "swift",
            "jetpack compose", "swiftui",
        ],
        "neutral_skills": [],
    },
    "other": {
        "titles": [],
        "core_skills": [],
        "neutral_skills": [],
    }
}

@lru_cache(maxsize=2048)
def compile_token_pattern(token: str) -> re.Pattern:
    """
    Compiles token with strict word-boundary or lookaround regex.
    Tokens containing non-alphanumeric punctuation (e.g. c++, .net, ci/cd, ai/ml, server-side)
    use non-word character lookarounds so symbols are preserved cleanly.
    """
    t = token.strip().lower()
    if re.search(r"[^a-z0-9\s]", t):
        return re.compile(rf"(?<![\w]){re.escape(t)}(?![\w])", re.IGNORECASE)
    else:
        return re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)

GENERIC_TITLE_WORDS = {"developer", "engineer", "specialist", "programmer", "architect", "lead", "senior", "junior", "role", "job"}

@lru_cache(maxsize=1024)
def resolve_user_stream_cached(raw_role: str, has_ml_skills: bool = False, has_eng_skills: bool = False) -> tuple:
    """Cached stream resolver. Input raw_role must be pre-normalized."""
    r_lower = " ".join(raw_role.strip().lower().split())
    if r_lower in STREAM_TAXONOMY:
        return (r_lower, (), False)
    
    if r_lower == "data":
        if has_ml_skills:
            return ("data_ml", (), False)
        elif has_eng_skills:
            return ("data_eng", (), False)
        return ("data_ml", (), False)  # Default for data stream is AI/ML Data Science

    # Custom role handling
    words = [w for w in re.split(r"[\s/,-]+", r_lower) if w and w not in GENERIC_TITLE_WORDS]
    if not words:
        words = [r_lower]
        
    # Check affiliation based on domain keywords
    affil = "other"
    for w in words:
        if w in {"java", "python", "golang", "go", "rust", "backend", "api", "node", "django", "spring"}:
            affil = "backend"
            break
        elif w in {"react", "vue", "angular", "frontend", "ui", "web"}:
            affil = "frontend"
            break
        elif w in {"ml", "ai", "machine", "deep", "nlp", "vision", "data", "scientist"}:
            affil = "data_ml"
            break
        elif w in {"etl", "spark", "hadoop", "warehouse", "bi", "analytics"}:
            affil = "data_eng"
            break
        elif w in {"devops", "cloud", "sre", "infra", "kubernetes", "docker", "aws", "azure"}:
            affil = "devops"
            break
        elif w in {"android", "ios", "flutter", "mobile"}:
            affil = "mobile"
            break

    return (affil, tuple(words), True)

def resolve_user_stream(role_pref: str, user_skills: list[str] = None) -> dict:
    """
    Resolves user's role preference to canonical stream and extracted keywords.
    Differentiates legacy 'data' into 'data_ml' or 'data_eng' based on user skills.
    """
    clean_role = (role_pref or "fullstack").strip()
    skills_set = {str(s).lower().strip() for s in (user_skills or []) if s}
    has_ml = bool(skills_set & set(STREAM_TAXONOMY["data_ml"]["core_skills"]))
    has_eng = bool(skills_set & set(STREAM_TAXONOMY["data_eng"]["core_skills"]))
    stream, words, is_custom = resolve_user_stream_cached(clean_role, has_ml, has_eng)
    return {
        "stream": stream,
        "custom_keywords": list(words),
        "is_custom": is_custom
    }

def classify_job_streams(title: str, role_category: str = "", skills: list[str] = None) -> set[str]:
    """
    Deterministic multi-stream job classifier based on Title and Core Skills.
    Returns the set of streams this job belongs to.
    """
    streams = set()
    t_clean = (title or "").lower()
    cat_clean = (role_category or "").lower()
    s_list = [str(s).lower().strip() for s in (skills or []) if s]

    for stream, tax in STREAM_TAXONOMY.items():
        if stream == "other":
            continue
        # Title & Category Check
        for pat_str in tax["titles"]:
            if compile_token_pattern(pat_str).search(t_clean) or (cat_clean and compile_token_pattern(pat_str).search(cat_clean)):
                streams.add(stream)
                break
        
        # Skill Check (if not already matched by title)
        if stream not in streams and s_list:
            core_hits = sum(1 for cs in tax["core_skills"] if any(compile_token_pattern(cs).search(s) for s in s_list))
            if core_hits >= 2:
                streams.add(stream)
            elif stream in ("mobile", "devops") and core_hits >= 1:
                streams.add(stream)

    if "frontend" in streams and "backend" in streams:
        streams.add("fullstack")
    if "fullstack" in streams:
        streams.add("frontend")
        streams.add("backend")

    if not streams:
        streams.add("other")
    return streams

def compute_role_alignment(user_role_info: dict, job: dict) -> int:
    """
    Computes deterministic role alignment percentage (0 to 100) following RFC-010:
      - Rule 1 (Conflicting Title Gate): 0% (if zero stream overlap and opposing title hit)
      - Rule 2 (Explicit Title Match): 100%
      - Rule 3 (Multi-Stream Title Match): 95%
      - Rule 4 (Neutral Title + Core Skills): 85% (>=2 hits) / 70% (1 hit) / 40% (neutral hit)
      - Rule 5 (Fallback): 20%
    """
    user_stream = user_role_info["stream"]
    custom_keywords = user_role_info.get("custom_keywords", [])
    job_streams = classify_job_streams(job.get("title") or "", job.get("role_category") or "", job.get("skills") or [])
    title_lower = (job.get("title") or "").lower()

    # Rule 1: Conflicting Title Gate (Evaluated strictly on Title / Category, never description)
    if user_stream != "other":
        overlap = job_streams & {user_stream, "fullstack", "other"}
        if not overlap:
            is_explicit_conflict = any(
                compile_token_pattern(t).search(title_lower)
                for s, tax in STREAM_TAXONOMY.items()
                if s not in (user_stream, "fullstack", "other")
                for t in tax["titles"]
            )
            if is_explicit_conflict:
                return 0

    # Rule 2: Explicit Title Match (Custom or Canonical Stream)
    if user_role_info.get("is_custom") and custom_keywords:
        if all(compile_token_pattern(kw).search(title_lower) for kw in custom_keywords):
            return 100

    if user_stream in STREAM_TAXONOMY:
        for t in STREAM_TAXONOMY[user_stream]["titles"]:
            if compile_token_pattern(t).search(title_lower):
                return 100

    # Rule 3: Multi-Stream Title Match
    if len(job_streams) > 1 and (user_stream in job_streams or "fullstack" in job_streams):
        return 95

    # Rule 4: Neutral Title + Core Domain Skills
    job_skills_lower = [str(s).lower().strip() for s in (job.get("skills") or []) if s]
    job_desc_lower = (job.get("description") or "").lower()
    
    core_skills = STREAM_TAXONOMY.get(user_stream, {}).get("core_skills", [])
    core_hits = 0
    for cs in core_skills:
        pat = compile_token_pattern(cs)
        if any(pat.search(s) for s in job_skills_lower) or (job_desc_lower and pat.search(job_desc_lower)):
            core_hits += 1

    if core_hits >= 2:
        return 85
    elif core_hits == 1:
        return 70

    neutral_skills = STREAM_TAXONOMY.get(user_stream, {}).get("neutral_skills", [])
    neutral_hits = any(
        compile_token_pattern(ns).search(s)
        for ns in neutral_skills
        for s in job_skills_lower
    )
    if neutral_hits:
        return 40

    return 20

# ── Backward-Compatible Role Keywords Mapping ──────────────────────────────────
# Preserves legacy imports in handlers/admin.py, etc. Cleaned of generic noise.
ROLE_KEYWORDS: dict[str, list[str]] = {
    "frontend": STREAM_TAXONOMY["frontend"]["titles"] + STREAM_TAXONOMY["frontend"]["core_skills"],
    "backend": STREAM_TAXONOMY["backend"]["titles"] + STREAM_TAXONOMY["backend"]["core_skills"],
    "fullstack": STREAM_TAXONOMY["fullstack"]["titles"] + STREAM_TAXONOMY["fullstack"]["core_skills"],
    "devops": STREAM_TAXONOMY["devops"]["titles"] + STREAM_TAXONOMY["devops"]["core_skills"],
    "mobile": STREAM_TAXONOMY["mobile"]["titles"] + STREAM_TAXONOMY["mobile"]["core_skills"],
    "data": (
        STREAM_TAXONOMY["data_ml"]["titles"] + STREAM_TAXONOMY["data_ml"]["core_skills"] +
        STREAM_TAXONOMY["data_eng"]["titles"] + STREAM_TAXONOMY["data_eng"]["core_skills"]
    ),
    "other": [],
}

FRONTEND_SKILLS = ROLE_KEYWORDS["frontend"]
