# test_persona_4_qa.py
import asyncio
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from utils.constants import (
    STREAM_TAXONOMY,
    compile_token_pattern,
    resolve_user_stream,
    classify_job_streams,
    compute_role_alignment,
    ROLE_KEYWORDS
)
from utils.messages import compute_manual_job_match

def run_local_unit_tests():
    print("==================================================")
    print(" SUITE 1: UNIT & NEGATIVE KEYWORD TESTS")
    print("==================================================")

    # 1. Punctuation and Boundary checks
    assert compile_token_pattern("rag").search("storage") is None
    assert compile_token_pattern("rag").search("leverage") is None
    assert compile_token_pattern("ios").search("bios") is None
    assert compile_token_pattern("rust").search("trust") is None
    assert compile_token_pattern("server").search("serverless") is None
    assert compile_token_pattern("ci/cd").search("ci/cd pipeline") is not None
    assert compile_token_pattern("ai/ml").search("ai/ml engineer") is not None
    assert compile_token_pattern("c++").search("c++ developer") is not None
    assert compile_token_pattern(".net").search(".net core") is not None
    assert compile_token_pattern("node.js").search("node.js backend") is not None
    print("✅ All boundary & punctuation lookarounds passed!")

    # 2. Sam07 vs Jobgether ETL Data Engineer
    sam_user = {
        "telegram_id": 8337089549,
        "role_pref": "data",
        "skills": ["GitHub", "LangGraph", "RAG", "Machine Learning", "REST APIs", "TensorFlow", "SQL", "Python", "Pandas", "NumPy", "LangChain", "LLMs", "Scikit-Learn", "Node.js", "NLP"],
        "experience_level": "0",
        "batch_year": None
    }
    jobgether_etl_job = {
        "id": 7230,
        "title": "Data Engineer",
        "role_category": "Data Engineering",
        "skills": ["Python", "SQL", "REST APIs", "Data Pipelines", "CRM Integration"],
        "min_yoe": 1,
        "salary": "Not disclosed",
        "posted_at": datetime.now(timezone.utc)
    }
    match_etl = compute_manual_job_match(sam_user, jobgether_etl_job)
    print(f"\n[Test Sam07 vs ETL Job #7230]")
    print(f"Role %: {match_etl['role_pct']}%, Final Score: {match_etl['score']}%")
    assert match_etl["role_pct"] == 0, f"Expected role_pct=0, got {match_etl['role_pct']}"
    assert match_etl["score"] <= 25, f"Expected final score <= 25, got {match_etl['score']}"
    print("✅ Gate 1 fired: Sam07 blocked from ETL Data Engineer (Score <= 25%, Alert Suppressed)!")

    # 3. Sam07 vs Genuine AI/ML Engineer Job
    aiml_job = {
        "id": 9991,
        "title": "Generative AI / ML Engineer",
        "role_category": "AI / Machine Learning",
        "skills": ["Python", "PyTorch", "LangGraph", "RAG", "LLMs", "Scikit-Learn"],
        "min_yoe": 0,
        "salary": "$120,000",
        "posted_at": datetime.now(timezone.utc)
    }
    match_aiml = compute_manual_job_match(sam_user, aiml_job)
    print(f"\n[Test Sam07 vs Genuine AI/ML Job]")
    print(f"Role %: {match_aiml['role_pct']}%, Skill %: {match_aiml['skill_pct']}%, Final Score: {match_aiml['score']}%")
    assert match_aiml["role_pct"] == 100, f"Expected role_pct=100, got {match_aiml['role_pct']}"
    assert match_aiml["score"] >= 80, f"Expected final score >= 80, got {match_aiml['score']}"
    print("✅ Sam07 matches AI/ML Engineer with top score (Alert Dispatched)!")

    # 4. Frontend User vs Senior Java Backend Developer
    fe_user = {
        "telegram_id": 11111,
        "role_pref": "frontend",
        "skills": ["React", "TypeScript", "Next.js", "Tailwind CSS"],
        "experience_level": "2",
        "batch_year": 2024
    }
    java_backend_job = {
        "id": 9992,
        "title": "Senior Java Backend Developer",
        "role_category": "Backend Engineering",
        "skills": ["Java", "Spring Boot", "Microservices", "PostgreSQL", "Docker"],
        "min_yoe": 2,
        "salary": "25 LPA",
        "posted_at": datetime.now(timezone.utc)
    }
    match_fe_be = compute_manual_job_match(fe_user, java_backend_job)
    print(f"\n[Test Frontend vs Java Backend Job]")
    print(f"Role %: {match_fe_be['role_pct']}%, Final Score: {match_fe_be['score']}%")
    assert match_fe_be["role_pct"] == 0, f"Expected role_pct=0, got {match_fe_be['role_pct']}"
    assert match_fe_be["score"] <= 25, f"Expected score <= 25, got {match_fe_be['score']}"
    print("✅ Gate 1 fired: Frontend user strictly blocked from Backend (Score <= 25%)!")

    # 5. Frontend User vs Full Stack Engineer (React / Node)
    fullstack_job = {
        "id": 9993,
        "title": "Full Stack Engineer (React/Node)",
        "role_category": "Software Engineering",
        "skills": ["React", "Node.js", "PostgreSQL"],
        "min_yoe": 2,
        "salary": "20 LPA",
        "posted_at": datetime.now(timezone.utc)
    }
    match_fe_fs = compute_manual_job_match(fe_user, fullstack_job)
    print(f"\n[Test Frontend vs Fullstack Job]")
    print(f"Role %: {match_fe_fs['role_pct']}%, Final Score: {match_fe_fs['score']}%")
    assert match_fe_fs["role_pct"] == 95, f"Expected role_pct=95, got {match_fe_fs['role_pct']}"
    assert match_fe_fs["score"] >= 65, f"Expected score >= 65, got {match_fe_fs['score']}"
    print("✅ Overlap wins: Frontend user allowed for Fullstack React/Node job!")

    # 6. Custom Role "Java Developer" with Zero Java Skills vs With Java Skills
    java_no_skill_user = {
        "telegram_id": 22222,
        "role_pref": "Java Developer",
        "skills": ["Photoshop", "Excel", "Marketing"],
        "experience_level": "1"
    }
    java_job = {
        "id": 9994,
        "title": "Java Developer",
        "role_category": "Software Development",
        "skills": ["Java", "Spring Boot", "SQL"],
        "min_yoe": 1,
        "posted_at": datetime.now(timezone.utc)
    }
    match_java_noskill = compute_manual_job_match(java_no_skill_user, java_job)
    print(f"\n[Test Custom 'Java Developer' with 0 Java skills]")
    print(f"Role %: {match_java_noskill['role_pct']}%, Skill %: {match_java_noskill['skill_pct']}%, Final Score: {match_java_noskill['score']}%")
    assert match_java_noskill["role_pct"] == 100
    assert match_java_noskill["score"] <= 30, f"Expected score <= 30, got {match_java_noskill['score']}"
    print("✅ Gate 2 fired: Zero skills prevents alert even with title hit (Score <= 30%)!")

    java_skilled_user = {
        "telegram_id": 33333,
        "role_pref": "Java Developer",
        "skills": ["Java", "Spring Boot", "SQL", "Git"],
        "experience_level": "1"
    }
    match_java_skilled = compute_manual_job_match(java_skilled_user, java_job)
    print(f"\n[Test Custom 'Java Developer' WITH Java skills]")
    print(f"Role %: {match_java_skilled['role_pct']}%, Skill %: {match_java_skilled['skill_pct']}%, Final Score: {match_java_skilled['score']}%")
    assert match_java_skilled["score"] >= 80, f"Expected score >= 80, got {match_java_skilled['score']}"
    print("✅ Custom role with matching skills scores >= 80% (Alert Dispatched)!")

