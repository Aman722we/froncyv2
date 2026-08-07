"""
ATS Resume PDF Builder — Jinja2 + pdflatex pipeline.

Workflow:
  1. Render the Jinja2 LaTeX template with the user's structured resume data.
  2. Write the .tex file to a temp directory.
  3. Run pdflatex in a subprocess (non-interactive, no network access).
  4. Return the compiled PDF as bytes to be sent via Telegram.
"""
import os
import asyncio
import tempfile
import subprocess
import re
import pymupdf
from pathlib import Path
from loguru import logger
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Path to the template file
ASSETS_DIR = Path(__file__).parent.parent / "assets"
TEMPLATE_NAME = "resume_template.tex.j2"


def _get_jinja_env() -> Environment:
    """
    Returns a Jinja2 environment configured to use (((var))) and ((* *)) delimiters
    so they don't clash with LaTeX's {{ }} curly braces.
    """
    return Environment(
        loader=FileSystemLoader(str(ASSETS_DIR)),
        autoescape=False,           # LaTeX is NOT HTML — disable HTML escaping
        variable_start_string="(((", variable_end_string=")))",
        block_start_string="((*",   block_end_string="*))",
        comment_start_string="((#", comment_end_string="#))",
        keep_trailing_newline=True,
    )


LATEX_SUBS = (
    (re.compile(r'\\'), r'\\textbackslash '),
    (re.compile(r'([{}_#%&$])'), r'\\\1'),
    (re.compile(r'~'), r'\~{}'),
    (re.compile(r'\^'), r'\^{}'),
    (re.compile(r'"'), r"''"),
    # NOTE: '...' -> '\dots' is intentionally NOT here.
    # URLs may contain '...' as placeholders (e.g. linkedin.com/in/...)
    # and \dots inside \href{} is an undefined control sequence that
    # crashes pdflatex. We handle '...' in plain text at the call site.
)

def sanitise_url(url: str) -> str:
    """
    Clean a URL for safe use inside LaTeX \href{}{}.
    - Strips '...' / placeholder text that would cause pdflatex to crash.
    - Returns empty string if the value doesn't look like a real URL.
    """
    if not isinstance(url, str):
        return ""
    # Remove common placeholder suffixes
    url = url.strip()
    url = re.sub(r'\.\.\.*$', '', url)       # trailing ...
    url = re.sub(r'\s*\(link not provided\)', '', url, flags=re.IGNORECASE)
    url = re.sub(r'\s*\(not provided\)', '', url, flags=re.IGNORECASE)
    url = url.strip().rstrip('/')
    # Must start with a protocol or www to be a real URL
    if not re.match(r'^(https?://|www\.)', url, re.IGNORECASE):
        return ""
    return url

def escape_latex(value: str) -> str:
    """Escapes special characters for LaTeX and removes unsupported Unicode."""
    if not isinstance(value, str):
        return value

    # 1. Strip unsupported Unicode (pdflatex crashes on weird symbols like ⌢, emojis)
    # Keep Basic Latin + Latin-1 Supplement (0x00 - 0xFF) and common punctuation
    def is_safe(c: str) -> bool:
        cp = ord(c)
        return cp <= 0x00FF or cp in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026)
        
    newval = "".join(c for c in value if is_safe(c))

    # 2. Escape standard LaTeX special characters
    for pattern, replacement in LATEX_SUBS:
        newval = pattern.sub(replacement, newval)

    # 3. Now safely convert '...' → '\dots' in plain text (not inside URLs)
    newval = re.sub(r'\.\.\.', r'\\dots ', newval)

    return newval

