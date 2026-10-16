"""
LinkedIn Viral Post Generator for Froncy V2.

Generates high-converting LinkedIn job posts following the proven 55k+ impression viral structure.
Emphasizes Froncy V2's direct career-page intelligence (525+ company career pages), solves
the conversion rate drop-off by eliminating friction (pinned first comment + clear trust signals),
and delivers copy-paste-ready posts twice daily (8:00 AM IST & 5:00 PM IST) to the Admin on Telegram.
"""
import html
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from loguru import logger
from db.connection import get_pool
from config import settings


VIRAL_HOOKS = [
    # Hook 1: Framework Trap / Impostor Syndrome
    {
        "id": "framework_trap",
        "intro": (
            "Most frontend and junior developers think they need to learn one more framework before applying.\n"
            "The truth?\n\n"
            "Many companies are hiring developers who already have the skills they need.\n"
            "While you're waiting to feel \"100% ready,\" someone with a simpler portfolio has already submitted their application and is scheduling interviews.\n\n"
            "If you know JavaScript, React, Python, or core web development, these 5 opportunities are worth checking out today. 👇"
        ),
        "hashtags": "#FrontendDeveloper #ReactJS #JavaScript #TypeScript #NextJS #WebDevelopment #FrontendJobs #SoftwareEngineer #TechJobs #Hiring #FreshersJobs #CareerGrowth"
    },
    # Hook 2: Speed / Being Too Late (Ghosting)
    {
        "id": "speed_advantage",
        "intro": (
            "Most developers think they're getting ghosted because of competition.\n"
            "In reality? They're getting ghosted because they're applying too late.\n\n"
            "By the time a tech opening gets reposted across public job boards, 300+ people have already applied and HR has stopped opening new resumes.\n"
            "Companies don't always hire the \"best\" candidate. They hire the qualified candidate who applied first.\n\n"
            "Here are 5 brand new openings detected directly from company career pages today. 👇"
        ),
        "hashtags": "#TechJobs #FrontendDeveloper #SoftwareEngineer #WebDevelopment #ReactJS #FullStack #Python #Coding #Hiring #JobSearch #FreshersJobs #CareerGrowth"
    },
    # Hook 3: The Hidden Career Page Secret
    {
        "id": "career_page_secret",
        "intro": (
            "90% of job seekers only check LinkedIn and Naukri.\n"
            "That is exactly where 90% of the competition is fighting for the same 10 roles.\n\n"
            "What top candidates do differently:\n"
            "They apply directly on company career pages (Greenhouse, Lever, Ashby) days before the opening is ever posted on job boards.\n\n"
            "We tracked today's top direct career-page drops. Here are 5 junior & fresher opportunities you should check out right now. 👇"
        ),
        "hashtags": "#TechJobs #SoftwareEngineer #FrontendDeveloper #WebDevelopment #ReactJS #JavaScript #RemoteJobs #Hiring #FreshersJobs #CareerAdvice #DeveloperJobs"
    },
    # Hook 4: 100 Random Applications vs 10 Targeted Matches
    {
        "id": "targeted_applications",
        "intro": (
            "The biggest mistake job seekers make is sending 100 identical applications.\n"
            "A developer with a well-targeted resume gets more interviews from 10 applications than someone spamming \"Easy Apply\" 100 times.\n\n"
            "If your skills match at least 70% of a job description, you should apply.\n"
            "Here are 5 handpicked junior developer opportunities hiring today. 👇"
        ),
        "hashtags": "#JobSearch #TechJobs #SoftwareEngineer #FrontendDeveloper #ReactJS #FullStack #WebDevelopment #Hiring #FreshersJobs #ResumeTips #CareerGrowth"
    },
    # Hook 5: Waiting for the Perfect Time
    {
        "id": "perfect_time_myth",
        "intro": (
            "The biggest mistake junior developers make isn't having the wrong skills.\n"
            "It's waiting for the \"perfect time\" to start applying.\n\n"
            "Meanwhile, candidates with the exact same skills are already interviewing because they didn't wait.\n"
            "If you know core programming, web basics, and Git, companies are looking for you right now.\n\n"
            "Here are 5 verified junior opportunities to apply for today. 👇"
        ),
        "hashtags": "#FrontendDeveloper #SoftwareEngineer #ReactJS #JavaScript #TypeScript #WebDevelopment #FreshersJobs #TechJobs #Hiring #CareerGrowth #DeveloperJobs"
    },
    # Hook 6: The ATS Keyword Filter Trap
    {
        "id": "ats_keyword_trap",
        "intro": (
            "Most developers think their resume gets rejected by human recruiters.\n"
            "In reality, over 70% of resumes are filtered out by ATS parsers before an engineer ever reads them.\n\n"
            "The reason? Simple missing keywords and poor skill alignment with the JD.\n"
            "Before you send another application, check out these 5 fresh roles hiring juniors today. 👇"
        ),
        "hashtags": "#ResumeTips #ATSResume #FrontendDeveloper #SoftwareEngineer #TechJobs #Hiring #FreshersJobs #ReactJS #WebDevelopment #CareerAdvice #Developer"
    },
    # Hook 7: The First 25 Applicants Rule
    {
        "id": "first_25_rule",
        "intro": (
            "Want to know the single highest-ROI hack in tech hiring?\n"
            "Be in the first 25 applicants on the company's official career portal.\n\n"
            "Recruiters review the earliest qualified submissions first. If they find 5 solid candidates in the first 30 applications, they pause the pipeline.\n"
            "Here are 5 fresh junior roles dropped on direct career boards today. 👇"
        ),
        "hashtags": "#JobSearch #TechJobs #Hiring #SoftwareEngineer #FrontendDeveloper #ReactJS #WebDevelopment #FreshersJobs #CareerTips #DeveloperJobs"
    },
    # Hook 8: Not Enough React Myth
    {
        "id": "not_enough_react",
        "intro": (
            "Most developers think they're getting rejected because they don't know enough advanced frameworks.\n"
            "That's usually not the problem.\n\n"
            "The real problem? They're applying to jobs that don't match their current skills, days after the listing went viral.\n"
            "A developer applying early to matching roles will consistently beat someone mass-applying late.\n\n"
            "Here are 5 fresh junior opportunities hiring right now. 👇"
        ),
        "hashtags": "#FrontendDeveloper #ReactJS #NextJS #TypeScript #JavaScript #FrontendJobs #WebDevelopment #SoftwareEngineer #TechJobs #Hiring #CareerGrowth"
    }
]


