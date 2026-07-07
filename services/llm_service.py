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
            timeout=30.0,
        )
        model = settings.NVIDIA_MODEL_70B
    else:
        client = AsyncOpenAI(
            base_url=settings.NVIDIA_BASE_URL,
            api_key=settings.NVIDIA_API_KEY_8B,
            timeout=15.0,
        )
        model = settings.NVIDIA_MODEL_8B

    return client, model


SYSTEM_PROMPT = """You are an expert tech cover letter writer specializing in frontend development roles for freshers and early-career developers.
Write a concise, high-impact, first-person cover letter (MAXIMUM 150-200 words).
CRITICAL RULES:
- The candidate is a fresher or early-career frontend developer (0-1 years). Frame their projects, college work, and open-source contributions as real experience.
- DO NOT INCLUDE ANY HEADINGS, TITLES, OR SUBJECT LINES. Start directly with the first paragraph.
- NEVER start with "As a seasoned...", "I am writing to express...", or any generic opening. Start with a strong hook about what frontend work they've built and why it fits this role.
- Emphasize frontend-specific strengths: UI quality, component architecture, performance, responsive design, accessibility, or state management — whichever the resume shows.
- Be specific about the candidate's projects or skills matching the job's frontend requirements. Show what they built, not just what they know.
- Highlight 1-2 specific, concrete frontend projects or achievements.
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


ATS_SYSTEM_PROMPT = """You are an expert Tech Recruiter and ATS system that compares a candidate's resume to a job description with strict, literal accuracy.

## THE GOLDEN RULE — READ THIS FIRST:
A skill can ONLY go into "matching_keywords" or "tech_found" if it is EXPLICITLY mentioned in the resume text.
NEVER infer, assume, or guess. If Redux is not written in the resume, it is MISSING. Period.
Knowing React does NOT mean the candidate knows Redux. Knowing JavaScript does NOT mean they know TypeScript.
Every skill must have explicit textual evidence in the resume to be counted as matched.

## INSTRUCTIONS:
- Scan the JD for every concrete skill, library, tool, and technology it mentions.
- For EACH one, check if it literally appears in the resume text. If yes -> tech_found. If no -> missing_hard_skills.
- missing_hard_skills: specific named tools, libraries, frameworks the JD requires but are absent from the resume (e.g., Redux, Vite, D3.js, PWA, PostgreSQL).
- missing_soft_tech_skills: methodological/conceptual gaps (e.g., CI/CD, Agile, performance optimization, accessibility practices).
- matching_keywords: skills the resume has that are relevant to the JD — max 8 items.
- Do NOT penalize for missing backend/DevOps skills unless the JD explicitly lists them as required.
- IGNORE generic soft skills like "leadership", "creative", "passionate".
- Be honest and precise. The user needs accurate gaps to improve their resume.

