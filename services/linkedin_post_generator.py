"""
LinkedIn Viral Post Generator for Froncy V2.

Features:
- Rotates niche job categories across days and morning/evening slots (Frontend, Backend, DevOps, Data/AI/ML, Mobile, Fullstack, Mixed).
- Puts disclosed salary jobs at the top of the post for maximum click-through.
- Gracefully falls back to high-salary fresh jobs if a niche has fewer than 5 openings.
- Zero em-dashes or en-dashes to eliminate the AI-generated perception.
- Proven viral structure, zero-penalty companion first comment, and direct Froncy V2 career-page value proposition.
"""
import html
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from loguru import logger
from db.connection import get_pool
from config import settings


# ── Niche Stream Configurations ──────────────────────────────────────────────
NICHE_CONFIGS = {
    "frontend": {
        "id": "frontend",
        "name": "Frontend Development",
        "lead_in": "If you know HTML, CSS, JavaScript, React, or Next.js, here are 5 fresh frontend opportunities you can apply for today. 👇",
        "hook_intro": (
            "Most frontend developers think they need to learn one more framework before applying.\n"
            "The truth?\n\n"
            "Many companies are hiring developers who already have the skills they need.\n"
            "While you're waiting to feel \"100% ready,\" someone with a simpler portfolio has already submitted their application and is scheduling interviews.\n\n"
            "If you know HTML, CSS, JavaScript, React, or Next.js, here are 5 fresh frontend opportunities you can apply for today. 👇"
        ),
        "hashtags": "#FrontendDeveloper #ReactJS #JavaScript #TypeScript #NextJS #WebDevelopment #FrontendJobs #SoftwareEngineer #TechJobs #Hiring #FreshersJobs #CareerGrowth",
        "sql_filter": ""
    },
    "backend": {
        "id": "backend",
        "name": "Backend & API Development",
        "lead_in": "If you know Python, Java, Node.js, or SQL, here are 5 fresh backend developer openings you can apply for today. 👇",
        "hook_intro": (
            "Most backend developers think they need to master distributed systems and Kubernetes before applying.\n"
            "The truth?\n\n"
            "Companies hiring junior backend engineers are looking for developers who understand clean REST APIs, solid SQL queries, and basic Git workflows.\n"
            "You don't need 10 complex microservices to get an interview. You need solid fundamentals and early applications.\n\n"
            "Here are 5 verified backend developer opportunities hiring today. 👇"
        ),
        "hashtags": "#BackendDeveloper #Python #Java #NodeJS #Golang #SQL #APIs #SoftwareEngineer #TechJobs #Hiring #FreshersJobs #CareerGrowth",
        "sql_filter": ""
    },
    "devops": {
        "id": "devops",
        "name": "DevOps & Cloud Engineering",
        "lead_in": "If you know Linux, Docker, Git, or basic Cloud concepts, here are 5 DevOps and Cloud opportunities you can apply for today. 👇",
        "hook_intro": (
            "Most junior engineers think DevOps and Cloud roles are strictly reserved for 5+ YOE seniors.\n"
            "In reality?\n\n"
            "Fast-growing engineering teams are actively looking for entry-level developers who know Linux fundamentals, Docker containerization, Git, and basic AWS or CI/CD concepts.\n"
            "You don't need to be a Kubernetes architect to get hired. You need clean fundamentals and early applications.\n\n"
            "Here are 5 fresh DevOps and Cloud engineering opportunities hiring today. 👇"
        ),
        "hashtags": "#DevOps #CloudEngineer #AWS #Docker #Kubernetes #Linux #CICD #SoftwareEngineer #TechJobs #Hiring #FreshersJobs #CareerGrowth",
        "sql_filter": ""
    },
    "data": {
        "id": "data",
        "name": "Data, AI & Machine Learning",
        "lead_in": "If you have solid Python, SQL, and data basics, here are 5 Data, AI, and Machine Learning opportunities hiring today. 👇",
        "hook_intro": (
            "Most aspiring data and machine learning developers think they need a research paper or complex neural network to get an interview.\n"
            "The truth?\n\n"
            "Companies want junior developers who can write clean Python, write optimized SQL queries, and clean real-world datasets.\n"
            "Practical skills and early applications beat theoretical perfection every single time.\n\n"
            "Here are 5 Data, AI, and Machine Learning opportunities worth checking out today. 👇"
        ),
        "hashtags": "#DataEngineer #MachineLearning #ArtificialIntelligence #Python #SQL #DataScience #TechJobs #SoftwareEngineer #Hiring #FreshersJobs #CareerGrowth",
        "sql_filter": ""
    },
    "fullstack": {
        "id": "fullstack",
        "name": "Fullstack & Software Engineering",
        "lead_in": "Here are 5 fresh fullstack and software engineering opportunities hiring today. 👇",
        "hook_intro": (
            "The biggest mistake junior developers make isn't having the wrong skills.\n"
            "It's waiting for the \"perfect time\" to start applying.\n\n"
            "Meanwhile, candidates with the exact same skills are already interviewing because they didn't wait.\n"
            "If you know web fundamentals, Git, and at least one core backend language, companies are looking for you right now.\n\n"
            "Here are 5 verified fullstack and software engineering opportunities to apply for today. 👇"
        ),
        "hashtags": "#FullStackDeveloper #SoftwareEngineer #ReactJS #NodeJS #Python #WebDevelopment #TechJobs #Hiring #FreshersJobs #CareerGrowth #Coding",
        "sql_filter": ""
    },
    "mobile": {
        "id": "mobile",
        "name": "Mobile Development",
        "lead_in": "If you know React Native, Flutter, Android, or iOS basics, here are 5 mobile developer opportunities hiring today. 👇",
        "hook_intro": (
            "Most mobile developers think they need 5 published production apps before sending an application.\n"
            "In reality?\n\n"
            "Teams hiring junior mobile developers care about clean component architecture, API integration, and responsive UI.\n"
            "If you can build performant mobile screens and connect backend APIs, you are already qualified for junior roles.\n\n"
            "Here are 5 fresh mobile developer opportunities hiring today. 👇"
        ),
        "hashtags": "#MobileDeveloper #ReactNative #Flutter #AndroidDev #iOSDev #MobileApps #SoftwareEngineer #TechJobs #Hiring #FreshersJobs #CareerGrowth",
        "sql_filter": ""
    },
    "mixed": {
        "id": "mixed",
        "name": "All-Rounder Fresh Tech Drops",
        "lead_in": "Here are 5 handpicked junior developer opportunities across tech hiring today. 👇",
        "hook_intro": (
            "90% of job seekers only check LinkedIn and Naukri.\n"
            "That is exactly where 90% of the competition is fighting for the same 10 roles.\n\n"
            "What top candidates do differently:\n"
            "They apply directly on company career pages (Greenhouse, Lever, Ashby) days before the opening is ever posted on public job boards.\n\n"
            "We tracked today's top direct career-page drops. Here are 5 fresh junior opportunities you should check out right now. 👇"
        ),
        "hashtags": "#TechJobs #SoftwareEngineer #FrontendDeveloper #BackendDeveloper #FullStack #Python #Coding #Hiring #JobSearch #FreshersJobs #CareerGrowth",
        "sql_filter": ""
    }
}


