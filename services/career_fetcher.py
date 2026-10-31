"""
Career Page Fetchers for Froncy V2.
Supports: Greenhouse (Phase 1).
Future: Lever, Ashby.

All fetchers are pure HTTP — no browser automation, no authentication.
All public endpoints only.
"""
import html
import re
import httpx
from datetime import datetime, timezone
from loguru import logger


def _strip_html(raw_html: str) -> str:
    """
    Strip HTML tags, inline styles, and decode all HTML entities (&quot;, &amp;, &lt;, etc.).
    Preserves natural line breaks for lists and paragraphs.
    Outputs clean, human-readable plain text that saves ~40% LLM prompt tokens.
    """
    if not raw_html:
        return ""
    # 1. Unescape HTML entities first (turns &lt;div&gt; into <div>, &quot; into ", etc.)
    text = html.unescape(raw_html)
    text = html.unescape(text)  # Run twice for double-encoded entities

    # 2. Strip <script> and <style> tags and their inner content
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.DOTALL | re.IGNORECASE)

    # 3. Replace block/break elements with newlines so paragraphs and bullet points don't merge
    text = re.sub(r'<(p|div|br|li|h[1-6]|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(p|div|li|h[1-6]|tr)>', '\n', text, flags=re.IGNORECASE)

    # 4. Remove all remaining HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)

    # 5. Final entity unescape pass for any newly uncovered entities
    text = html.unescape(text)

    # 6. Normalize whitespace: trim lines, collapse multiple spaces, prevent excessive blank lines
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
    clean_lines = []
    prev_empty = False
    for line in lines:
        if line:
            clean_lines.append(line)
            prev_empty = False
        elif not prev_empty:
            clean_lines.append("")
            prev_empty = True

    return '\n'.join(clean_lines).strip()