You must return EXACTLY and ONLY valid JSON matching this schema:
{
  "matching_keywords": [<max 8 skills the resume explicitly has that match the JD>],
  "missing_hard_skills": [<specific tools/libraries/frameworks in the JD but NOT found in the resume>],
  "missing_soft_tech_skills": [<conceptual/methodological gaps e.g. CI/CD, Agile, accessibility>],
  "tech_found": [<exact tools explicitly in BOTH the resume and JD>],
  "suggestions": [<2-3 sentences of honest, specific, actionable advice. Name actual things to build or learn.>]
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


RESUME_EXTRACTION_SYSTEM_PROMPT = """You are an expert resume parser. Extract all information from the provided resume text into a structured JSON format.

CRITICAL RULES:
- Return ONLY valid JSON, no markdown, no code blocks, just raw JSON.
- CRITICAL JSON RULE: Ensure all internal double quotes inside strings are correctly escaped (e.g., \" ). Do NOT forget any commas between properties.
- If a field is not present, use null or an empty array [].
- For links: check both the text content AND any section labelled "[EMBEDDED LINKS FROM PDF]" at the bottom.
- GitHub links usually contain "github.com". LinkedIn links contain "linkedin.com". Project live links contain vercel.app, netlify.app, or a custom domain.
- Escape ALL special LaTeX characters in text: & → \\&, % → \\%, $ → \\$, # → \\#, _ → \\_, { → \\{, } → \\}, ~ → \\textasciitilde{}, ^ → \\textasciicircum{}
- For bullet points: write clean, impactful sentences. Each bullet should be a COMPLETE sentence with a strong action verb.
- Include at most 3 projects. If there are more, pick the 3 most impressive.
- For experience: include ALL jobs found.
- CRITICAL: Do NOT duplicate entries. If a company/startup is extracted under "experience", DO NOT extract it again under "projects". Every entry must be unique to its category.

Return JSON in EXACTLY this format:
{
  "name": "Full Name",
  "headline": "Role Title (e.g. Frontend Developer)",
  "email": "email@example.com",
  "phone": "+91-XXXXXXXXXX or null",
  "github": "https://github.com/username or null",
  "linkedin": "https://linkedin.com/in/username or null",
  "education": [
    {
      "institution": "University Name",
      "degree": "Bachelor of Technology",
      "years": "2021--2025"
    }
  ],
  "experience": [
    {
      "company": "Company Name",
      "title": "Job Title",
      "duration": "Month Year -- Month Year",
      "link": "https://live-link-or-null",
      "bullets": ["Bullet 1 describing impact.", "Bullet 2 with metrics if available."]
    }
  ],
  "projects": [
    {
      "name": "Project Name",
      "duration": "Month Year -- Present",
      "live_link": "https://live-url-or-null",
      "code_link": "https://github-url-or-null",
      "bullets": ["Bullet 1 describing tech and impact.", "Bullet 2."]
    }
  ],
  "skills": [
    {"category": "Frontend Engineering", "items": "React, Next.js, TypeScript"},
    {"category": "Backend & Tools", "items": "Node.js, PostgreSQL, Git"}
  ],
  "coding_profiles": [
    {"platform": "LeetCode", "link": "https://leetcode.com/...", "stats": "400+ problems solved | max rating 1750"}
  ]
}"""


async def extract_resume_json(resume_text: str) -> dict:
    """
    Parse raw resume text (including embedded URLs section) into a structured dict
    ready to be injected into the LaTeX Jinja2 template.

    Args:
        resume_text: Full extracted text from PDF (including [EMBEDDED LINKS FROM PDF] section)

    Returns:
        Parsed resume dict, or raises RuntimeError on failure
    """
    import json as _json
    client, model = _get_client(LLMMode.QUALITY)

    user_message = f"""Parse this resume into the exact JSON format specified:

{resume_text[:4000]}

Return the JSON now:"""

    for attempt in range(2):
        try:
            logger.info(f"Extracting resume JSON with {model} (attempt {attempt + 1})")
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": RESUME_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=3000,
                top_p=1,
            )
            result = response.choices[0].message.content.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]
            result = result.strip()
            
            try:
                data = _json.loads(result)
            except _json.JSONDecodeError as je:
                logger.warning(f"JSON syntax error: {je}. Attempting auto-repair with LLM...")
                fast_client, fast_model = _get_client(LLMMode.FAST)
                repair_prompt = f"The following JSON string is invalid. Fix the syntax errors (like missing commas or unescaped quotes) and return ONLY the valid raw JSON. Do not change the content.\n\n{result}"
                repair_res = await fast_client.chat.completions.create(
                    model=fast_model,
                    messages=[{"role": "user", "content": repair_prompt}],
                    temperature=0.0,
                    max_tokens=3000
                )
                repaired = repair_res.choices[0].message.content.strip()
                if repaired.startswith("```json"):
                    repaired = repaired[7:]
                if repaired.startswith("```"):
                    repaired = repaired[3:]
                if repaired.endswith("```"):
                    repaired = repaired[:-3]
                data = _json.loads(repaired.strip())
                
            logger.info(f"Resume JSON extracted: {len(data.get('projects', []))} projects, {len(data.get('experience', []))} jobs")
            return data
        except Exception as e:
            logger.error(f"Resume extraction error (attempt {attempt + 1}): {e}")
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                raise RuntimeError(f"Failed to extract resume JSON: {e}")

    raise RuntimeError("Resume extraction failed after retries")