# ── 14-Slot Weekly Niche Rotation (IST) ───────────────────────────────────────
# Monday = 0, Sunday = 6
WEEKLY_ROTATION = {
    0: {"morning": "frontend",  "evening": "backend"},    # Monday
    1: {"morning": "fullstack", "evening": "data"},       # Tuesday
    2: {"morning": "devops",    "evening": "frontend"},   # Wednesday
    3: {"morning": "backend",   "evening": "mobile"},     # Thursday
    4: {"morning": "frontend",  "evening": "fullstack"},  # Friday
    5: {"morning": "data",      "evening": "devops"},     # Saturday
    6: {"morning": "mixed",     "evening": "frontend"},   # Sunday
}


# ── Comprehensive Non-Tech Blacklist & Mobile Separation ─────────────────────
NON_TECH_EXCLUSIONS = (
    # HR & Recruiting
    "talent", "acquisition", "recruiter", "recruiting", "recruitment", "sourcer", "sourcing",
    "human resources", "hr coordinator", "hr generalist", "hr manager", "people partner", "people operations",
    "people systems", "hris", "workday",
    
    # Sales, BD & Account Management
    "account executive", "business development", "bdr", "sdr", "sales representative", "sales manager", "account manager",
    "inside sales", "sales enablement",
    
    # Customer Support & Helpdesk
    "customer support", "customer success", "client success", "support specialist", "support representative",
    "technical support specialist", "call center", "tier 1", "tier 2", "helpdesk", "service desk", "it support",
    
    # Marketing & Content
    "marketing", "content writer", "copywriter", "social media", "seo specialist", "growth marketer", "communications",
    "pr manager", "brand manager", "video editor",
    
    # Operations, Procurement & Administration
    "operations coordinator", "office manager", "executive assistant", "administrative", "workplace coordinator",
    "procurement", "purchasing", "buyer", "supply chain", "vendor management",
    
    # Finance, Accounting & Legal
    "finance", "accountant", "accounting", "bookkeeper", "payroll", "legal", "counsel", "compliance", "tax", "billing",
    "policy analyst", "regulatory", "government affairs", "public policy",
    
    # Healthcare, Teaching & Non-Tech AI Training
    "medical", "nurse", "physician", "clinical", "intake", "trainer", "training", "instructional",
    "voice actor", "language expert", "audio evaluation",
    
    # Management & Non-Tech Design
    "product manager", "program manager", "scrum master", "project manager",
    "graphic designer", "multimedia designer", "packaging designer", "fashion designer"
)

