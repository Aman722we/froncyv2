"""
Resume PDF text extraction and safe skill extraction using PyMuPDF and pymupdf4llm.
RFC-008 Compliant:
- Magic bytes check (%PDF-)
- Password/encryption check
- Page cap (max 10 pages)
- Event loop offloading (asyncio.to_thread)
- Concurrency bounded by Semaphore(3)
- Top-15 ranked canonical skill extraction
- Zero logging of resume text / candidate PII
"""
import os
import re
import json
import asyncio
from pathlib import Path
from collections import defaultdict
try:
    import pymupdf
    import pymupdf as fitz
except ImportError:
    import fitz  # PyMuPDF fallback
import pymupdf4llm
from loguru import logger
from utils.validators import CANONICAL_SKILL_MAP, validate_and_normalize_skills


RESUMES_DIR = Path("resumes")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_PAGES = 10
PARSE_SEMAPHORE = asyncio.Semaphore(3)


def ensure_resumes_dir():
    """Create resumes directory if it doesn't exist."""
    RESUMES_DIR.mkdir(exist_ok=True)


def _extract_text_from_pdf_sync(file_bytes: bytes) -> str:
    """
    Synchronous worker executed in a thread pool.
    Validates magic bytes, encryption, page limits, and extracts markdown text.
    """
    # 1. Magic bytes validation
    if not file_bytes.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF format. The file does not start with %PDF- header.")

    # 2. Open PDF from memory stream
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Failed to open PDF document: {e}")

    try:
        # 3. Guard against encrypted / password-protected files
        if doc.is_encrypted:
            raise ValueError("This PDF is password-protected. Please upload an unprotected PDF.")

        # 4. Cap pages to prevent memory exhaustion
        total_pages = len(doc)
        if total_pages == 0:
            raise ValueError("The PDF document contains 0 pages.")

        pages_to_process = list(range(min(total_pages, MAX_PAGES)))

        # 5. Extract structural markdown using pymupdf4llm
        try:
            full_text = pymupdf4llm.to_markdown(doc, pages=pages_to_process)
        except Exception as e:
            raise ValueError(f"Text extraction failed: {e}")

        # Strip null bytes that would crash PostgreSQL
        full_text = full_text.replace("\x00", "").strip()

        # 6. Scanned PDF detection
        if len(full_text) < 40:
            raise ValueError("Could not extract text. The PDF appears to be a scanned image or empty.")

        # 7. Extract links for application kit
        found_urls = []
        for p_idx in pages_to_process:
            page = doc[p_idx]
            for link in page.get_links():
                uri = link.get("uri", "")
                if uri and uri not in found_urls:
                    found_urls.append(uri)

        if found_urls:
            full_text += "\n\n[EMBEDDED LINKS FROM PDF]\n" + "\n".join(found_urls)

        return full_text

    finally:
        doc.close()


async def extract_text_from_pdf_bytes_safe(file_bytes: bytes) -> str:
    """
    Asynchronously and safely extract text from PDF bytes off the event loop,
    concurrency-bounded by PARSE_SEMAPHORE.
    """
    async with PARSE_SEMAPHORE:
        return await asyncio.to_thread(_extract_text_from_pdf_sync, file_bytes)


