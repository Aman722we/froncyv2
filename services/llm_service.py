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
    FAST = "fast"       # GPT-OSS 20B
    QUALITY = "quality"  # GPT-OSS 120B


def get_mode_for_plan(plan: str) -> LLMMode:
    """Determine which model a user can access based on their plan."""
    if plan in ("proplus", "premium"):
        return LLMMode.QUALITY
    return LLMMode.FAST


import time

_key_cooldowns = {}
_rr_index_8b = 0
_rr_index_70b = 0

def _get_client(mode: LLMMode, timeout: float = 60.0) -> tuple[AsyncOpenAI, str]:
    """Get the appropriate OpenAI client and model name for the mode. Supports round-robin multi-key."""
    global _rr_index_8b, _rr_index_70b
    
    if mode == LLMMode.QUALITY:
        keys_str = settings.NVIDIA_API_KEY_70B
        model = settings.NVIDIA_MODEL_70B
        is_8b = False
    else:
        keys_str = settings.NVIDIA_API_KEY_8B
        model = settings.NVIDIA_MODEL_8B
        is_8b = True

    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    if not keys:
        raise ValueError("No API keys configured.")

    now = time.time()
    start_idx = _rr_index_8b if is_8b else _rr_index_70b
    
    selected_key = None
    for i in range(len(keys)):
        idx = (start_idx + i) % len(keys)
        candidate = keys[idx]
        if _key_cooldowns.get(candidate, 0.0) < now:
            selected_key = candidate
            if is_8b:
                _rr_index_8b = (idx + 1) % len(keys)
            else:
                _rr_index_70b = (idx + 1) % len(keys)
            break
            
    if not selected_key:
        # All keys on cooldown, pick the one freeing up earliest to avoid crashing
        selected_key = min(keys, key=lambda k: _key_cooldowns.get(k, 0.0))

    client = AsyncOpenAI(
        base_url=settings.NVIDIA_BASE_URL,
        api_key=selected_key,
        timeout=timeout,
        max_retries=0,
    )
    client._used_api_key = selected_key
    return client, model


# Role display names for prompt injection
ROLE_DISPLAY_NAMES: dict[str, str] = {
    "frontend": "frontend development",
    "backend": "backend development",
    "fullstack": "full stack development",
    "devops": "DevOps and cloud engineering",
    "mobile": "mobile app development",
    "data": "data science and machine learning",
    "other": "software engineering",
}

ROLE_STRENGTHS: dict[str, str] = {
    "frontend": "UI quality, component architecture, performance, responsive design, accessibility, or state management",
    "backend": "API design, database optimization, system scalability, security, or microservices architecture",
    "fullstack": "end-to-end feature delivery, API integration, database design, or full product ownership",
    "devops": "CI/CD pipelines, infrastructure-as-code, containerization, cloud cost optimization, or observability",
    "mobile": "app performance, offline capability, platform-specific UX, or cross-platform architecture",
    "data": "model accuracy, data pipeline design, feature engineering, experimentation, or business impact of insights",
    "other": "technical problem-solving, system design, code quality, or cross-functional collaboration",
}


def get_system_prompt(user_role: str = "frontend") -> str:
    """Build a role-specific system prompt for cover letter generation."""
    role_name = ROLE_DISPLAY_NAMES.get(user_role, "software engineering")
    role_strengths = ROLE_STRENGTHS.get(user_role, ROLE_STRENGTHS["other"])
    return f"""You are an expert tech cover letter writer specializing in {role_name} roles for freshers and early-career developers.
Write a concise, high-impact, first-person cover letter (MAXIMUM 150-200 words).
CRITICAL RULES:
- Highlight the candidate's core strengths based on their years of experience. For freshers, frame their projects as real experience. For experienced developers, emphasize their professional impact.
- DO NOT INCLUDE ANY HEADINGS, TITLES, OR SUBJECT LINES. Start directly with the first paragraph.
- NEVER start with "As a seasoned...", "I am writing to express...", or any generic opening. Start with a strong hook about what they've built and why it fits this role.
- Emphasize role-specific strengths: {role_strengths} — whichever the resume shows.
- Be specific about the candidate's projects or skills matching the job's requirements. Show what they built, not just what they know.
- Highlight 1-2 specific, concrete projects or achievements.
- DO NOT INCLUDE ANY PREAMBLES, INTROS, OR GREETINGS (like "Here is your cover letter:").
- DO NOT include addresses, dates, or "Dear Hiring Manager" header.
- Output ONLY the raw cover letter body text, starting immediately with the first sentence."""