async def fetch_curated_fresher_jobs(limit: int = 5) -> list[dict]:
    """
    Fetch 5 high-quality, junior/fresher jobs from manual_jobs table.
    Prioritizes jobs with disclosed salary, fresher-friendly tags, and unique companies.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Step 1: Look for fresher friendly jobs (min_yoe <= 1 or is_fresher_friendly)
        rows = await conn.fetch(
            """
            SELECT id, title, company, location, salary, skills, min_yoe, max_yoe,
                   workplace_type, source_provider, source_type, posted_at, url, role_category
            FROM manual_jobs
            WHERE is_active = TRUE
              AND (min_yoe <= 1 OR is_fresher_friendly = TRUE)
              AND (
                  location ILIKE '%india%' OR location ILIKE '%bangalore%' OR location ILIKE '%bengaluru%' OR 
                  location ILIKE '%remote%' OR location ILIKE '%hyderabad%' OR location ILIKE '%pune%' OR 
                  location ILIKE '%mumbai%' OR location ILIKE '%delhi%' OR location ILIKE '%gurgaon%' OR 
                  location ILIKE '%noida%' OR location ILIKE '%chennai%' OR location IS NULL OR location = ''
              )
            ORDER BY 
              CASE WHEN salary IS NOT NULL AND salary != 'Not disclosed' AND salary != '' THEN 0 ELSE 1 END,
              posted_at DESC
            LIMIT 40;
            """
        )

        # Step 2: Fallback to min_yoe <= 2 if we don't have enough rows
        if len(rows) < limit:
            fallback_rows = await conn.fetch(
                """
                SELECT id, title, company, location, salary, skills, min_yoe, max_yoe,
                       workplace_type, source_provider, source_type, posted_at, url, role_category
                FROM manual_jobs
                WHERE is_active = TRUE
                  AND min_yoe <= 2
                ORDER BY 
                  CASE WHEN salary IS NOT NULL AND salary != 'Not disclosed' AND salary != '' THEN 0 ELSE 1 END,
                  posted_at DESC
                LIMIT 40;
                """
            )
            rows = fallback_rows

    # Deduplicate by company so we don't feature multiple jobs from the same company
    seen_companies = set()
    selected = []
    for r in rows:
        comp = (r["company"] or "").strip().lower()
        if comp and comp not in seen_companies:
            seen_companies.add(comp)
            selected.append(dict(r))
        if len(selected) >= limit:
            break

    # If still fewer than limit, just take top available
    if len(selected) < limit and rows:
        for r in rows:
            if dict(r) not in selected:
                selected.append(dict(r))
            if len(selected) >= limit:
                break

    return selected[:limit]


def _format_job_card(job: dict) -> str:
    """Format a single job into the viral micro-card structure."""
    title = (job.get("title") or "Software Engineer").strip()
    company = (job.get("company") or "Tech Company").strip()
    
    # Location & Workplace Type
    raw_loc = (job.get("location") or "Remote / India").strip()
    workplace = (job.get("workplace_type") or "").strip()
    if workplace and workplace.lower() not in raw_loc.lower():
        loc_display = f"{raw_loc} ({workplace})"
    else:
        loc_display = raw_loc

    # Salary
    raw_salary = (job.get("salary") or "").strip()
    if not raw_salary or raw_salary.lower() in ("null", "none", "not disclosed", "n/a"):
        salary_display = "Salary Not Disclosed"
    else:
        salary_display = raw_salary

    # Experience Display
    min_yoe = job.get("min_yoe", 0) or 0
    max_yoe = job.get("max_yoe")
    is_fresher = job.get("is_fresher_friendly", False)

    if min_yoe == 0 or is_fresher:
        if max_yoe and max_yoe > 0:
            exp_display = f"Freshers Welcome (0–{max_yoe} YOE)"
        else:
            exp_display = "Freshers Welcome (0 YOE)"
    elif min_yoe == 1:
        exp_display = "1 YOE (Freshers with internships welcome)"
    else:
        exp_display = f"{min_yoe} YOE"

    # Skills formatting
    skills = job.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    clean_skills = [str(s).strip() for s in skills if str(s).strip()][:7]
    if not clean_skills:
        clean_skills = ["React", "JavaScript", "HTML", "CSS", "Git", "APIs"]
    skills_display = ", ".join(clean_skills)

    card = (
        f"🚀 {title} — {company}\n"
        f"📍 {loc_display}\n"
        f"💰 {salary_display}\n"
        f"🎯 {exp_display}\n"
        f"⚡ {skills_display}"
    )
    return card


async def generate_linkedin_post(slot: str = "morning") -> dict:
    """
    Generate a complete, copy-paste-ready LinkedIn post + companion First Comment.
    `slot`: 'morning' (for 9:00 AM post) or 'evening' (for 6:00 PM post).
    """
    jobs = await fetch_curated_fresher_jobs(limit=5)
    if not jobs:
        return {
            "error": "No active jobs found in database to generate post.",
            "post_text": "",
            "first_comment": ""
        }

    # Rotate hooks based on day of year + slot
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    day_of_year = now_ist.timetuple().tm_yday
    slot_offset = 0 if slot == "morning" else 4
    hook_index = (day_of_year * 2 + slot_offset) % len(VIRAL_HOOKS)
    hook = VIRAL_HOOKS[hook_index]

    # Format the 5 job cards
    cards = [_format_job_card(j) for j in jobs]
    cards_section = "\n━━━━━━━━━━━━━━━\n".join(cards)

    # Slot greeting / context note
    evening_tease = ""
    if slot == "morning":
        evening_tease = "In the evening I'll drop 5 more verified career-page openings."

    # Build the full post body
    post_text = f"""{hook['intro']}

