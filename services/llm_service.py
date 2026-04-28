"""
AI Cover Letter Generation via NVIDIA NIM API (OpenAI-compatible).

Uses two separate API keys for Llama 3 8B (Fast) and 70B (Quality).
Rate limit: 40 RPM per model, no daily cap.
"""
import asyncio
from enum import Enum
from openai import AsyncOpenAI
from loguru import logger
from config import settings


class LLMMode(Enum):
    FAST = "fast"       # Llama 3 8B — ~3s, all users
    QUALITY = "quality"  # Llama 3 70B — ~12s, Pro+/Premium only


def get_mode_for_plan(plan: str) -> LLMMode:
    """Determine which model a user can access based on their plan."""
    if plan in ("proplus", "premium"):
        return LLMMode.QUALITY
    return LLMMode.FAST


def _get_client(mode: LLMMode) -> tuple[AsyncOpenAI, str]:
    """Get the appropriate OpenAI client and model name for the mode."""
    if mode == LLMMode.QUALITY:
        client = AsyncOpenAI(
            base_url=settings.NVIDIA_BASE_URL,
            api_key=settings.NVIDIA_API_KEY_70B,
        )
        model = settings.NVIDIA_MODEL_70B
    else:
        client = AsyncOpenAI(
            base_url=settings.NVIDIA_BASE_URL,
            api_key=settings.NVIDIA_API_KEY_8B,
        )
        model = settings.NVIDIA_MODEL_8B

    return client, model


SYSTEM_PROMPT = """You are an expert, modern tech cover letter writer.
Write a concise, high-impact, first-person cover letter (MAXIMUM 150-200 words).
CRITICAL RULES:
- DO NOT INCLUDE ANY HEADINGS, TITLES, OR SUBJECT LINES. Start directly with the first paragraph.
- NEVER start with "As a seasoned...", "I am writing to express...", or any generic opening. Start directly with a strong, confident hook about why your background solves their specific problems.
- Be highly concise. Get straight to the point. Short paragraphs.
- Be specific about the candidate's experience matching the job requirements, but don't just list skills. Show impact.
- Highlight 1-2 specific concrete achievements.
- DO NOT INCLUDE ANY PREAMBLES, INTROS, OR GREETINGS (like "Here is your cover letter:").
- DO NOT include addresses, dates, or "Dear Hiring Manager" header.
- Output ONLY the raw cover letter body text, starting immediately with the first sentence."""

TONE_PROMPTS = {
    "formal": "Write in a professional, direct, and confident tone.",
    "friendly": "Write in a warm, approachable, but highly professional tone.",
    "concise": "Write an ultra-short, punchy version (100-150 words). Get straight to the value.",
}


async def generate_cover_letter(
    resume_text: str,
    job_description: str,
    mode: LLMMode = LLMMode.FAST,
    tone: str = "formal",
) -> str:
    """
    Generate a tailored cover letter using NVIDIA NIM API.

    Args:
        resume_text: Extracted text from user's resume
        job_description: Job posting text or description
        mode: FAST (8B) or QUALITY (70B)
        tone: formal, friendly, or concise

    Returns:
        Generated cover letter text

    Raises:
        Exception on API failure after retries
    """
    client, model = _get_client(mode)

    tone_instruction = TONE_PROMPTS.get(tone, TONE_PROMPTS["formal"])

    user_message = f"""Resume:
{resume_text[:2000]}

Job Description:
{job_description[:1500]}

{tone_instruction}

Write the cover letter now:"""

    # Attempt with 1 retry
    for attempt in range(2):
        try:
            logger.info(f"Generating cover letter with {model} (attempt {attempt + 1})")

            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.7,
                max_tokens=500,
                top_p=1,
            )

            result = response.choices[0].message.content.strip()
            logger.info(f"Cover letter generated: {len(result)} chars")
            return result

        except Exception as e:
            logger.error(f"LLM API error (attempt {attempt + 1}): {e}")
            if attempt == 0:
                # Exponential backoff before retry
                await asyncio.sleep(2)
            else:
                raise

    # Should not reach here, but fallback
    raise RuntimeError("Cover letter generation failed after retries")


