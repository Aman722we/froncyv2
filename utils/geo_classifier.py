"""
Geo-Hiring & Location Classifier (RFC-005).
Classifies job locations into mutually exclusive geographical buckets:
  1. india_tech: Location in India AND Title matches tech whitelist
  2. india_non_tech: Location in India AND Title is non-tech
  3. foreign: Explicitly foreign country/city OR region-locked remote (e.g. SF, London, Remote US, Remote EMEA)
  4. remote_global: Unrestricted Worldwide / Global Remote (e.g. Worldwide, Anywhere, Work from anywhere)
  5. remote_ambiguous: Generic unspecified remote (e.g. 'Remote', 'WFH') without explicit global or country modifier
  6. unclassified: Ambiguous or generic department/office strings ('Multiple Locations', 'Flexible', '')

Rules:
- Delimiter-based tokenization.
- Standalone uppercase 2-letter country codes (US, UK, IN, CA, DE, AU, SG).
- Lowercase 'in', 'ca', 'de' in prose NEVER match country codes.
- Pre-compiled regex patterns for performance and zero memory leaks.
"""
import re

# ── Tech Role Keywords (Identical to services/career_sync.py ingestion whitelist) ──
TECH_KEYWORDS = [
    "engineer", "developer", "sde", "programmer", "software", "coder", "architect",
    "data", "ml", "ai", "machine learning", "product", "designer", "ui", "ux",
    "security", "cloud", "sre", "devops", "platform", "backend", "frontend",
    "fullstack", "ios", "android", "mobile", "qa", "test", "systems", "research", "mle",
]
RE_TECH = re.compile(r'\b(' + '|'.join(re.escape(k) for k in TECH_KEYWORDS) + r')\b', re.IGNORECASE)

# Non-tech veto keywords
JUNK_KEYWORDS = [
    "sales", "marketing", "account executive", "hr", "human resources", "recruiter", "recruiting",
    "finance", "accounting", "legal", "counsel", "customer success", "advocacy",
    "content", "copywriter", "business development", "payroll", "tax",
    "workplace", "facilities", "executive assistant", "vp", "chief",
    "support", "technical support", "partner", "partnerships", "event", "events",
]
RE_JUNK = re.compile(r'\b(' + '|'.join(re.escape(k) for k in JUNK_KEYWORDS) + r')\b', re.IGNORECASE)

# ── India Location Keywords ──
INDIA_CITIES = [
    "india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "gurgaon",
    "gurugram", "noida", "chennai", "kolkata", "ahmedabad", "remote - ind", "remote - india",
    "india remote", "remote india",
]
RE_INDIA_CITIES = re.compile(r'\b(' + '|'.join(re.escape(c) for c in INDIA_CITIES) + r')\b', re.IGNORECASE)
RE_INDIA_CODE = re.compile(r'\b(IN|IND)\b')  # Uppercase only

# ── Explicit Foreign Terms & Region-Locked Remote ──
# Case-insensitive full country and city names
FOREIGN_TERMS = [
    "united states", "usa", "u.s.a.", "u.s.", "united kingdom", "u.k.", "london", "europe", "emea",
    "amer", "latam", "canada", "australia", "spain", "sweden", "ireland", "germany",
    "france", "singapore", "poland", "romania", "netherlands", "brazil", "mexico",
    "colombia", "argentina", "new york", "san francisco", "seattle", "portugal",
    "lisbon", "japan", "tokyo", "israel", "tel aviv", "dubai", "uae", "abu dhabi",
    "chile", "austria", "belgium", "switzerland", "zurich", "berlin", "munich",
    "toronto", "vancouver", "sydney", "melbourne", "paris", "madrid", "barcelona",
    "boston", "austin", "chicago", "los angeles", "denver", "atlanta",
    "california", "texas", "washington", "massachusetts", "colorado",
]
RE_FOREIGN_TERMS = re.compile(r'\b(' + '|'.join(re.escape(t) for t in FOREIGN_TERMS) + r')\b', re.IGNORECASE)

# Standalone uppercase country codes (MUST be uppercase to prevent matching 'in', 'us', 'ca' in English words)
RE_FOREIGN_CODES = re.compile(r'\b(US|USA|UK|CA|DE|AU|SG|EU|FR|ES|NL|CH|JP|BR|MX)\b')