━━━━━━━━━━━━━━━
{cards_section}
━━━━━━━━━━━━━━━

One pattern we've noticed after tracking thousands of career-page applications:
A lot of candidates spend months improving their skills...
Very few spend the same energy ensuring their resume actually matches the JD before hitting apply.

Before submitting your application, ask yourself:
✅ Does my resume contain the exact keywords mentioned in the JD?
✅ Am I applying to roles that match at least 70–80% of my stack?
✅ Is my resume ATS-friendly and easy for recruiters to scan?
✅ Am I applying early—before 200 other people crowd the portal?

That's exactly why we built FroncyBot.
These 5 jobs are just a tiny preview of today's openings.
Froncy monitors 525+ direct company career pages (Greenhouse, Lever, Ashby) with continuous hourly sweeps.
When a company quietly publishes a fresh opening on their internal careers board, you catch it in the very first wave—so you can apply within the first hour, long before the role gets reposted and flooded on LinkedIn.

🛡️ Why Telegram?
Direct, first-wave alerts right where you chat—zero email clutter, no clunky apps to download, and 100% verified direct ATS links (no third-party middlemen).

⚡ What you get in seconds:
1️⃣ Upload your resume
2️⃣ Live ATS match score & keyword breakdown for your stack
3️⃣ Direct official application links before the crowd arrives