# Legacy constant kept for any code still referencing SYSTEM_PROMPT directly
SYSTEM_PROMPT = get_system_prompt("frontend")


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
    user_role: str = "frontend",
) -> str:
    """
    Generate a tailored cover letter using NVIDIA NIM API.

    Args:
        resume_text: Extracted text from user's resume
        job_description: Job posting text or description
        mode: FAST (8B) or QUALITY (70B)
        tone: formal, friendly, or concise
        user_role: The user's selected role stream (e.g. frontend, backend, devops)

    Returns:
        Generated cover letter text

    Raises:
        Exception on API failure after retries
    """
    client, model = _get_client(mode)

    tone_instruction = TONE_PROMPTS.get(tone, TONE_PROMPTS["formal"])
    system_prompt = get_system_prompt(user_role)

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
                    {"role": "system", "content": system_prompt},
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
        return "✨ Quality Mode (GPT-OSS 120B)"
    return "⚡ Fast Mode (GPT-OSS 20B)"


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

    import re
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
                max_tokens=2000,
                top_p=1,
            )

            result = response.choices[0].message.content.strip()
            
            # Robust JSON extraction: Find the first { and last }
            json_match = re.search(r"\{.*\}", result, re.DOTALL)
            if json_match:
                result = json_match.group(0)

            return result

        except Exception as e:
            logger.error(f"LLM ATS API error (attempt {attempt + 1}): {e}")
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                raise

    raise RuntimeError("ATS generation failed after retries")


async def check_resume_parseable(resume_text: str) -> bool:
    """
    Quick sanity check — uses the fast 8B model to determine if the raw resume
    text is structured enough for the AI to extract experience/project bullets.

    Returns True if parseable, False if the layout is too complex (columns, tables, etc.)
    This runs in ~3 seconds and costs a fraction of a full extraction.
    """
    client, model = _get_client(LLMMode.FAST, timeout=20.0)

    # Only check the first 2000 chars — enough to detect structure
    snippet = resume_text[:2000]

    prompt = (
        "You are a basic resume sanity checker. You will receive raw text extracted from a PDF resume.\n\n"
        "Because our extraction system already handles multi-column layouts, your ONLY job is to verify that the PDF is not completely corrupted or unreadable.\n\n"
        "Answer NO if:\n"
        "- The text is literally unreadable gibberish, random symbols, or completely fragmented letters without real words.\n"
        "- It is clearly not a resume at all.\n\n"
        "Answer YES if:\n"
        "- You can see normal readable English words, names, skills, or job experience, even if the formatting is a bit strange.\n\n"
        "Reply with ONLY the single word YES or NO. Nothing else."
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Resume text:\n{snippet}"},
            ],
            temperature=0.0,
            max_tokens=50,
            extra_body={"reasoning_effort": "low"},
        )
        answer = response.choices[0].message.content.strip().upper()
        logger.info(f"Resume parseability check: {answer}")
        return "YES" in answer
    except Exception as e:
        logger.warning(f"Resume parseability check failed (defaulting to True): {e}")
        # Default to True on failure — don't block user from uploading
        return True