# Region-locked remote modifiers
REGION_LOCKED_REMOTE_PATTERNS = [
    r'remote\s*[-–—:]\s*(us|usa|u\.s\.|emea|amer|latam|europe|uk|canada|na|apac\s*\(ex[^\)]*\))',
    r'remote\s*\(\s*(us|usa|u\.s\.|emea|amer|latam|europe|uk|canada)',
    r'(us|usa|u\.s\.|emea|amer|europe|uk|canada)\s*remote',
    r'remote\s*,\s*(us|usa|u\.s\.|emea|amer|latam|europe|uk|canada)',
    r'remote\s*-\s*[a-z\s]+only',  # e.g. "Remote - US only"
]
RE_REGION_LOCKED_REMOTE = re.compile(r'(' + '|'.join(REGION_LOCKED_REMOTE_PATTERNS) + r')', re.IGNORECASE)

# ── Explicit Worldwide / Global Remote Keywords ──
GLOBAL_REMOTE_PATTERNS = [
    r'\bworldwide\b',
    r'\bglobal\s*remote\b',
    r'\bremote\s*[-–—:]\s*global\b',
    r'\bremote\s*,\s*global\b',
    r'\bwork\s*from\s*anywhere\b',
    r'\banywhere\s*in\s*the\s*world\b',
    r'\bremote\s*[-–—:]\s*anywhere\b',
    r'\banywhere\b',
    r'\bfully\s*remote\s*worldwide\b',
]
RE_GLOBAL_REMOTE = re.compile(r'(' + '|'.join(GLOBAL_REMOTE_PATTERNS) + r')', re.IGNORECASE)

# ── Generic / Ambiguous Remote Keywords ──
RE_AMBIGUOUS_REMOTE = re.compile(r'\b(remote|wfh|telecommute|work\s*from\s*home|virtual)\b', re.IGNORECASE)


def is_tech_title(title: str, dept: str = "") -> bool:
    """Check if title matches the tech ingestion whitelist and passes junk veto."""
    t = (title or "").lower()
    d = (dept or "").lower()
    if RE_JUNK.search(t) or RE_JUNK.search(d):
        return False
    return bool(RE_TECH.search(t) or RE_TECH.search(d))


def is_location_india(loc_str: str) -> bool:
    """Returns True if the location string represents an India location."""
    if not loc_str:
        return False
    if RE_INDIA_CITIES.search(loc_str):
        return True
    # Check standalone uppercase country codes (e.g. "Bengaluru, IN")
    if RE_INDIA_CODE.search(loc_str):
        return True
    return False


def is_location_foreign(loc_str: str) -> bool:
    """Returns True if the location string explicitly represents a foreign or region-locked location."""
    if not loc_str:
        return False
    if RE_REGION_LOCKED_REMOTE.search(loc_str):
        return True
    if RE_FOREIGN_TERMS.search(loc_str):
        return True
    if RE_FOREIGN_CODES.search(loc_str):
        return True
    return False


def is_location_global_remote(loc_str: str) -> bool:
    """Returns True if the location string explicitly signifies worldwide / unrestricted remote."""
    if not loc_str:
        return False
    return bool(RE_GLOBAL_REMOTE.search(loc_str))


def is_location_ambiguous_remote(loc_str: str) -> bool:
    """Returns True if the location indicates generic remote without explicit country/global context."""
    if not loc_str:
        return False
    return bool(RE_AMBIGUOUS_REMOTE.search(loc_str))