🔗 Direct 1-tap FroncyBot access link is pinned in the FIRST COMMENT below 👇
(Or check the link at the top of my profile featured section)

💬 Or simply comment "BOT" or "LINK" and we'll send you the direct access link.

No endless searching.
No mass applying.
No guessing if you're qualified.
Just smarter applications.

📌 Save this post before you apply.
📌 Repost this to help a fellow developer land an interview.
📌 Follow for daily direct career-page tech jobs & fresher openings.

{evening_tease}

{hook['hashtags']}"""

    # Companion First Comment (Guarantees zero-penalty, 1-click conversion)
    first_comment = (
        "🚀 Here is the direct 1-tap link to launch FroncyBot on Telegram:\n"
        "👉 https://t.me/FroncyJobsBot\n\n"
        "⚡ First-wave direct alerts for fresh junior/entry-level tech jobs from 525+ company career pages (Greenhouse, Lever, Ashby) hours before they hit LinkedIn.\n"
        "🎯 Upload your resume to see your live ATS match score in 10 seconds!"
    )

    return {
        "slot": slot,
        "hook_id": hook["id"],
        "post_text": post_text.strip(),
        "first_comment": first_comment.strip(),
        "job_count": len(jobs),
        "companies": [j.get("company") for j in jobs]
    }


async def send_scheduled_linkedin_post(bot, slot: str = "morning") -> bool:
    """
    Called by APScheduler at 8:00 AM IST and 5:00 PM IST.
    Generates the LinkedIn post and sends it directly to the Admin on Telegram.
    """
    admin_id = settings.ADMIN_TELEGRAM_ID
    if not admin_id:
        logger.warning("Cannot send LinkedIn post: settings.ADMIN_TELEGRAM_ID is not configured.")
        return False

    try:
        post_data = await generate_linkedin_post(slot=slot)
        if "error" in post_data:
            await bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ <b>LinkedIn Post Generator Error:</b> {post_data['error']}",
                parse_mode="HTML"
            )
            return False

        slot_title = "Morning Post (for 9:00 AM)" if slot == "morning" else "Evening Post (for 6:00 PM)"
        companies_str = ", ".join(filter(None, post_data.get("companies", [])))

        # Header intro message
        header_text = (
            f"📢 <b>LinkedIn Viral Post Ready! ({slot_title})</b>\n\n"
            f"🏢 <b>Featured Companies:</b> {html.escape(companies_str)}\n"
            f"🎯 <b>Hook Style:</b> <code>{post_data['hook_id']}</code>\n\n"
            f"👇 <b>1. Copy and paste the post text below on LinkedIn:</b>"
        )
        await bot.send_message(
            chat_id=admin_id,
            text=header_text,
            parse_mode="HTML"
        )

        # Post body message
        # Send as clean plain text so admin can copy the entire message easily on mobile
        await bot.send_message(
            chat_id=admin_id,
            text=post_data["post_text"],
            disable_web_page_preview=True
        )

        # First comment message
        comment_header = (
            "💬 <b>2. Copy and paste this as the FIRST COMMENT on your post:</b>\n"
            "<i>(This bypasses LinkedIn's link penalty and gives readers a direct 1-tap link!)</i>"
        )
        await bot.send_message(
            chat_id=admin_id,
            text=comment_header,
            parse_mode="HTML"
        )

        await bot.send_message(
            chat_id=admin_id,
            text=post_data["first_comment"],
            disable_web_page_preview=True
        )

        logger.info(f"✅ Successfully sent scheduled LinkedIn {slot} post to admin {admin_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to generate or send LinkedIn post to admin: {e}")
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"❌ <b>Failed to generate scheduled LinkedIn post:</b> {html.escape(str(e))}",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return False
