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
        
        score = data.get("score", 0)
        matching = data.get("matching_keywords", [])
        missing = data.get("missing_keywords", [])
        tech_found = data.get("tech_found", [])
        tech_missing = data.get("tech_missing", [])
        suggestions = data.get("suggestions", [])

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