def extract_text_from_pdf(filepath: str) -> str:
    """
    Synchronous file-path extraction for backward compatibility.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    file_bytes = path.read_bytes()
    return _extract_text_from_pdf_sync(file_bytes)


def _build_canonical_patterns() -> dict[str, re.Pattern]:
    """Group aliases per canonical skill and compile regex patterns once to eliminate synonym bias."""
    canonical_to_aliases: dict[str, list[str]] = defaultdict(list)
    for alias, canonical in CANONICAL_SKILL_MAP.items():
        canonical_to_aliases[canonical].append(alias)

    compiled: dict[str, re.Pattern] = {}
    for canonical, aliases in canonical_to_aliases.items():
        aliases_sorted = sorted(aliases, key=len, reverse=True)
        regex_parts = []
        for a in aliases_sorted:
            if a in ("c++", "c#", ".net"):
                regex_parts.append(rf"(?<!\w){re.escape(a)}(?!\w)")
            elif a == "js":
                # Negative lookbehind for dot so Node.js, Express.js, Next.js don't trigger JavaScript
                regex_parts.append(r"(?<!\.)\bjs\b")
            elif a == "r":
                # Prevent R&D or paths from triggering R language
                regex_parts.append(r"(?<![\w&/])r(?![\w&/])")
            else:
                regex_parts.append(rf"\b{re.escape(a)}\b")
        compiled[canonical] = re.compile("|".join(regex_parts), re.IGNORECASE)
    return compiled


_CANONICAL_PATTERNS = _build_canonical_patterns()
_groq_circuit_breaker_until: float = 0.0

ROLE_ALIGNMENT: dict[str, set[str]] = {
    "frontend": {"react", "next.js", "vue.js", "angular", "javascript", "typescript", "html", "css", "tailwind css", "redux", "vite", "flutter"},
    "backend": {"python", "node.js", "go", "java", "fastapi", "django", "spring boot", "postgresql", "mysql", "mongodb", "redis", "docker", "rest apis", "microservices", "mcp", "langgraph", "supabase"},
    "fullstack": {"react", "node.js", "typescript", "python", "postgresql", "docker", "next.js", "rest apis", "aws", "tailwind css", "mongodb"},
    "devops": {"docker", "kubernetes", "aws", "gcp", "azure", "terraform", "ci/cd", "jenkins", "linux", "ansible", "bash"},
    "data": {"python", "sql", "machine learning", "deep learning", "pytorch", "tensorflow", "pandas", "numpy", "apache spark", "airflow", "langchain", "langgraph", "rag"},
}


def rank_and_extract_skills(resume_text: str, role_pref: str = "other", max_skills: int = 15) -> list[str]:
    """
    Tier 2: Extract canonical technical skills from resume text, ranked by:
      - 3x: Mentioned inside a designated 'Skills' section
      - 2x: Aligned with candidate role preference (e.g. frontend, backend)
      - 1x: Frequency of occurrence across the document (grouping aliases to eliminate synonym multiplication)
    Returns top 15 canonical skills. Never logs resume text.
    """
    if not resume_text:
        return []

    text_lower = resume_text.lower()

    # Detect skills section if present
    skills_section_text = ""
    skills_header_pattern = re.compile(
        r"(?:skills|technical skills|technologies|tech stack|key skills|proficiencies|tools\s*&\s*technologies)[:\n]",
        re.IGNORECASE
    )
    match = skills_header_pattern.search(text_lower)
    if match:
        start_idx = match.start()
        # Take the next 1500 chars or until next section header
        skills_section_text = text_lower[start_idx:start_idx + 1500]

    preferred_skills = ROLE_ALIGNMENT.get(role_pref.lower(), set())

    # Score each canonical skill
    skill_scores: dict[str, int] = {}

    for canonical, pattern in _CANONICAL_PATTERNS.items():
        matches = pattern.findall(text_lower)
        count = len(matches)
        if count == 0:
            continue

        score = count

        # 2. Section weight (3x bonus if in skills section)
        if skills_section_text and pattern.search(skills_section_text):
            score += 3

        # 3. Role alignment bonus
        if canonical.lower() in preferred_skills:
            score += 2

        skill_scores[canonical] = score

    if not skill_scores:
        return []

    # Sort descending by score, tie-break by name
    sorted_skills = sorted(skill_scores.keys(), key=lambda s: (skill_scores[s], s), reverse=True)
    return sorted_skills[:max_skills]


async def extract_skills_hybrid(resume_text: str, role_pref: str = "other", max_skills: int = 15) -> list[str]:
    """
    Tiered Hybrid Skill Extraction Architecture:
      Tier 1: Fast LLM (Groq / OpenAI compatible) attempt with strict 2.0s timeout and circuit breaker.
              Validated and normalized against canonical taxonomy.
      Tier 2: High-speed, deterministic local Python regex extractor with section weighting
              and role stream alignment. Zero synonym multiplication bias.
    Guarantees:
      - Resilient fallback: Never fails or hangs onboarding if Groq is restricted, rate-limited, or slow.
      - Returns at most `max_skills` canonical skills.
      - Respects zero-logging of candidate PII.
    """
    global _groq_circuit_breaker_until
    if not resume_text or not resume_text.strip():
        return []

    import time
    now = time.time()

    # Tier 1: Fast LLM attempt (bypassed immediately if circuit breaker is tripped)
    if now >= _groq_circuit_breaker_until:
        used_key = None
        try:
            from services.llm_service import _get_client, LLMMode, _key_cooldowns

            client, model = _get_client(LLMMode.FAST, timeout=2.0)
            used_key = getattr(client, "_used_api_key", None)

            # Key-level cooldown check
            if not used_key or _key_cooldowns.get(used_key, 0.0) <= now:
                sample_text = resume_text[:3500]
                system_prompt = (
                    "You are an expert technical recruiter and resume parser. "
                    "Extract up to 15 key technical skills, programming languages, databases, cloud tools, frameworks, and AI tools explicitly mentioned in the resume. "
                    "Return ONLY a valid JSON list of strings, e.g. [\"Python\", \"PostgreSQL\", \"FastAPI\"]. "
                    "Do not include generic soft skills, buzzwords, or explanations outside the JSON."
                )

                resp = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Resume Text:\n{sample_text}\n\nExtract top technical skills:"}
                        ],
                        temperature=0.1,
                        max_tokens=200,
                    ),
                    timeout=2.0,
                )

                content = (resp.choices[0].message.content or "").strip()
                json_match = re.search(r"\[.*?\]", content, re.DOTALL)
                if json_match:
                    raw_skills = json.loads(json_match.group(0))
                    if isinstance(raw_skills, list) and len(raw_skills) > 0:
                        is_valid, normalized, _ = validate_and_normalize_skills(raw_skills, max_skills=max_skills)
                        if is_valid and len(normalized) >= 3:
                            logger.info(f"Tier 1 (LLM) extracted {len(normalized)} skills successfully")
                            return normalized
        except Exception as e:
            err_msg = str(e).lower()
            if any(phrase in err_msg for phrase in ("organization_restricted", "unauthorized", "invalid_api_key", "permission_denied")):
                _groq_circuit_breaker_until = time.time() + 900  # 15 min global circuit breaker
                logger.warning(f"Groq API circuit breaker tripped for 15m: {e}")
            elif used_key:
                from services.llm_service import _key_cooldowns
                _key_cooldowns[used_key] = time.time() + 300  # 5 min key cooldown
            logger.debug(f"Tier 1 LLM skill extraction bypassed/fallback ({type(e).__name__}: {e})")

    # Tier 2: Enhanced deterministic regex fallback
    return rank_and_extract_skills(resume_text, role_pref=role_pref, max_skills=max_skills)


def save_resume_file(telegram_id: int, file_bytes: bytes, filename: str) -> str:
    """Save resume PDF to disk safely."""
    ensure_resumes_dir()
    safe_name = f"{telegram_id}_{filename.replace(' ', '_')}"
    filepath = RESUMES_DIR / safe_name

    # Remove old resume if exists
    for old_file in RESUMES_DIR.glob(f"{telegram_id}_*"):
        old_file.unlink()

    filepath.write_bytes(file_bytes)
    return str(filepath)


def get_resume_path(telegram_id: int) -> str | None:
    """Find the stored resume file path for a user."""
    ensure_resumes_dir()
    files = list(RESUMES_DIR.glob(f"{telegram_id}_*"))
    return str(files[0]) if files else None


def delete_resume_file(telegram_id: int) -> bool:
    """Delete stored resume file for a user from local disk."""
    ensure_resumes_dir()
    deleted = False
    for f in RESUMES_DIR.glob(f"{telegram_id}_*"):
        try:
            f.unlink()
            deleted = True
        except Exception:
            pass
    return deleted
