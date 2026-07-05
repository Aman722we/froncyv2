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


def _render_latex(resume_data: dict) -> str:
    """Render the Jinja2 template with the given resume data."""
    env = _get_jinja_env()
    template = env.get_template(TEMPLATE_NAME)
    return template.render(**resume_data)


async def compile_resume_pdf(resume_data: dict) -> bytes:
    """
    Compile a resume PDF from structured data using Jinja2 + pdflatex.

    Args:
        resume_data: Structured resume dict (from extract_resume_json / optimize_resume_bullets)

    Returns:
        PDF file contents as bytes

    Raises:
        RuntimeError: If pdflatex fails or is not installed
    """
    try:
        latex_source = _render_latex(resume_data)
    except Exception as e:
        raise RuntimeError(f"Template rendering failed: {e}")

    # Run pdflatex in a temporary directory so temp files are self-contained
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / "resume.tex"
        pdf_path = Path(tmpdir) / "resume.pdf"

        tex_path.write_text(latex_source, encoding="utf-8")
        logger.info(f"LaTeX source written ({len(latex_source)} chars) to {tex_path}")

        # pdflatex flags:
        #   -interaction=nonstopmode  → don't pause on errors; keep compiling
        #   -halt-on-error            → exit with non-zero code on fatal errors
        #   -output-directory         → write all generated files to tmpdir
        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={tmpdir}",
            str(tex_path),
        ]

        try:
            # Run in executor so we don't block the asyncio event loop
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
            raise RuntimeError(
                "pdflatex is not installed on this server. "
                "Please add texlive to the Railway nixPkgsFilter."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("pdflatex timed out after 60 seconds.")

        if result.returncode != 0:
            # Log the pdflatex output for debugging
            log_output = result.stdout[-3000:] if result.stdout else result.stderr[-3000:]
            logger.error(f"pdflatex failed (exit {result.returncode}):\n{log_output}")
            raise RuntimeError(f"pdflatex compilation failed. Exit code: {result.returncode}")

        if not pdf_path.exists():
            raise RuntimeError("pdflatex ran successfully but PDF output was not found.")

        pdf_bytes = pdf_path.read_bytes()
        logger.info(f"PDF compiled successfully: {len(pdf_bytes)} bytes")
        return pdf_bytes
