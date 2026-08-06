"""
Resume PDF text extraction using PyMuPDF and pymupdf4llm.

Why pymupdf4llm:
- Natively understands reading order, multi-column layouts, tables, and lists.
- Bypasses PyMuPDF's low-level get_text("blocks") block-fusion bugs which can 
  scramble text horizontally (e.g. fusing 'ensuring' and 'Intern').
- Outputs clean Markdown which is highly optimized for LLMs (Llama 70B/8B).
"""
import os
from pathlib import Path
import fitz  # PyMuPDF
import pymupdf4llm
from loguru import logger


RESUMES_DIR = Path("resumes")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def ensure_resumes_dir():
    """Create resumes directory if it doesn't exist."""
    RESUMES_DIR.mkdir(exist_ok=True)


def extract_text_from_pdf(filepath: str) -> str:
    """
    Extract perfectly formatted markdown text from a PDF file using pymupdf4llm.

    Also extracts embedded hyperlinks (GitHub, LinkedIn, portfolio URLs)
    natively via fitz page.get_links() to ensure they are available to the LLM.

    Args:
        filepath: Path to the PDF file on disk.

    Returns:
        A clean, logically ordered Markdown string (with an appended [EMBEDDED LINKS]
        section if any hyperlinks are found). Raises ValueError if no text
        can be extracted.
    """
    doc = fitz.open(filepath)
    
    try:
        # 1. Extract structural markdown using pymupdf4llm
        full_text = pymupdf4llm.to_markdown(doc)
    except Exception as e:
        doc.close()
        raise ValueError(f"pymupdf4llm extraction failed: {e}")

    # Strip null bytes that would crash PostgreSQL
    full_text = full_text.replace("\x00", "").strip()

    if not full_text:
        doc.close()
        raise ValueError(
            "Could not extract any text from the PDF. It may be image-based or scanned."
        )

    # 2. Extract hidden hyperlinks natively
    found_urls = []
    for page in doc:
        for link in page.get_links():
            uri = link.get("uri", "")
            if uri and uri not in found_urls:
                found_urls.append(uri)

    doc.close()

    # 3. Append links section so the LLM can see them for template filling
    if found_urls:
        url_section = "\n\n[EMBEDDED LINKS FROM PDF]\n" + "\n".join(found_urls)
        full_text += url_section
        logger.info(f"Extracted {len(found_urls)} hyperlinks from PDF links layer")

    logger.info(f"Extracted {len(full_text)} chars from '{filepath}'")
    return full_text


def save_resume_file(telegram_id: int, file_bytes: bytes, filename: str) -> str:
    """
    Save resume PDF to disk.

    Args:
        telegram_id: User's Telegram ID
        file_bytes: Raw file bytes
        filename: Original filename

    Returns:
        Path to saved file
    """
    ensure_resumes_dir()

    # Sanitize filename
    safe_name = f"{telegram_id}_{filename.replace(' ', '_')}"
    filepath = RESUMES_DIR / safe_name

    # Remove old resume if exists
    for old_file in RESUMES_DIR.glob(f"{telegram_id}_*"):
        old_file.unlink()
        logger.info(f"Removed old resume: {old_file}")

    filepath.write_bytes(file_bytes)
    logger.info(f"Saved resume for user {telegram_id}: {filepath}")
    return str(filepath)


def get_resume_path(telegram_id: int) -> str | None:
    """Find the stored resume file path for a user."""
    ensure_resumes_dir()
    files = list(RESUMES_DIR.glob(f"{telegram_id}_*"))
    return str(files[0]) if files else None


def delete_resume_file(telegram_id: int) -> bool:
    """Delete stored resume file for a user."""
    ensure_resumes_dir()
    deleted = False
    for f in RESUMES_DIR.glob(f"{telegram_id}_*"):
        f.unlink()
        deleted = True
    return deleted