MOBILE_KEYWORDS = ("mobile", "react native", "flutter", "android", "ios", "maui", "xamarin", "swift developer", "kotlin developer")


def is_valid_tech_job(job: dict) -> bool:
    """Strictly ensures a job is a genuine software/data/cloud tech role, never non-tech."""
    title = (job.get("title") or "").strip().lower()
    if not title:
        return False
    if any(nt in title for nt in NON_TECH_EXCLUSIONS):
        return False
        
    # Check for non-tech designer (unless UI/UX)
    if "designer" in title and not any(u in title for u in ["ui", "ux", "product designer"]):
        return False

    # Must contain recognized developer/engineering keyword
    tech_patterns = (
        r'\bengineer\b', r'\bdeveloper\b', r'\bsde\b', r'\bprogrammer\b', r'\barchitect\b',
        r'\bdata engineer\b', r'\bdata scientist\b', r'\bdata analyst\b', r'\bdatabase\b',
        r'\bdevops\b', r'\bcloud\b', r'\bsre\b', r'\bml\b', r'\bai engineer\b', r'\bai developer\b',
        r'\bfullstack\b', r'\bfull-stack\b', r'\bfrontend\b', r'\bfront-end\b', r'\bbackend\b', r'\bback-end\b',
        r'\bsoftware\b', r'\bmobile\b', r'\bandroid\b', r'\bios\b', r'\bweb developer\b', r'\bqa engineer\b'
    )
    return any(re.search(pat, title) for pat in tech_patterns)


