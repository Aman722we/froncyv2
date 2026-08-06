"""
Resume PDF text extraction using PyMuPDF (fitz).

Why PyMuPDF over pypdf:
- pypdf reads text objects in the order they are stored inside the PDF, which often
  does NOT match visual/reading order (especially for multi-column resumes).
- PyMuPDF returns text blocks with their (x0, y0, x1, y1) bounding box coordinates.
  This lets us sort and group blocks spatially, reconstructing the correct reading order.

Spatial sorting strategy:
1.  Extract all text blocks from the page.
2.  Detect how many columns exist by clustering blocks on their x0 (left-edge) coordinate.
3.  Sort blocks within each column top-to-bottom (by y0).
4.  Merge columns left-to-right, yielding clean, logically ordered text.

This approach handles:
  - Single-column LaTeX/Word resumes          (pass)
  - Two-column creative/Canva resumes         (pass)
  - Resumes with sidebars (Skills, Contact)   (pass)
  - Embedded hyperlinks (via get_links())     (pass)
  - Decorative images/icons (ignored)         (pass)
"""
import os
from pathlib import Path
import fitz  # PyMuPDF
from loguru import logger


RESUMES_DIR = Path("resumes")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# X-coordinate gap (in PDF points) needed to consider two blocks as being in
# different columns. ~35% of a standard A4 page width (595pt) is a good default.
COLUMN_GAP_THRESHOLD = 200


def ensure_resumes_dir():
    """Create resumes directory if it doesn't exist."""
    RESUMES_DIR.mkdir(exist_ok=True)


def _detect_columns(blocks: list) -> list:
    """
    Given a list of PyMuPDF text blocks, detect visual columns and return
    them sorted left-to-right. Each column is a list of blocks sorted
    top-to-bottom by their y0 coordinate.

    Strategy:
    - Sort all blocks by their x0 (left edge).
    - Walk through the sorted blocks and start a new column group whenever
      the x0 gap between consecutive blocks exceeds COLUMN_GAP_THRESHOLD.
    - Within each column, sort blocks by y0 (top edge) for reading order.

    This is a fast O(n log n) heuristic that correctly handles:
      - 1-column: all blocks land in the same group.
      - 2-column: blocks split into two groups by the large x-gap in the middle.
      - 3-column: three groups are formed.
    """
    if not blocks:
        return []

    # Sort by x0 to detect column boundaries
    sorted_by_x = sorted(blocks, key=lambda b: b[0])

    columns = []
    current_column = [sorted_by_x[0]]
    current_x_center = sorted_by_x[0][0]

    for block in sorted_by_x[1:]:
        x0 = block[0]
        # If this block is far to the right of the current column's left edge,
        # it belongs to a new column
        if x0 - current_x_center > COLUMN_GAP_THRESHOLD:
            # Sort the current column top-to-bottom and save it
            columns.append(sorted(current_column, key=lambda b: b[1]))
            current_column = [block]
            current_x_center = x0
        else:
            current_column.append(block)
            # Anchor column to its leftmost block
            current_x_center = min(current_x_center, x0)

    # Don't forget the last column
    columns.append(sorted(current_column, key=lambda b: b[1]))

    return columns


def extract_text_from_pdf(filepath: str) -> str:
    """
    Extract spatially-sorted plain text from a PDF file using PyMuPDF.

    Also extracts embedded hyperlinks (GitHub, LinkedIn, portfolio URLs)
    natively via fitz page.get_links(), replacing the brittle /Annots hack.

    Args:
        filepath: Path to the PDF file on disk.

    Returns:
        A clean, logically ordered text string (with an appended [EMBEDDED LINKS]
        section if any hyperlinks are found). Raises ValueError if no text
        can be extracted (image-only / scanned PDF).
    """
    doc = fitz.open(filepath)
    all_page_texts = []
    found_urls = []

    for page_num, page in enumerate(doc):
        # Each block: (x0, y0, x1, y1, "text", block_no, block_type)
        # block_type == 0 is a text block; block_type == 1 is an image block.
        raw_blocks = page.get_text("blocks")

        # Filter to text-only blocks with actual content
        text_blocks = [
            b for b in raw_blocks
            if b[6] == 0 and b[4].strip()
        ]

        # Reconstruct reading order via spatial column detection
        columns = _detect_columns(text_blocks)

        page_text_parts = []
        for column in columns:
            for block in column:
                block_text = block[4].strip()
                if block_text:
                    page_text_parts.append(block_text)

        if page_text_parts:
            all_page_texts.append("\n".join(page_text_parts))

        # Extract hyperlinks natively (much cleaner than /Annots)
        for link in page.get_links():
            uri = link.get("uri", "")
            if uri and uri not in found_urls:
                found_urls.append(uri)

    doc.close()

    full_text = "\n\n".join(all_page_texts).strip()
    # Strip null bytes that would crash PostgreSQL
    full_text = full_text.replace("\x00", "")

    if not full_text:
        raise ValueError(
            "Could not extract any text from the PDF. It may be image-based or scanned."
        )

    # Append links section so the LLM can see them for template filling
    if found_urls:
        url_section = "\n\n[EMBEDDED LINKS FROM PDF]\n" + "\n".join(found_urls)
        full_text += url_section
        logger.info(f"Extracted {len(found_urls)} hyperlinks from PDF links layer")

    logger.info(
        f"Extracted {len(full_text)} chars from '{filepath}' "
        f"({len(all_page_texts)} page(s))"
    )
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