RESUME_EXTRACTION_SYSTEM_PROMPT = """You are a faithful resume data-entry clerk. Your ONLY job is to lift information out of the resume text and place it into a JSON structure. You are NOT a writer, editor, or advisor.

GOLDEN RULE — READ THIS FIRST:
Copy bullet points WORD-FOR-WORD exactly as they appear in the resume. Do NOT rephrase, summarize, shorten, or "improve" them. Treat each bullet like a legal document you are transcribing. Changing even one word is a critical failure.

CRITICAL RULES:
- Return ONLY valid JSON, no markdown, no code blocks, just raw JSON.
- CRITICAL JSON RULE: Ensure all internal double quotes inside strings are correctly escaped (e.g., \" ). Do NOT forget any commas between properties.
- If a field is not present, use null or an empty array [].
- For links: check both the text content AND any section labelled "[EMBEDDED LINKS FROM PDF]" at the bottom.
- GitHub links usually contain "github.com". LinkedIn links contain "linkedin.com". Project live links contain vercel.app, netlify.app, or a custom domain.
- Escape ALL special LaTeX characters in text: & → \\&, % → \\%, $ → \\$, # → \\#, _ → \\_, { → \\{, } → \\}, ~ → \\textasciitilde{}, ^ → \\textasciicircum{}
- Include ALL projects found — do NOT drop any project. Extract every single one.
- For experience: include ALL formal employment, internships, and organization-based roles.
- For projects: include ALL personal, academic, open-source, and side projects without a formal employer.
- CRITICAL: Do NOT duplicate entries. If an entry is classified as "experience", DO NOT extract it again under "projects". Every entry must be unique to its proper category.

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
      "bullets": ["Exact word-for-word copy of bullet 1.", "Exact word-for-word copy of bullet 2."]
    }
  ],
  "projects": [
    {
      "name": "Project Name",
      "duration": "Month Year -- Present",
      "live_link": "https://live-url-or-null",
      "code_link": "https://github-url-or-null",
      "bullets": ["Exact word-for-word copy of bullet 1.", "Exact word-for-word copy of bullet 2."]
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
    # Resume extraction produces a large JSON output — give it a longer timeout
    client, model = _get_client(LLMMode.QUALITY, timeout=90.0)

    user_message = f"""Parse this resume into the exact JSON format specified:

{resume_text[:12000]}

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
                temperature=0.0,
                max_tokens=5000,
                extra_body={"reasoning_effort": "low"},
                top_p=1,
            )
            import re
            result = response.choices[0].message.content.strip()
            match = re.search(r"\{.*\}", result, re.DOTALL)
            if match:
                result = match.group(0).strip()
            
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
                import re
                match = re.search(r"\{.*\}", repaired, re.DOTALL)
                if match:
                    repaired = match.group(0).strip()
                data = _json.loads(repaired)
                
            logger.info(f"Resume JSON extracted: {len(data.get('projects', []))} projects, {len(data.get('experience', []))} jobs")
            return data
        except Exception as e:
            logger.error(f"Resume JSON extraction failed: {e}")
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                error_str = str(e).lower()
                raise RuntimeError(f"Resume extraction failed: {'LLM timeout' if 'timeout' in error_str or 'timed out' in error_str else 'parsing error'}")

    raise RuntimeError("Resume extraction failed after retries")


BULLET_OPTIMIZATION_SYSTEM_PROMPT = """You are an expert ATS resume optimizer. You will be given a list of bullet points from a candidate's resume, a job description, and a list of missing ATS keywords.

Your task is to produce a DIFF PATCH — a tiny list of surgical replacements. You are NOT rewriting the entire resume.

## STEP 1: Quality Audit
Read all the bullets. Identify any bullets that are genuinely poorly written:
- Poorly written = passive voice ("was responsible for"), vague ("worked on stuff"), or has zero technical detail.
- Well-written = starts with a strong action verb, is specific, mentions technologies or metrics.
- For EACH poorly written bullet: write a new, improved version that MUST preserve every single technical keyword, tool, and metric from the original. Just fix the grammar and structure.
- For EACH well-written bullet: DO NOT touch it at all.

## STEP 2: Keyword Weave (max 1-2 bullets total)
From all bullets (original or improved), find the 1 or 2 most logically relevant ones to weave the missing ATS keywords into naturally.
- Weave organically into the sentence structure. Do NOT tack on at the end.
- GOOD: "Engineered a Next.js PWA using Zustand for state management, enforcing accessibility-driven development."
- BAD: "Engineered an installable Next.js PWA, incorporating accessibility-driven development."

## OUTPUT FORMAT — CRITICAL:
Return ONLY a JSON object with a single key "replacements" containing an array.
Each item in the array represents ONE bullet you changed (quality fix OR keyword weave).
Only include bullets you actually changed. If a bullet was already perfect and needed no changes, do NOT include it.

{
  "replacements": [
    {
      "original": "The exact original bullet text, copied character-for-character.",
      "improved": "The new improved bullet text with keywords woven in."
    }
  ]
}

If no changes are needed at all, return: {"replacements": []}
No markdown. No code blocks. Raw JSON only."""


