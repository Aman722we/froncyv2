"""
Resume PDF text extraction using pypdf.
"""
import os
from pathlib import Path
from pypdf import PdfReader
from loguru import logger


RESUMES_DIR = Path("resumes")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def ensure_resumes_dir():
    """Create resumes directory if it doesn't exist."""
    RESUMES_DIR.mkdir(exist_ok=True)


def extract_text_from_pdf(filepath: str) -> str:
    """
    Extract plain text from a PDF file located on disk using pypdf.
    Also extracts embedded hyperlinks (GitHub, LinkedIn, portfolio URLs)
    from the PDF's annotation layer so we don't lose clickable links.

    Args:
        filepath: Path to the PDF file

    Returns:
        Extracted text string (with appended URLs section if any found)
    """
    try:
        reader = PdfReader(filepath)
        text_parts = []
        found_urls = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

            # Extract hyperlinks from the annotation layer
            if "/Annots" in page:
                for annotation in page["/Annots"]:
                    try:
                        obj = annotation.get_object()
                        if obj.get("/Subtype") == "/Link":
                            uri_obj = obj.get("/A")
                            if uri_obj and "/URI" in uri_obj:
                                url = uri_obj["/URI"]
                                if url and url not in found_urls:
                                    found_urls.append(url)
                    except Exception:
                        pass  # Skip malformed annotations silently

        full_text = "\n".join(text_parts).strip()

        if not full_text:
            raise ValueError("Could not extract any text from the PDF. It may be image-based.")

        # Append URLs section so the LLM can see them for template filling
        if found_urls:
            url_section = "\n\n[EMBEDDED LINKS FROM PDF]\n" + "\n".join(found_urls)
            full_text += url_section
            logger.info(f"Extracted {len(found_urls)} hyperlinks from PDF annotations")

        logger.info(f"Extracted {len(full_text)} chars from PDF ({len(reader.pages)} pages)")
        return full_text

    except Exception as e:
        if "Could not extract" in str(e):
            raise
        logger.error(f"PDF extraction error: {e}")
        raise ValueError(f"Failed to process PDF: {str(e)}")



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