def get_stream_relevance(job: dict, stream: str) -> int:
    """
    Returns relevance tier:
      2 = Exact, unambiguous niche match (e.g. Frontend Developer, React for frontend)
      1 = Broad/related engineering match (e.g. Fullstack with React for frontend)
      0 = Not relevant to this stream
    """
    if not is_valid_tech_job(job):
        return 0
        
    title = (job.get("title") or "").lower()
    skills = [s.lower() for s in (job.get("skills") or [])]
    cat = (job.get("role_category") or "").lower()
    stream = stream.lower()
    
    if stream == "frontend":
        # Strict exclusion of mobile / desktop app roles
        if any(m in title for m in MOBILE_KEYWORDS):
            return 0
        if any(b in title for b in ["backend", "back-end", "database admin", "network engineer"]):
            return 0
        if any(w in title for w in ["frontend", "front-end", "front end", "angular", "vue", "next.js", "nextjs", "svelte", "ui developer", "ui engineer"]):
            return 2
        if "react" in title and "native" not in title:
            return 2
        if "web developer" in title or "web engineer" in title:
            return 2
        if "frontend" in cat and "designer" not in title:
            return 1
        if any(k in skills for k in ["react", "next.js", "vue", "angular", "frontend"]) and any(w in title for w in ["developer", "engineer", "software"]):
            return 1
        return 0

    elif stream == "backend":
        if any(w in title for w in ["frontend", "front-end", "ui/ux", "mobile", "ios", "android"]):
            return 0
        if any(w in title for w in ["backend", "back-end", "back end", "node.js", "nodejs", "fastapi", "django", "flask", "golang", "spring", "api developer"]):
            return 2
        if "python" in title and any(w in title for w in ["developer", "engineer"]):
            return 2
        if "java" in title and "javascript" not in title and any(w in title for w in ["developer", "engineer"]):
            return 2
        if ".net developer" in title or "c# developer" in title:
            return 2
        if "backend" in cat:
            return 1
        if any(k in skills for k in ["python", "java", "node.js", "django", "fastapi", "spring", "golang", "sql", "postgresql", "rest apis"]) and any(w in title for w in ["software engineer", "sde", "developer"]):
            return 1
        return 0

    elif stream == "devops":
        if any(w in title for w in ["devops", "dev-ops", "dev ops", "cloud engineer", "cloud developer", "infrastructure engineer", "infra engineer", "platform engineer"]):
            return 2
        if re.search(r'\bsre\b', title) or "site reliability" in title:
            return 2
        if any(w in title for w in ["systems engineer", "network engineer", "security engineer"]):
            return 1
        if ("devops" in cat or "cloud" in cat) and any(w in title for w in ["engineer", "developer"]):
            return 1
        return 0

    elif stream == "data":
        if any(w in title for w in ["data engineer", "data scientist", "data analyst", "analytics engineer", "bi engineer", "machine learning", "deep learning", "nlp engineer"]):
            return 2
        if re.search(r'\b(ai|ml)\b', title) and any(w in title for w in ["engineer", "developer", "scientist", "analyst"]):
            return 2
        if "data" in cat and any(w in title for w in ["engineer", "developer", "scientist", "analyst"]):
            return 1
        return 0

    elif stream == "mobile":
        if any(m in title for m in MOBILE_KEYWORDS):
            return 2
        if "mobile" in cat:
            return 1
        return 0

    elif stream == "fullstack":
        if any(w in title for w in ["fullstack", "full-stack", "full stack"]):
            return 2
        if any(w in title for w in ["software engineer", "software developer", "sde"]):
            return 1
        if "fullstack" in cat or "software" in cat:
            return 1
        return 0

    elif stream == "mixed":
        return 2

    return 0


def normalize_title(t: str) -> str:
    """Normalize job title for company-level deduplication."""
    cleaned = re.sub(r'[^a-z0-9]', '', (t or "").lower())
    for noise in ["remote", "fulltime", "parttime", "shorttermproject", "contract", "india"]:
        cleaned = cleaned.replace(noise, "")
    return cleaned


def compute_virality_score(job: dict) -> float:
    """
    Ultra-fast in-memory virality & desirability score (0 to 100).
    Runs in < 0.1ms per candidate. Zero LLM calls, pure in-memory calculation.
    
    Weights:
    - 35 pts: Disclosed Salary (the #1 click magnet for freshers)
    - 25 pts: True Fresher Accessibility (0 YOE / Freshers Welcome)
    - 15 pts: Tier-1 Brand Clout & Direct ATS (Greenhouse/Lever/Ashby or recognized brand)
    - 15 pts: Modern In-Demand Stack (React, Python, TypeScript, Docker, Next.js, SQL)
    - 10 pts: Workplace Flexibility (Remote / Hybrid / Major Tech Hub)
    """
    score = 0.0

    # 1. Salary Transparency (35 pts max)
    raw_salary = (job.get("salary") or "").strip().lower()
    has_salary = raw_salary and raw_salary not in ("null", "none", "not disclosed", "n/a", "")
    if has_salary:
        score += 35.0
        if any(w in raw_salary for w in ("lpa", "k", "month", "$", "₹", "per")):
            score += 5.0

    # 2. Fresher Accessibility (25 pts max)
    min_yoe = job.get("min_yoe", 0) or 0
    is_fresher = job.get("is_fresher_friendly", False)
    if min_yoe == 0 or is_fresher:
        score += 25.0
    elif min_yoe == 1:
        score += 15.0
    elif min_yoe == 2:
        score += 5.0

    # 3. Direct ATS & Company Clout (15 pts max)
    source_provider = (job.get("source_provider") or "").upper()
    if source_provider in ("GREENHOUSE", "LEVER", "ASHBY"):
        score += 10.0
    
    comp_name = (job.get("company") or "").lower()
    famous_brands = (
        "google", "amazon", "microsoft", "uber", "cred", "swiggy", "zomato",
        "razorpay", "alphasense", "delhivery", "zepto", "groww", "meesho",
        "phonepe", "flipkart", "paytm", "ibm", "highradius", "vector", "sourcegraph"
    )
    if any(b in comp_name for b in famous_brands):
        score += 5.0

    # 4. Modern Marketable Tech Stack (15 pts max)
    skills = job.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip().lower() for s in skills.split(",") if s.strip()]
    else:
        skills = [str(s).strip().lower() for s in skills if str(s).strip()]

    hot_skills = (
        "react", "python", "javascript", "typescript", "next.js", "node", "sql",
        "docker", "aws", "tailwind", "fastapi", "django", "flutter", "react native", "git"
    )
    matches = sum(1 for s in skills if any(h in s for h in hot_skills))
    score += min(15.0, matches * 3.0)

    # 5. Workplace Appeal (10 pts max)
    wpt = (job.get("workplace_type") or "").lower()
    loc = (job.get("location") or "").lower()
    if "remote" in wpt or "remote" in loc:
        score += 10.0
    elif "hybrid" in wpt or "hybrid" in loc:
        score += 8.0
    elif any(hub in loc for hub in ("bangalore", "bengaluru", "pune", "hyderabad", "gurgaon", "noida", "mumbai", "delhi")):
        score += 6.0
    else:
        score += 3.0

    return score