def escape_dict_for_latex(data):
    """Recursively escape strings in a dict/list for LaTeX."""
    if isinstance(data, dict):
        return {k: escape_dict_for_latex(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [escape_dict_for_latex(v) for v in data]
    elif isinstance(data, str):
        return escape_latex(data)
    else:
        return data

# URL fields that must be sanitised (not escaped like plain text)
URL_FIELDS = {"linkedin", "github", "portfolio"}

def _sanitise_url_fields(data: dict) -> dict:
    """
    Sanitise known top-level URL fields before the rest of the data
    is LaTeX-escaped. Also sanitises exp.link and proj.live_link/code_link.
    """
    data = dict(data)
    for key in URL_FIELDS:
        if key in data:
            data[key] = sanitise_url(data[key])
    if "experience" in data:
        data["experience"] = [
            {**exp, "link": sanitise_url(exp.get("link", ""))}
            for exp in (data["experience"] or [])
        ]
    if "projects" in data:
        data["projects"] = [
            {
                **proj,
                "live_link": sanitise_url(proj.get("live_link", "")),
                "code_link": sanitise_url(proj.get("code_link", "")),
            }
            for proj in (data["projects"] or [])
        ]
    if "coding_profiles" in data:
        data["coding_profiles"] = [
            {**cp, "link": sanitise_url(cp.get("link", ""))}
            for cp in (data["coding_profiles"] or [])
        ]
    return data


def _render_latex(resume_data: dict, font_size: str = "11pt") -> str:
    """Render the Jinja2 template with the given resume data."""
    # 1. Sanitise URL fields first (must NOT go through escape_latex)
    sanitised = _sanitise_url_fields(resume_data)
    # 2. Escape all remaining plain-text fields for LaTeX
    escaped_data = escape_dict_for_latex(sanitised)
    # 3. Restore sanitised URLs (escape_dict_for_latex would corrupt them)
    for key in URL_FIELDS:
        if key in sanitised:
            escaped_data[key] = sanitised[key]  # already clean, don't re-escape
    if "experience" in sanitised:
        for i, exp in enumerate(sanitised["experience"]):
            escaped_data["experience"][i]["link"] = exp["link"]
    if "projects" in sanitised:
        for i, proj in enumerate(sanitised["projects"]):
            escaped_data["projects"][i]["live_link"] = proj["live_link"]
            escaped_data["projects"][i]["code_link"] = proj["code_link"]
    if "coding_profiles" in sanitised:
        for i, cp in enumerate(sanitised["coding_profiles"]):
            escaped_data["coding_profiles"][i]["link"] = cp["link"]
    env = _get_jinja_env()
    template = env.get_template(TEMPLATE_NAME)
    return template.render(**escaped_data, font_size=font_size)


async def compile_resume_pdf(resume_data: dict) -> bytes:
    """
    Compile a resume PDF from structured data using Jinja2 + pdflatex.
    Auto-scales dense resumes to 10pt if they span multiple pages.
    """
    # Pass 1: Try compiling at default 11pt
    pdf_bytes, page_count = await _compile_pdf_with_font(resume_data, "11pt")
    
    if page_count > 1:
        logger.warning(f"Resume spilled onto {page_count} pages at 11pt. Auto-scaling down to 10pt.")
        # Pass 2: Re-compile at 10pt to fit 1 page
        pdf_bytes, _ = await _compile_pdf_with_font(resume_data, "10pt")
        
    return pdf_bytes

async def _compile_pdf_with_font(resume_data: dict, font_size: str) -> tuple[bytes, int]:
    """Helper to compile PDF and return (pdf_bytes, page_count)."""
    try:
        latex_source = _render_latex(resume_data, font_size)
    except Exception as e:
        raise RuntimeError(f"Template rendering failed: {e}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / "resume.tex"
        pdf_path = Path(tmpdir) / "resume.pdf"

        tex_path.write_text(latex_source, encoding="utf-8")
        logger.info(f"LaTeX source written ({len(latex_source)} chars) to {tex_path}")

        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={tmpdir}",
            str(tex_path),
        ]

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=tmpdir,
                )
            )
        except FileNotFoundError:
            raise RuntimeError("pdflatex is not installed on this server.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("pdflatex timed out after 60 seconds.")

        if result.returncode != 0:
            log_output = result.stdout[-3000:] if result.stdout else result.stderr[-3000:]
            logger.error(f"pdflatex failed (exit {result.returncode}):\n{log_output}")
            raise RuntimeError(f"pdflatex compilation failed. Exit code: {result.returncode}")

        if not pdf_path.exists():
            raise RuntimeError("pdflatex ran successfully but PDF output was not found.")

        pdf_bytes = pdf_path.read_bytes()
        
        # Parse the PDF to count pages
        try:
            doc = pymupdf.open(pdf_path)
            page_count = len(doc)
            doc.close()
        except Exception as e:
            logger.error(f"Failed to read PDF page count: {e}")
            page_count = 1  # Fallback to 1 on read error
            
        logger.info(f"PDF compiled successfully ({font_size}): {len(pdf_bytes)} bytes, {page_count} pages")
        return pdf_bytes, page_count
