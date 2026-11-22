# tests/test_faang_fetchers.py
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.career_fetcher import (
    _parse_amazon_token,
    _parse_apple_token,
    _parse_google_token,
    verify_board_token,
    fetch_amazon_jobs,
    fetch_apple_jobs,
    fetch_google_jobs,
    fetch_jobs_for_source,
)

async def test_tokens():
    print("Testing token parsers...")
    # Apple
    assert _parse_apple_token("india-INDC") == (None, "india-INDC")
    assert _parse_apple_token("IND") == (None, "india-INDC")
    assert _parse_apple_token("software/india-INDC") == ("software", "india-INDC")
    assert _parse_apple_token("software/IND") == ("software", "india-INDC")

    # Google
    assert _parse_google_token("India") == (None, "India")
    assert _parse_google_token("IND") == (None, "India")
    assert _parse_google_token("software/India") == ("software", "India")
    assert _parse_google_token("software/IND") == ("software", "India")

    print("✅ All token parsers passed!")

async def test_apple():
    print("\n[Testing APPLE Fetcher]...")
    valid = await verify_board_token("APPLE", "software/india-INDC")
    assert valid is True, "Apple verify_board_token failed!"
    print("✅ Apple verify_board_token passed!")

    normalized, raw, is_truncated = await fetch_apple_jobs("software/india-INDC")
    assert len(normalized) > 0, "No Apple jobs fetched!"
    assert len(raw) == len(normalized)
    
    sample = normalized[0]
    print(f"Sample Apple Job: {sample['title']} | ID: {sample['external_id']} | URL: {sample['job_url']}")
    assert sample["source_provider"] == "APPLE"
    assert sample["external_id"]
    assert sample["title"]
    assert sample["job_url"].startswith("https://jobs.apple.com")
    print(f"✅ Fetched {len(normalized)} Apple jobs successfully!")

async def test_google():
    print("\n[Testing GOOGLE Fetcher]...")
    valid = await verify_board_token("GOOGLE", "software/India")
    assert valid is True, "Google verify_board_token failed!"
    print("✅ Google verify_board_token passed!")

    normalized, raw, is_truncated = await fetch_google_jobs("software/India")
    assert len(normalized) > 0, "No Google jobs fetched!"
    
    sample = normalized[0]
    print(f"Sample Google Job: {sample['title']} | ID: {sample['external_id']} | URL: {sample['job_url']}")
    assert sample["source_provider"] == "GOOGLE"
    assert sample["external_id"]
    assert sample["title"]
    assert sample["job_url"].startswith("https://careers.google.com")
    print(f"✅ Fetched {len(normalized)} Google jobs successfully!")

async def test_dispatcher():
    print("\n[Testing Dispatcher for APPLE & GOOGLE]...")
    apple_source = {"provider": "APPLE", "board_token": "software/india-INDC"}
    norm_a, _, _ = await fetch_jobs_for_source(apple_source)
    assert len(norm_a) > 0
    assert norm_a[0]["source_provider"] == "APPLE"

    google_source = {"provider": "GOOGLE", "board_token": "software/India"}
    norm_g, _, _ = await fetch_jobs_for_source(google_source)
    assert len(norm_g) > 0
    assert norm_g[0]["source_provider"] == "GOOGLE"
    print("✅ Dispatcher verified for both APPLE and GOOGLE!")

async def main():
    print("=" * 55)
    print(" FAANG CRAWLER TEST SUITE (AMAZON, APPLE, GOOGLE)")
    print("=" * 55)
    await test_tokens()
    await test_apple()
    await test_google()
    await test_dispatcher()
    print("\n" + "=" * 55)
    print(" 🚀 ALL FAANG TESTS PASSED!")
    print("=" * 55)

if __name__ == "__main__":
    asyncio.run(main())