def get_fallback_cover_letter(job_title: str, company: str) -> str:
    """
    Jinja2-style template fallback when API is completely down.
    Returns a basic template the user can customize.
    """
    return f"""I am writing to express my interest in the {job_title} position at {company}.

With my experience in frontend development, I believe I would be a strong addition to your team. My skills in building responsive, performant web applications align well with the requirements of this role.

I would welcome the opportunity to discuss how my background and skills would benefit {company}. I look forward to hearing from you.

[⚠️ This is a template — our AI service is temporarily unavailable. Please personalize this before sending.]"""


def get_mode_display(mode: LLMMode) -> str:
    """Get user-friendly display text for the LLM mode."""
    if mode == LLMMode.QUALITY:
        return "✨ Quality Mode (Llama 3 70B)"
    return "⚡ Fast Mode (Llama 3 8B)"

ATS_SYSTEM_PROMPT = """You are an expert, nuanced Tech Recruiter and ATS analyzer.
Compare the provided Resume against the Job Description thoughtfully.

CRITICAL INSTRUCTIONS:
- Identify the CORE NATURE of the role. Is it backend-heavy? Frontend-heavy? Full-stack? DevRel? Do not let a few matching keywords (like React or UI) artificially inflate the score if the core domain (like Distributed Systems, Kafka, Java/Kotlin) is missing.
- "Backend-first engineer who can do frontend" is a VERY DIFFERENT profile from "Frontend engineer with some backend exposure". If the core domain mismatches, the score MUST reflect reality (e.g. 40-60% MAX), regardless of how many secondary/frontend tools match.
- Distinguish between absolute requirements vs nice-to-haves. For frontend roles, UI/State/TS is core; CI/CD or AWS is often a nice-to-have or exposure-based. Don't heavily penalize missing infrastructure tools unless it's a DevOps role.
- Recognize proxy signals: If they built complex, data-driven UIs or PWA, count that as system-thinking, cross-functional collaboration, and end-to-end ownership. Do not mark these as missing just because the exact word isn't there.
- Accurately assess Experience Level mismatch (e.g., Fresher vs 5+ years requirement). Call this out as the primary gap in your suggestions if true, rather than nitpicking specific secondary tools.
- Identify real, meaningful gaps like lack of core backend architectures, scale metrics, or production depth, rather than generic missing keywords.
- IGNORE generic soft skills entirely like "leadership", "creative", "passionate".

You must return EXACTLY and ONLY valid JSON matching this schema:
{
  "score": <0-100 integer representing holistic tech and experience match. DO NOT INFLATE. Heavily penalize core domain/experience mismatches>,
  "matching_keywords": [<list of max 8 highly relevant hard skills or system concepts the user HAS>],
  "missing_keywords": [<list of max 8 real technical or conceptual gaps (e.g. observability, distributed systems) that actually matter>],
  "tech_found": [<list of exact tools/languages found in both>],
  "tech_missing": [<list of exact tools/languages requested but missing. Don't list infra tools for frontend roles, but DO list core backend tools if the role requires them.>],
  "suggestions": [
     <2-3 sentences of honest, actionable advice. DO NOT suggest faking skills. Discuss core domain mismatches (e.g. "This role is backend-centric...") and experience level gaps honestly.>
  ]
}

No markdown wrappers, no code blocks, just raw JSON."""

async def generate_ats_analysis(
    resume_text: str,
    job_description: str,
    mode: LLMMode = LLMMode.QUALITY,
) -> str:
    """
    Generate ATS analysis JSON using NVIDIA NIM API.
    """
    client, model = _get_client(mode)

    user_message = f"""Resume:
{resume_text[:2500]}

Job Description:
{job_description[:2000]}

Analyze the match and provide the JSON:"""

    for attempt in range(2):
        try:
            logger.info(f"Generating ATS analysis with {model} (attempt {attempt + 1})")

            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ATS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,  # Low temperature for strict JSON adherence
                max_tokens=600,
                top_p=1,
            )

            result = response.choices[0].message.content.strip()
            # Clean up markdown JSON wrappers if Llama injects them defensively
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            return result.strip()

        except Exception as e:
            logger.error(f"LLM ATS API error (attempt {attempt + 1}): {e}")
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                raise

    raise RuntimeError("ATS generation failed after retries")