async def fetch_greenhouse_jobs(board_token: str) -> tuple[list[dict], list[dict], bool]:
    """
    Fetch all published jobs from a Greenhouse board.
    Uses the public Job Board API — no auth required.
    Returns (normalized_jobs, raw_jobs, is_truncated).
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "FroncyBot/2.0 (job-aggregator)"})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning(f"Greenhouse HTTP error for {board_token}: {e.response.status_code}")
        raise
    except Exception as e:
        logger.warning(f"Greenhouse fetch failed for {board_token}: {e}")
        raise

    jobs = data.get("jobs", [])
    total_meta = data.get("meta", {}).get("total")
    is_truncated = False
    if total_meta is not None and len(jobs) < total_meta:
        is_truncated = True
        logger.warning(f"Greenhouse [{board_token}]: payload truncated ({len(jobs)} < {total_meta})")

    normalized = []

    for job in jobs:
        try:
            # Extract location
            location = None
            loc = job.get("location", {})
            if isinstance(loc, dict):
                location = loc.get("name")
            
            # Extract department
            dept = ""
            departments = job.get("departments", [])
            if departments and isinstance(departments, list):
                dept = departments[0].get("name", "") if departments else ""

            # Parse published_at from updated_at (best Greenhouse has)
            published_at = None
            updated_at_str = job.get("updated_at")
            if updated_at_str:
                try:
                    published_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            # Full description text (stripped of HTML)
            raw_content = job.get("content") or ""
            description = _strip_html(raw_content)

            normalized.append({
                "external_id": str(job["id"]),
                "title": job.get("title", "Untitled"),
                "location": location,
                "department": dept,
                "description": description,
                "published_at": published_at,
                "job_url": job.get("absolute_url"),
                "apply_url": job.get("absolute_url"),
                "source_provider": "GREENHOUSE",
            })
        except Exception as e:
            logger.warning(f"Error normalizing Greenhouse job {job.get('id')}: {e}")
            continue

    logger.info(f"Greenhouse [{board_token}]: fetched {len(normalized)} jobs (raw={len(jobs)}, truncated={is_truncated})")
    return normalized, jobs, is_truncated


async def fetch_lever_jobs(site_slug: str) -> tuple[list[dict], list[dict], bool]:
    """
    Fetch all published jobs from a Lever board. Public API only.
    Returns (normalized_jobs, raw_jobs, is_truncated).
    """
    url = f"https://api.lever.co/v0/postings/{site_slug}?mode=json"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "FroncyBot/2.0"})
            resp.raise_for_status()
            jobs = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning(f"Lever HTTP error for {site_slug}: {e.response.status_code}")
        raise
    except Exception as e:
        logger.warning(f"Lever fetch failed for {site_slug}: {e}")
        raise

    is_truncated = False
    if not isinstance(jobs, list):
        jobs = []
        is_truncated = True
    else:
        link_hdr = resp.headers.get("link", "").lower()
        if 'rel="next"' in link_hdr or 'rel=next' in link_hdr:
            is_truncated = True

    normalized = []
    for job in jobs:
        try:
            # Lever timestamp is in milliseconds
            published_at = None
            ts = job.get("createdAt")
            if ts:
                published_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

            categories = job.get("categories", {})
            location = categories.get("location") or categories.get("allLocations", [None])[0]
            dept = categories.get("department", "")

            hosted_url = (job.get("hostedUrl") or "").strip()
            # Clean URL: ensure it points to the JD page, not /apply
            if hosted_url.endswith("/apply"):
                hosted_url = hosted_url[:-6]
            elif hosted_url.endswith("/apply/"):
                hosted_url = hosted_url[:-7]

            description = _strip_html(job.get("descriptionPlain") or job.get("description") or "")

            normalized.append({
                "external_id": job["id"],
                "title": job.get("text", "Untitled"),
                "location": location,
                "department": dept,
                "description": description,
                "published_at": published_at,
                "job_url": hosted_url,
                "apply_url": hosted_url,  # Always open the JD page
                "source_provider": "LEVER",
            })
        except Exception as e:
            logger.warning(f"Error normalizing Lever job {job.get('id')}: {e}")
            continue

    logger.info(f"Lever [{site_slug}]: fetched {len(normalized)} jobs (raw={len(jobs)}, truncated={is_truncated})")
    return normalized, jobs, is_truncated


async def fetch_ashby_jobs(board_name: str) -> tuple[list[dict], list[dict], bool]:
    """
    Fetch all published jobs from an Ashby board. Public API only.
    Returns (normalized_jobs, raw_jobs, is_truncated).
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "FroncyBot/2.0"})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning(f"Ashby HTTP error for {board_name}: {e.response.status_code}")
        raise
    except Exception as e:
        logger.warning(f"Ashby fetch failed for {board_name}: {e}")
        raise

    jobs = data.get("jobs", [])
    is_truncated = bool(data.get("nextPageToken") or data.get("hasMore"))
    if is_truncated:
        logger.warning(f"Ashby [{board_name}]: payload truncated flag detected")

    normalized = []
    for job in jobs:
        try:
            published_at = None
            pa_str = job.get("publishedAt")
            if pa_str:
                try:
                    published_at = datetime.fromisoformat(pa_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            location = job.get("location") or job.get("locationName")
            description = _strip_html(job.get("descriptionHtml") or job.get("descriptionPlain") or "")

            job_url = (job.get("jobUrl") or "").strip()
            # Clean URL: ensure it points to the JD page, not /application
            if job_url.endswith("/application"):
                job_url = job_url[:-12]
            elif job_url.endswith("/application/"):
                job_url = job_url[:-13]

            normalized.append({
                "external_id": job["id"],
                "title": job.get("title", "Untitled"),
                "location": location,
                "department": job.get("department") or job.get("team") or "",
                "description": description,
                "published_at": published_at,
                "job_url": job_url,
                "apply_url": job_url,  # Always open the JD page
                "source_provider": "ASHBY",
            })
        except Exception as e:
            logger.warning(f"Error normalizing Ashby job {job.get('id')}: {e}")
            continue

    logger.info(f"Ashby [{board_name}]: fetched {len(normalized)} jobs (raw={len(jobs)}, truncated={is_truncated})")
    return normalized, jobs, is_truncated


async def fetch_jobs_for_source(source: dict) -> tuple[list[dict], list[dict], bool]:
    """
    Route to the correct fetcher based on provider.
    Returns (normalized_jobs, raw_jobs, is_truncated).
    """
    provider = source["provider"].upper()
    token = source["board_token"]
    
    if provider == "GREENHOUSE":
        return await fetch_greenhouse_jobs(token)
    elif provider == "LEVER":
        return await fetch_lever_jobs(token)
    elif provider == "ASHBY":
        return await fetch_ashby_jobs(token)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def verify_board_token(provider: str, token: str) -> bool:
    """Quickly verify if a board token returns 200 OK before saving to DB."""
    import httpx
    provider = provider.upper()
    
    if provider == "GREENHOUSE":
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    elif provider == "LEVER":
        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    elif provider == "ASHBY":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    else:
        return False
        
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "FroncyBot/2.0"})
            return resp.status_code == 200
    except Exception:
        return False