BULLET_OPTIMIZATION_SYSTEM_PROMPT = """You are an expert ATS resume optimizer and Senior Technical Recruiter. You will be given:
1. A JSON object containing "experience" and "projects" arrays.
2. A job description

You will perform TWO passes over the resume:

--- PASS 1 (The Quality Audit) ---
Evaluate every single bullet point against strict quality standards (concise, action-oriented, metric-driven).
- IF a bullet is poorly written (rambling, passive voice, missing impact), rewrite it to be strong and concise.
- IF a bullet is already well-written (strong action verbs, concise, under 2 lines), DO NOT change it during this pass. Leave it exactly as is.

--- PASS 2 (The Organic Keyword Weave) ---
Look at the missing ATS keywords provided.
Find the 1 or 2 most logically relevant bullets in the entire resume (from Pass 1), and restructure their core sentence to naturally incorporate the missing keywords.
- DO NOT just tack the keywords onto the end of the sentence with a comma (e.g. "...using React, incorporating accessibility-driven development"). This is robotic and gets rejected.
- Weave the missing keywords naturally into the core action verb or structure.
- GOOD WEAVE: "Engineered a Next.js PWA using Zustand, optimizing performance and enforcing accessibility-driven development."
- BAD TACK-ON (LAZY): "Engineered an installable Next.js PWA, prioritizing accessibility-driven development." (Do not just append phrases to the end).
- A maximum of 1 or 2 bullets across the ENTIRE resume should receive keywords. Do not keyword stuff every section.

CRITICAL RULES:
- Return ONLY the updated JSON containing the "experience" and "projects" arrays.
- Keep bullets truthful — only add keywords where they genuinely fit.
- Escape ALL special LaTeX characters: & → \\&, % → \\%, $ → \\$, # → \\#, _ → \\_, { → \\{, } → \\}
- No markdown, no code blocks. Return raw JSON only."""


async def optimize_resume_bullets(resume_json: dict, job_description: str, missing_keywords: list[str]) -> dict:
    """
    Rewrite experience and project bullets in resume_json to naturally incorporate
    the ATS keywords that are missing for a specific job description.

    Args:
        resume_json: Structured resume dict from extract_resume_json()
        job_description: The target job description text
        missing_keywords: List of missing keywords identified by the ATS analyzer

    Returns:
        Updated resume_json with optimized bullet points
    """
    import json as _json
    client, model = _get_client(LLMMode.QUALITY)

    import copy
    
    partial_json = {
        "experience": resume_json.get("experience", []),
        "projects": resume_json.get("projects", [])
    }

    keywords_str = ", ".join(missing_keywords) if missing_keywords else "general ATS optimization"

    user_message = f"""Resume JSON:
{_json.dumps(partial_json, indent=2)}

Job Description:
{job_description[:1500]}

Missing ATS keywords to incorporate: {keywords_str}

Rewrite the bullet points to include these keywords naturally. Return the updated JSON:"""

    for attempt in range(2):
        try:
            logger.info(f"Optimizing resume bullets with {model} (attempt {attempt + 1})")
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": BULLET_OPTIMIZATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=2500,
                top_p=1,
            )
            result = response.choices[0].message.content.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]
            updated_partial = _json.loads(result.strip())
            
            final_json = copy.deepcopy(resume_json)
            if "experience" in updated_partial:
                final_json["experience"] = updated_partial["experience"]
            if "projects" in updated_partial:
                final_json["projects"] = updated_partial["projects"]
                
            logger.info("Resume bullets optimized successfully")
            return final_json
        except Exception as e:
            logger.error(f"Bullet optimization error (attempt {attempt + 1}): {e}")
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                # Return original as fallback — better to send unoptimized PDF than fail
                logger.warning("Returning original resume JSON as fallback")
                return resume_json

    return resume_json