async def optimize_resume_bullets(resume_json: dict, job_description: str, missing_keywords: list[str]) -> dict:
    """
    Uses a Diff-Patch approach to apply surgical improvements to resume bullets.
    The AI only outputs a list of (original -> improved) replacements.
    Python then applies those replacements, making it impossible for the AI to
    accidentally delete or hallucinate content across the rest of the resume.

    Args:
        resume_json: Structured resume dict from extract_resume_json()
        job_description: The target job description text
        missing_keywords: List of missing soft-tech keywords from the ATS analyzer

    Returns:
        Updated resume_json with only the patched bullet points changed
    """
    import json as _json
    import copy

    # Collect ALL bullets with metadata so we can patch by exact text match
    all_bullets: list[str] = []
    for exp in resume_json.get("experience", []):
        all_bullets.extend(exp.get("bullets", []))
    for proj in resume_json.get("projects", []):
        all_bullets.extend(proj.get("bullets", []))

    if not all_bullets:
        logger.warning("No bullets found in resume — skipping optimization")
        return resume_json

    keywords_str = ", ".join(missing_keywords) if missing_keywords else "general ATS optimization"

    user_message = f"""Here are all the bullet points from the candidate's resume (one per line, numbered):

{chr(10).join(f'{i+1}. {b}' for i, b in enumerate(all_bullets))}

Job Description:
{job_description[:1500]}

Missing ATS keywords to weave in: {keywords_str}

Apply your two-step process and return the diff patch JSON:"""

    client, model = _get_client(LLMMode.QUALITY, timeout=90.0)

    for attempt in range(2):
        try:
            logger.info(f"Generating bullet diff-patch with {model} (attempt {attempt + 1})")
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": BULLET_OPTIMIZATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=1500,  # Much smaller — we only need the patch, not the full resume
                top_p=1,
            )
            result = response.choices[0].message.content.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            patch = _json.loads(result.strip())
            replacements = patch.get("replacements", [])

            if not replacements:
                logger.info("AI returned empty diff-patch — resume bullets are already optimal")
                return resume_json

            # Build a lookup map: original_text -> improved_text
            patch_map: dict[str, str] = {}
            for r in replacements:
                orig = r.get("original", "").strip()
                improved = r.get("improved", "").strip()
                if orig and improved and orig != improved:
                    patch_map[orig] = improved

            logger.info(f"Applying {len(patch_map)} bullet patch(es) via Python — rest of resume untouched")

            # Apply the patch: Python does a simple string match-and-replace
            # The AI cannot touch anything outside the patch_map
            final_json = copy.deepcopy(resume_json)

            def apply_patch_to_section(entries: list) -> list:
                for entry in entries:
                    new_bullets = []
                    for bullet in entry.get("bullets", []):
                        # Try exact match first
                        if bullet in patch_map:
                            new_bullets.append(patch_map[bullet])
                        else:
                            # Try trimmed match as a fallback
                            trimmed = bullet.strip()
                            new_bullets.append(patch_map.get(trimmed, bullet))
                    entry["bullets"] = new_bullets
                return entries

            final_json["experience"] = apply_patch_to_section(final_json.get("experience", []))
            final_json["projects"] = apply_patch_to_section(final_json.get("projects", []))

            logger.info("Diff-patch applied successfully — resume integrity preserved")
            return final_json

        except Exception as e:
            logger.error(f"Bullet diff-patch error (attempt {attempt + 1}): {e}")
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                logger.warning("Returning original resume JSON as fallback")
                return resume_json

    return resume_json


OUTREACH_SYSTEM_PROMPT = """You are a world-class career coach and ghostwriter who crafts highly personalized, authentic outreach messages for job seekers.

You will receive:
- A candidate's resume text
- A job description
- A hiring manager's name and role

Your task is to generate outreach messages that feel genuine and human, not templated.
Reference specific details from the company, job, and candidate's background.

CRITICAL RULES:
- connection_note: MUST be under 200 characters. It is the LinkedIn connection request note. Be specific, reference the company or role. No emojis.
- linkedin_dm: 3-4 short paragraphs. Warm but professional. Reference 1 specific project from their resume that maps to this role.
- cold_email: Professional email. Include a subject line on the first line prefixed with "Subject: ". Then the body. 4-5 short paragraphs.
- NEVER use generic phrases like "I hope this message finds you well" or "I am writing to express my interest".
- Use the hiring manager's actual name and role. Address them directly.
- Return ONLY valid JSON. No markdown, no code blocks.

Return JSON in EXACTLY this format:
{
  "connection_note": "...",
  "linkedin_dm": "...",
  "cold_email": "Subject: [subject here]\\n\\n[email body here]"
}"""


