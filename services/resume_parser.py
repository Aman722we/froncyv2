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
import asyncio
from pathlib import Path
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


def rank_and_extract_skills(resume_text: str, role_pref: str = "other", max_skills: int = 15) -> list[str]:
    """
    Extract canonical technical skills from resume text, ranked by:
      - 3x: Mentioned inside a designated 'Skills' section
      - 2x: Aligned with candidate role preference (e.g. frontend, backend)
      - 1x: Frequency of occurrence across the document
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

    # Role stream alignment keywords
    role_alignment: dict[str, set[str]] = {
        "frontend": {"react", "next.js", "vue.js", "angular", "javascript", "typescript", "html", "css", "tailwind css", "redux", "vite"},
        "backend": {"python", "node.js", "go", "java", "fastapi", "django", "spring boot", "postgresql", "mysql", "mongodb", "redis", "docker", "rest apis"},
        "fullstack": {"react", "node.js", "typescript", "python", "postgresql", "docker", "next.js", "rest apis", "aws", "tailwind css"},
        "devops": {"docker", "kubernetes", "aws", "gcp", "azure", "terraform", "ci/cd", "jenkins", "linux", "ansible"},
        "data": {"python", "sql", "machine learning", "deep learning", "pytorch", "tensorflow", "pandas", "numpy", "apache spark", "airflow"},
    }
    preferred_skills = role_alignment.get(role_pref.lower(), set())

    # Score each canonical skill
    skill_scores: dict[str, int] = {}

    for alias, canonical in CANONICAL_SKILL_MAP.items():
        # Match using word boundaries
        # Special handling for C++, C#, .NET
        if alias in ("c++", "c#", ".net"):
            escaped = re.escape(alias)
            pattern = re.compile(rf"(?:^|[\s,;:(]){escaped}(?:$|[\s,;:)\n])", re.IGNORECASE)
        else:
            escaped = re.escape(alias)
            pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)

        # 1. Total occurrences
        count = len(pattern.findall(text_lower))
        if count == 0:
            continue

        score = count

        # 2. Section weight (3x bonus if in skills section)
        if skills_section_text and pattern.search(skills_section_text):
            score += 3

        # 3. Role alignment bonus
        if canonical.lower() in preferred_skills or alias in preferred_skills:
            score += 2

        # Accumulate score under the canonical name
        skill_scores[canonical] = skill_scores.get(canonical, 0) + score

    if not skill_scores:
        return []

    # Sort descending by score, tie-break by name
    sorted_skills = sorted(skill_scores.keys(), key=lambda s: (skill_scores[s], s), reverse=True)
    return sorted_skills[:max_skills]


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