def classify_job(title: str, locations: list[str] | str | None, department: str = "") -> str:
    """
    Classifies a job into one of six mutually exclusive categories:
      - 'india_tech'
      - 'india_non_tech'
      - 'foreign'
      - 'remote_global'
      - 'remote_ambiguous'
      - 'unclassified'
    
    Priority Hierarchy:
      1. India Check: Any location matches India -> tech or non-tech
      2. Foreign / Region-Locked Check -> foreign
      3. Global / Worldwide Remote Check -> remote_global
      4. Ambiguous Remote Check -> remote_ambiguous
      5. Fallback -> unclassified
    """
    if locations is None:
        loc_list = []
    elif isinstance(locations, str):
        loc_list = [locations]
    else:
        loc_list = [str(l) for l in locations if l]

    # Combine all locations into a joined representation for holistic check
    combined_loc = " | ".join(loc_list).strip()

    # Step 1: Multi-location India check
    # If ANY location specifies India, the job is an India job
    has_india = any(is_location_india(loc) for loc in loc_list) if loc_list else is_location_india(combined_loc)
    if has_india:
        if is_tech_title(title, department):
            return "india_tech"
        return "india_non_tech"

    # Step 2: Explicit Foreign / Region-Locked Check
    # (Checked BEFORE remote to catch 'Remote, US', 'Remote - US only', 'San Francisco', etc.)
    has_foreign = any(is_location_foreign(loc) for loc in loc_list) if loc_list else is_location_foreign(combined_loc)
    if has_foreign:
        return "foreign"

    # Step 3: Explicit Worldwide / Global Remote Check
    has_global_remote = any(is_location_global_remote(loc) for loc in loc_list) if loc_list else is_location_global_remote(combined_loc)
    if has_global_remote:
        return "remote_global"

    # Step 4: Generic Ambiguous Remote Check
    has_ambiguous_remote = any(is_location_ambiguous_remote(loc) for loc in loc_list) if loc_list else is_location_ambiguous_remote(combined_loc)
    if has_ambiguous_remote:
        return "remote_ambiguous"

    # Step 5: Fallback Unclassified (e.g. 'Multiple Locations', 'Engineering', '')
    return "unclassified"


def extract_locations_from_raw_job(raw_job: dict, provider: str) -> list[str]:
    """Extracts all location strings from a raw job dictionary across Greenhouse, Lever, and Ashby."""
    provider = provider.upper()
    locations: list[str] = []

    if provider == "GREENHOUSE":
        loc = raw_job.get("location")
        if isinstance(loc, dict) and loc.get("name"):
            locations.append(loc["name"])
        elif isinstance(loc, str) and loc:
            locations.append(loc)
        # Check offices
        offices = raw_job.get("offices", [])
        if isinstance(offices, list):
            for off in offices:
                if isinstance(off, dict) and off.get("name"):
                    locations.append(off["name"])

    elif provider == "LEVER":
        cats = raw_job.get("categories", {})
        if isinstance(cats, dict):
            loc = cats.get("location")
            if loc:
                locations.append(loc)
            all_locs = cats.get("allLocations", [])
            if isinstance(all_locs, list):
                for l in all_locs:
                    if l and l not in locations:
                        locations.append(l)
        country = raw_job.get("country")
        if country and country not in locations:
            locations.append(country)

    elif provider == "ASHBY":
        loc = raw_job.get("location") or raw_job.get("locationName")
        if loc:
            locations.append(loc)
        sec_locs = raw_job.get("secondaryLocations", [])
        if isinstance(sec_locs, list):
            for sl in sec_locs:
                if isinstance(sl, dict) and sl.get("location"):
                    locations.append(sl["location"])
                elif isinstance(sl, str) and sl:
                    locations.append(sl)

    return locations


def tally_raw_jobs(jobs: list[dict], provider: str) -> dict:
    """
    Tallies raw jobs into RFC-005 geographical and role buckets.
    Returns dictionary of aggregate counts.
    """
    counts = {
        "total_board_jobs": len(jobs),
        "india_tech_jobs": 0,
        "india_non_tech_jobs": 0,
        "remote_global_jobs": 0,
        "remote_ambiguous_jobs": 0,
        "foreign_jobs": 0,
        "unclassified_jobs": 0,
    }

    for job in jobs:
        title = job.get("title") or job.get("text") or "Untitled"
        dept = ""
        if provider == "GREENHOUSE":
            departments = job.get("departments", [])
            if departments and isinstance(departments, list):
                dept = departments[0].get("name", "") if isinstance(departments[0], dict) else ""
        elif provider == "LEVER":
            cats = job.get("categories", {})
            if isinstance(cats, dict):
                dept = cats.get("department", "")
        elif provider == "ASHBY":
            dept = job.get("department") or job.get("team") or ""

        locations = extract_locations_from_raw_job(job, provider)
        category = classify_job(title, locations, dept)

        if category == "india_tech":
            counts["india_tech_jobs"] += 1
        elif category == "india_non_tech":
            counts["india_non_tech_jobs"] += 1
        elif category == "foreign":
            counts["foreign_jobs"] += 1
        elif category == "remote_global":
            counts["remote_global_jobs"] += 1
        elif category == "remote_ambiguous":
            counts["remote_ambiguous_jobs"] += 1
        else:
            counts["unclassified_jobs"] += 1

    return counts