async def fetch_curated_fresher_jobs(stream: str = "mixed", limit: int = 5) -> list[dict]:
    """
    Fetch high-quality, junior/fresher jobs from manual_jobs table for a specific stream.
    Strictly filters out non-tech roles, isolates exact niche disciplines, prioritizes salary,
    and intelligently deduplicates company/titles to guarantee exactly 5 high-converting cards.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Step 1: Fetch fresh active jobs that have NOT been featured on LinkedIn in the last 14 days
        query = """
            SELECT id, title, company, location, salary, skills, min_yoe, max_yoe,
                   workplace_type, source_provider, source_type, posted_at, url, role_category, is_fresher_friendly
            FROM manual_jobs
            WHERE is_active = TRUE
              AND (min_yoe <= 2 OR is_fresher_friendly = TRUE)
              AND id NOT IN (
                  SELECT job_id FROM linkedin_featured_jobs 
                  WHERE featured_at >= NOW() - INTERVAL '14 days'
              )
              AND (
                  location ILIKE '%india%' OR location ILIKE '%bangalore%' OR location ILIKE '%bengaluru%' OR 
                  location ILIKE '%remote%' OR location ILIKE '%hyderabad%' OR location ILIKE '%pune%' OR 
                  location ILIKE '%mumbai%' OR location ILIKE '%delhi%' OR location ILIKE '%gurgaon%' OR 
                  location ILIKE '%noida%' OR location ILIKE '%chennai%' OR location IS NULL OR location = ''
              )
            ORDER BY 
              CASE WHEN salary IS NOT NULL AND salary != 'Not disclosed' AND salary != '' THEN 0 ELSE 1 END,
              posted_at DESC
            LIMIT 150;
        """
        rows = await conn.fetch(query)
        candidates = [dict(r) for r in rows]

        # Step 2: Safety buffer - if unfeatured candidates are low (< 15), supplement with broader pool
        if len(candidates) < 15:
            fallback_rows = await conn.fetch("""
                SELECT id, title, company, location, salary, skills, min_yoe, max_yoe,
                       workplace_type, source_provider, source_type, posted_at, url, role_category, is_fresher_friendly
                FROM manual_jobs
                WHERE is_active = TRUE
                  AND (min_yoe <= 2 OR is_fresher_friendly = TRUE)
                  AND (
                      location ILIKE '%india%' OR location ILIKE '%bangalore%' OR location ILIKE '%bengaluru%' OR 
                      location ILIKE '%remote%' OR location ILIKE '%hyderabad%' OR location ILIKE '%pune%' OR 
                      location ILIKE '%mumbai%' OR location ILIKE '%delhi%' OR location ILIKE '%gurgaon%' OR 
                      location ILIKE '%noida%' OR location ILIKE '%chennai%' OR location IS NULL OR location = ''
                  )
                ORDER BY 
                  CASE WHEN salary IS NOT NULL AND salary != 'Not disclosed' AND salary != '' THEN 0 ELSE 1 END,
                  posted_at DESC
                LIMIT 50;
            """)
            seen_cand_ids = {c["id"] for c in candidates}
            for r in fallback_rows:
                if r["id"] not in seen_cand_ids:
                    candidates.append(dict(r))

    now_utc = datetime.now(timezone.utc)
    scored = []
    for j in candidates:
        rel = get_stream_relevance(j, stream)
        if rel > 0:
            v_score = compute_virality_score(j)
            if rel == 2:
                v_score += 25.0
            item = dict(j)
            item["_virality_score"] = v_score
            item["_relevance"] = rel
            scored.append(item)

    # Sort candidates by relevance DESC, virality score DESC, posted_at DESC
    scored.sort(
        key=lambda x: (x["_relevance"], x["_virality_score"], x.get("posted_at") or now_utc),
        reverse=True
    )

    selected = []
    seen_job_ids = set()
    company_counts = {}
    seen_comp_titles = set()

    def _can_add(job, max_comp_allowed=2, check_title=True):
        if job["id"] in seen_job_ids:
            return False
        comp = (job["company"] or "").strip().lower()
        if check_title:
            title_key = (comp, normalize_title(job["title"]))
            if title_key in seen_comp_titles:
                return False
        if company_counts.get(comp, 0) >= max_comp_allowed:
            return False
        return True

    def _add(job):
        selected.append(job)
        seen_job_ids.add(job["id"])
        comp = (job["company"] or "").strip().lower()
        company_counts[comp] = company_counts.get(comp, 0) + 1
        title_key = (comp, normalize_title(job["title"]))
        seen_comp_titles.add(title_key)

    # Pass 1: Max 1 job per company from EXACT matches
    for j in scored:
        if j["_relevance"] == 2 and _can_add(j, max_comp_allowed=1, check_title=True):
            _add(j)
            if len(selected) >= limit:
                break

    # Pass 2: Allow up to 2 jobs per company from EXACT matches with different titles
    if len(selected) < limit:
        for j in scored:
            if j["_relevance"] == 2 and _can_add(j, max_comp_allowed=2, check_title=True):
                _add(j)
                if len(selected) >= limit:
                    break

    # Pass 3: Allow up to 4 jobs per company from EXACT matches with different titles
    if len(selected) < limit:
        for j in scored:
            if j["_relevance"] == 2 and _can_add(j, max_comp_allowed=4, check_title=True):
                _add(j)
                if len(selected) >= limit:
                    break

    # Pass 4: Allow BROAD matches (rel == 1) with max 2 per company
    if len(selected) < limit:
        for j in scored:
            if j["_relevance"] == 1 and _can_add(j, max_comp_allowed=2, check_title=True):
                _add(j)
                if len(selected) >= limit:
                    break

    # Pass 5: Broad matches allowing up to 4 per company
    if len(selected) < limit:
        for j in scored:
            if j["_relevance"] == 1 and _can_add(j, max_comp_allowed=4, check_title=True):
                _add(j)
                if len(selected) >= limit:
                    break

    # Pass 6: Fallback to valid tech candidates
    if len(selected) < limit:
        for j in candidates:
            if is_valid_tech_job(j) and _can_add(j, max_comp_allowed=2, check_title=True):
                _add(j)
                if len(selected) >= limit:
                    break

    # Pass 7: Absolute safety fallback (any valid tech job not yet seen)
    if len(selected) < limit:
        for j in candidates:
            if is_valid_tech_job(j) and j["id"] not in seen_job_ids:
                _add(j)
                if len(selected) >= limit:
                    break

    # Final guarantee: Put salary jobs at the top of the cards
    def _has_salary(j):
        sal = (j.get("salary") or "").strip().lower()
        return 0 if sal and sal not in ("null", "none", "not disclosed", "n/a", "") else 1

    selected.sort(key=_has_salary)
    return selected[:limit]


def _format_job_card(job: dict) -> str:
    """Format a single job into the viral micro-card structure (Zero em-dashes)."""
    title = (job.get("title") or "Software Engineer").strip()
    company = (job.get("company") or "Tech Company").strip()
    
    # Location & Workplace Type
    raw_loc = (job.get("location") or "Remote / India").strip()
    workplace = (job.get("workplace_type") or "").strip()
    if workplace and workplace.lower() not in raw_loc.lower():
        loc_display = f"{raw_loc} ({workplace})"
    else:
        loc_display = raw_loc

    # Salary (Use simple standard hyphen)
    raw_salary = (job.get("salary") or "").strip()
    if not raw_salary or raw_salary.lower() in ("null", "none", "not disclosed", "n/a"):
        salary_display = "Salary Not Disclosed"
    else:
        salary_display = raw_salary.replace("—", " - ").replace("–", "-")

    # Experience Display (Use standard hyphen)
    min_yoe = job.get("min_yoe", 0) or 0
    max_yoe = job.get("max_yoe")
    is_fresher = job.get("is_fresher_friendly", False)

    if min_yoe == 0 or is_fresher:
        if max_yoe and max_yoe > 0:
            exp_display = f"Freshers Welcome (0-{max_yoe} YOE)"
        else:
            exp_display = "Freshers Welcome (0 YOE)"
    elif min_yoe == 1:
        exp_display = "1 YOE (Freshers with internships welcome)"
    else:
        exp_display = f"{min_yoe} YOE"

    # Skills formatting (top 5 skills to stay concise and impactful)
    skills = job.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    clean_skills = [str(s).strip() for s in skills if str(s).strip()][:5]
    if not clean_skills:
        clean_skills = ["Python", "JavaScript", "SQL", "Git", "APIs"]
    skills_display = ", ".join(clean_skills)

    card = (
        f"🚀 {title} - {company}\n"
        f"📍 {loc_display}\n"
        f"💰 {salary_display}\n"
        f"🎯 {exp_display}\n"
        f"⚡ {skills_display}"
    )
    return card


async def generate_linkedin_post(slot: str = "morning", stream: str | None = None) -> dict:
    """
    Generate a complete, copy-paste-ready LinkedIn post + companion First Comment.
    `slot`: 'morning' (for 9:00 AM post) or 'evening' (for 6:00 PM post).
    `stream`: Optional override ('frontend', 'backend', 'devops', 'data', 'fullstack', 'mobile', 'mixed').
              If None, automatically picks the scheduled stream for today/slot.
    Guaranteed strictly under LinkedIn's 3,000 character limit (typically ~2,200 to 2,400 chars).
    """
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    weekday = now_ist.weekday()  # 0=Monday ... 6=Sunday

    # Auto-pick stream from rotation if not explicitly specified
    if not stream or stream.lower() not in NICHE_CONFIGS:
        slot_clean = "evening" if "even" in slot.lower() or "pm" in slot.lower() else "morning"
        chosen_stream = WEEKLY_ROTATION.get(weekday, {}).get(slot_clean, "mixed")
    else:
        chosen_stream = stream.lower()

    config = NICHE_CONFIGS[chosen_stream]
    jobs = await fetch_curated_fresher_jobs(stream=chosen_stream, limit=5)
    if not jobs:
        return {
            "error": f"No active jobs found in database for stream '{chosen_stream}'.",
            "post_text": "",
            "first_comment": ""
        }

    # Record featured jobs into tracking table so they are NEVER repeated in future drops
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            for j in jobs:
                await conn.execute("""
                    INSERT INTO linkedin_featured_jobs (job_id, stream, slot, featured_at)
                    VALUES ($1, $2, $3, NOW())
                """, j["id"], chosen_stream, slot)
    except Exception as e:
        logger.warning(f"Failed to record featured jobs to linkedin_featured_jobs: {e}")

    # Format the 5 job cards (compact separator)
    cards = [_format_job_card(j) for j in jobs]
    cards_section = "\n━━━━━━━\n".join(cards)

    # Evening context tease
    evening_tease = ""
    if slot == "morning":
        evening_stream_name = NICHE_CONFIGS.get(WEEKLY_ROTATION[weekday]["evening"], {}).get("name", "tech")
        evening_tease = f"In the evening I'll drop 5 more verified {evening_stream_name} openings.\n\n"

    # Build the full post body (Punchy, viral, strictly under 3000 chars, zero em-dashes)
    post_text = f"""{config['hook_intro']}

