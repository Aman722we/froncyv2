# test_amazon_preview.py
import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from services.career_fetcher import fetch_amazon_jobs
from utils.messages import compute_manual_job_match

async def main():
    print("=" * 65)
    print(" 🚀 FETCHING REAL LIVE AMAZON JOBS (INDIA) FROM amazon.jobs")
    print("=" * 65)
    print("Connecting to https://www.amazon.jobs/en/search.json ...\n")

    normalized, raw, is_truncated = await fetch_amazon_jobs("software-development/IND")
    print(f"✅ Successfully fetched {len(normalized)} live jobs from Amazon!\n")

    # Sample profile (Fullstack developer like Anuj)
    sample_user = {
        "telegram_id": 999999999,
        "first_name": "Test Candidate",
        "role_pref": "fullstack",
        "skills": ["Python", "Java", "React", "AWS", "Docker", "SQL", "Distributed Systems"],
        "experience_level": "2",
        "batch_year": 2024
    }

    print("Showing the top 5 newest Amazon jobs and their live match scores:\n")

    for i, job in enumerate(normalized[:5], 1):
        match = compute_manual_job_match(sample_user, job)
        score = match["score"]
        role_pct = match["role_pct"]
        skill_pct = match["skill_pct"]

        score_emoji = "🟢" if score >= 60 else ("🟡" if score >= 40 else "🔴")

        print(f"[{i}] {job['title']}")
        print(f"    🏢 Company: Amazon (AWS)")
        print(f"    📍 Location: {job['location']}")
        print(f"    📅 Posted: {job['published_at'].strftime('%b %d, %Y') if job['published_at'] else 'Recent'}")
        print(f"    🔗 Job URL: {job['job_url']}")
        print(f"    🎯 Match for Fullstack: {score_emoji} {score}% (Role: {role_pct}%, Skills: {skill_pct}%)")
        if match["matched"]:
            print(f"    🛠️ Matched Skills: {', '.join(match['matched'][:5])}")
        print("-" * 65)

    print("\n💡 You can test any country or category by changing the board token, e.g.:")
    print("   - 'software-development/USA' (Amazon US)")
    print("   - 'data-science/IND' (Amazon India AI/ML/Data)")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
