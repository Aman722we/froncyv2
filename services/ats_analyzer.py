"""
ATS Resume Keyword Analyzer (Pro+ feature).
Compares resume text against a job description using NVIDIA NIM LLM.
"""
import json
from loguru import logger
from services.llm_service import generate_ats_analysis, LLMMode


async def analyze_resume_match(resume_text: str, job_description: str, mode=None) -> dict:
    """
    Compare resume against a job description using an LLM.

    Returns:
        {
            "score": 0-100 (match percentage),
            "matching_keywords": [...],
            "missing_keywords": [...],
            "suggestions": [...],
            "tech_match": {"found": [...], "missing": [...]},
        }
    """
    if not resume_text or not job_description:
        return {
            "score": 0,
            "matching_keywords": [],
            "missing_keywords": [],
            "suggestions": ["Upload your resume and provide a job description to analyze."],
            "tech_match": {"found": [], "missing": []},
        }

    from services.llm_service import LLMMode as _LLMMode
    if mode is None:
        mode = _LLMMode.QUALITY

    try:
        # Call LLM logic
        json_output = await generate_ats_analysis(resume_text, job_description, mode=mode)
        data = json.loads(json_output)
        
        def _sanitize(val):
            return str(val).replace("~", "").replace("`", "")

        matching = [_sanitize(k) for k in data.get("matching_keywords", [])]
        missing = [_sanitize(k) for k in data.get("missing_keywords", [])]
        tech_found = [_sanitize(k) for k in data.get("tech_found", [])]
        tech_missing = [_sanitize(k) for k in data.get("tech_missing", [])]
        suggestions = [_sanitize(s) for s in data.get("suggestions", [])]

        total_tech = len(tech_found) + len(tech_missing)
        if total_tech > 0:
            score = int((len(tech_found) / total_tech) * 100)
        else:
            score = 0

        result = {
            "score": score,
            "matching_keywords": matching,
            "missing_keywords": missing,
            "suggestions": suggestions,
            "tech_match": {"found": tech_found, "missing": tech_missing},
        }
        
        logger.info(f"LLM ATS Analysis: score={score}%, {len(matching)} matches, {len(missing)} gaps")
        return result

    except Exception as e:
        logger.error(f"Failed to parse LLM ATS analysis: {e}")
        return {
            "score": 0,
            "matching_keywords": [],
            "missing_keywords": [],
            "suggestions": ["⚠️ Error analyzing resume. Please parse your resume again."],
            "tech_match": {"found": [], "missing": []},
        }