async def run_db_dry_run():
    print("\n==================================================")
    print(" SUITE 2: REAL DATABASE USER DRY RUN")
    print("==================================================")
    import asyncpg
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not found, skipping DB dry run.")
        return

    conn = await asyncpg.connect(db_url, statement_cache_size=0)
    try:
        users = await conn.fetch("""
            SELECT telegram_id, first_name, username, role_pref, skills, experience_level, plan
            FROM users
            WHERE is_onboarded = TRUE AND (is_deleted IS NULL OR is_deleted = FALSE)
            ORDER BY telegram_id ASC
        """)
        print(f"Found {len(users)} onboarded active users in database.")
        
        migrated_counts = {}
        for u in users:
            raw_role = u["role_pref"] or "fullstack"
            skills = u["skills"] or []
            resolved = resolve_user_stream(raw_role, skills)
            stream = resolved["stream"]
            migrated_counts[stream] = migrated_counts.get(stream, 0) + 1
            if stream in ("data_ml", "data_eng"):
                print(f"  User @{u['username'] or u['first_name']} (ID {u['telegram_id']}) -> raw: '{raw_role}' => resolved: '{stream}' (custom={resolved['is_custom']})")

        print("\nStream distribution across all active users:")
        for s, count in sorted(migrated_counts.items(), key=lambda x: -x[1]):
            print(f"  - {s}: {count} users")

        print("\n✅ Zero crashes across all live database user profiles!")

    finally:
        await conn.close()

if __name__ == "__main__":
    run_local_unit_tests()
    asyncio.run(run_db_dry_run())
