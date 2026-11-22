import asyncio
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from services.career_fetcher import (
    _parse_amazon_token,
    fetch_amazon_jobs,
    fetch_jobs_for_source,
    verify_board_token,
)

async def run_tests():
    print("==================================================")
    print(" TEST SUITE: AMAZON CRAWLER SPECIFICATION")
    print("==================================================")

    # 1. Token parser tests
    assert _parse_amazon_token("software-development/IND") == ("software-development", "IND")
    assert _parse_amazon_token("IND") == ("software-development", "IND")
    assert _parse_amazon_token("data-science/IND") == ("data-science", "IND")
    assert _parse_amazon_token("all/IND") == (None, "IND")
    assert _parse_amazon_token("category=software-development&country=IND") == ("software-development", "IND")
    print("✅ Token parser tests passed!")

    # 2. Token verification tests
    print("\n[Testing verify_board_token for AMAZON]...")
    is_valid = await verify_board_token("AMAZON", "software-development/IND")
    print(f"verify_board_token('AMAZON', 'software-development/IND') = {is_valid}")
    assert is_valid is True, "Token verification failed for software-development/IND"
    print("✅ Token verification passed!")

    # 3. Live Amazon jobs fetch test
    print("\n[Testing fetch_amazon_jobs for India]...")
    normalized, raw, is_truncated = await fetch_amazon_jobs("software-development/IND")
    print(f"Fetched {len(normalized)} normalized jobs (raw count: {len(raw)}, is_truncated: {is_truncated})")
    assert len(normalized) > 0, "No jobs returned from Amazon fetcher!"

    first_job = normalized[0]
    print("\nSample normalized Amazon job:")
    print(f" - ID: {first_job['external_id']}")
    print(f" - Title: {first_job['title']}")
    print(f" - Location: {first_job['location']}")
    print(f" - Published At: {first_job['published_at']}")
    print(f" - Job URL: {first_job['job_url']}")
    print(f" - Description length: {len(first_job['description'])} chars")
    print(f" - Provider: {first_job['source_provider']}")

    assert first_job["external_id"], "Missing external_id"
    assert first_job["title"], "Missing title"
    assert first_job["job_url"].startswith("https://www.amazon.jobs"), f"Invalid job_url: {first_job['job_url']}"
    assert first_job["published_at"] is not None, "Missing published_at"
    assert first_job["published_at"].tzinfo is not None, "published_at is not timezone-aware"
    assert first_job["source_provider"] == "AMAZON"
    assert len(first_job["description"]) > 50, "Description too short"
    print("✅ All normalized job schema assertions passed!")

    # 4. Dispatcher test
    print("\n[Testing fetch_jobs_for_source dispatcher]...")
    norm_disp, raw_disp, trunc_disp = await fetch_jobs_for_source({
        "provider": "AMAZON",
        "board_token": "software-development/IND"
    })
    assert len(norm_disp) == len(normalized)
    print("✅ Dispatcher passed successfully!")

    print("\n==================================================")
    print(" 🚀 ALL AMAZON CRAWLER TESTS PASSED!")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