async def generate_outreach_templates(
    resume_text: str,
    job_description: str,
    hm_name: str,
    hm_role: str,
    company: str,
    generate_linkedin: bool = True,
    generate_email: bool = True,
) -> dict:
    """
    Dynamically generate outreach templates based on available hiring manager data.

    Returns a dict with keys depending on what was requested:
      connection_note, linkedin_dm, cold_email
    """
    import json as _json

    fields_needed = []
    if generate_linkedin:
        fields_needed.extend(["connection_note", "linkedin_dm"])
    if generate_email:
        fields_needed.append("cold_email")

    if not fields_needed:
        return {}

    fields_schema = ", ".join(f'"{f}": "..."' for f in fields_needed)
    schema_note = f"Return ONLY these fields: {{{fields_schema}}}"

    client, model = _get_client(LLMMode.QUALITY, timeout=90.0)

    user_message = f"""Candidate Resume:
{resume_text[:2000]}

Job Description:
{job_description[:1500]}

Hiring Manager: {hm_name} ({hm_role}) at {company}

{schema_note}

Generate the outreach messages now:"""

    for attempt in range(2):
        try:
            logger.info(f"Generating outreach templates with {model} (attempt {attempt + 1})")
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": OUTREACH_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.7,
                max_tokens=1200,
                top_p=1,
            )
            result = response.choices[0].message.content.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            data = _json.loads(result.strip(), strict=False)
            logger.info(f"Outreach templates generated: {list(data.keys())}")
            return data

        except Exception as e:
            logger.error(f"Outreach LLM error (attempt {attempt + 1}): {e}")
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                logger.warning("Returning empty outreach templates as fallback")
                return {}

    return {}


_llm_cooldown_until = 0.0

async def extract_job_metadata(job_description: str) -> dict:
    """
    Extract skills and minimum years of experience from a raw job description using AI.
    Returns: {"skills": ["skill1", "skill2"], "min_yoe": 2}
    """
    import json
    import time
    global _key_cooldowns
    

    system_prompt = """You are an expert technical recruiter. Your task is to extract structured data from a raw job description.
Read the job description and extract two things:
1. "skills": A list of technical skills, tools, and languages mentioned (e.g., ["Python", "React", "AWS"]). If none are found, return an empty list.
2. "min_yoe": The absolute minimum years of experience required for this role as an integer. For example, if it says "3-5 years", return 3. If it says "5+ years", return 5. If it says "Entry level" or no explicit minimum years are mentioned, return 0.

Output EXACTLY and ONLY valid JSON matching this schema:
{"skills": ["skill1", "skill2"], "min_yoe": 2}
Do not include markdown formatting or backticks, just the raw JSON.
"""

    user_message = f"Job Description:\n{job_description[:6000]}\n\nReturn JSON now:"


    for attempt in range(5):  # Try up to 5 times to rotate through keys
        client, model = _get_client(LLMMode.FAST, timeout=30.0)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                max_tokens=200,
                extra_body={"reasoning_effort": "low"},
            )
            result = response.choices[0].message.content.strip()
            
            import re
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON braces found in LLM response: {repr(result)}")
            
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON decode error: {e}. Raw extracted: {repr(match.group())}")
            
            # Normalize skills to list of strings, min_yoe to int
            skills = data.get("skills", [])
            if not isinstance(skills, list):
                skills = []
            skills = [str(s) for s in skills]
            
            try:
                min_yoe = int(data.get("min_yoe", 0))
            except (ValueError, TypeError):
                min_yoe = 0
                
            return {
                "skills": skills,
                "min_yoe": min_yoe
            }
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Rate limit" in err_str:
                import re
                import time
                match = re.search(r"try again in ([\d\.]+)s", err_str)
                wait_sec = float(match.group(1)) if match else 15.0
                used_key = getattr(client, '_used_api_key', None)
                if used_key:
                    _key_cooldowns[used_key] = time.time() + wait_sec + 1.0
                logger.warning(f"LLM Rate limit hit. Circuit breaker active for {wait_sec + 2.0:.1f}s.")
                continue # Try the next key immediately
                
            logger.warning(f"Failed to extract job metadata (attempt {attempt + 1}): {e}")
            
    return {"skills": [], "min_yoe": 0}