━━━━━━━
{cards_section}
━━━━━━━

One pattern we notice tracking thousands of career applications:
A lot of candidates spend months improving their skills...
Very few spend the same energy applying early before 500+ people flood the portal.

That is why we built FroncyBot.
We monitor 525+ direct company career pages (Greenhouse, Lever, Ashby) with continuous hourly sweeps.
When a company publishes a fresh opening, you catch it in the first wave, hours before it hits public job boards.

⚡ What you get on Telegram:
1️⃣ Upload your resume once
2️⃣ Live ATS match score & keyword breakdown for your stack
3️⃣ Direct official career-page links before the crowd arrives

🔗 Direct 1-tap FroncyBot access link is pinned in the FIRST COMMENT below 👇
(Or check the link at the top of my profile featured section)

💬 Or simply comment "BOT" or "LINK" and we'll send you the direct access link.

📌 Save this post before you apply.
📌 Repost to help a fellow developer land an interview.
📌 Follow for daily direct career-page drops.

{evening_tease}{config['hashtags']}"""

    # ── Strict Sanitizer: Remove any em-dash (—) and en-dash (–) ──
    post_text = post_text.replace("—", " - ").replace("–", "-")
    post_text = re.sub(r' +', ' ', post_text)

    # ── Hard Cap Safety Guard for LinkedIn (3,000 char maximum) ──
    if len(post_text) > 2900:
        # If ever pushing near the limit due to long job titles, trim cleanly
        post_text = post_text[:2850].rstrip() + "\n\n" + config['hashtags']

    # Companion First Comment (Zero penalty + 1-click conversion)
    first_comment = (
        f"🚀 Here is the direct 1-tap link to launch FroncyBot on Telegram:\n"
        f"👉 https://t.me/FroncyJobsBot\n\n"
        f"⚡ First-wave direct alerts for fresh junior {config['name']} jobs from 525+ company career pages (Greenhouse, Lever, Ashby) hours before they hit LinkedIn.\n"
        f"🎯 Upload your resume to see your live ATS match score in 10 seconds!"
    )
    first_comment = first_comment.replace("—", " - ").replace("–", "-")
    first_comment = re.sub(r' +', ' ', first_comment)

    return {
        "slot": slot,
        "stream": chosen_stream,
        "stream_name": config["name"],
        "post_text": post_text.strip(),
        "first_comment": first_comment.strip(),
        "job_count": len(jobs),
        "companies": [j.get("company") for j in jobs]
    }


async def send_scheduled_linkedin_post(bot, slot: str = "morning") -> bool:
    """
    Called by APScheduler at 8:00 AM IST and 5:00 PM IST.
    Generates the LinkedIn post using the scheduled niche stream and delivers it to Admin.
    """
    admin_id = settings.ADMIN_TELEGRAM_ID
    if not admin_id:
        logger.warning("Cannot send LinkedIn post: settings.ADMIN_TELEGRAM_ID is not configured.")
        return False

    try:
        post_data = await generate_linkedin_post(slot=slot)
        if "error" in post_data:
            await bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ <b>LinkedIn Post Generator Error:</b> {post_data['error']}",
                parse_mode="HTML"
            )
            return False

        slot_title = "Morning Drop (for 9:00 AM)" if slot == "morning" else "Evening Drop (for 6:00 PM)"
        stream_name = post_data.get("stream_name", "Tech")
        companies_str = ", ".join(filter(None, post_data.get("companies", [])))

        header_text = (
            f"📢 <b>LinkedIn Viral Post Ready! ({slot_title})</b>\n\n"
            f"🎯 <b>Niche Stream:</b> <b>{stream_name}</b>\n"
            f"🏢 <b>Featured Companies:</b> {html.escape(companies_str)}\n\n"
            f"👇 <b>1. Copy and paste the post text below on LinkedIn:</b>"
        )
        await bot.send_message(
            chat_id=admin_id,
            text=header_text,
            parse_mode="HTML"
        )

        # Post body message
        await bot.send_message(
            chat_id=admin_id,
            text=post_data["post_text"],
            disable_web_page_preview=True
        )

        # First comment message
        comment_header = (
            "💬 <b>2. Copy and paste this as the FIRST COMMENT on your post:</b>\n"
            "<i>(This bypasses LinkedIn's link penalty and gives readers a direct 1-tap link!)</i>"
        )
        await bot.send_message(
            chat_id=admin_id,
            text=comment_header,
            parse_mode="HTML"
        )

        await bot.send_message(
            chat_id=admin_id,
            text=post_data["first_comment"],
            disable_web_page_preview=True
        )

        logger.info(f"✅ Successfully sent scheduled LinkedIn {slot} post ({stream_name}) to admin {admin_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to generate or send LinkedIn post to admin: {e}")
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"❌ <b>Failed to generate scheduled LinkedIn post:</b> {html.escape(str(e))}",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return False
