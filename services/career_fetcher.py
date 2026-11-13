"""
Career Page Fetchers for Froncy V2.
Supports: Greenhouse (Phase 1).
Future: Lever, Ashby.

All fetchers are pure HTTP — no browser automation, no authentication.
All public endpoints only.
"""
import html
import re
import urllib.parse
import httpx
from datetime import datetime, timezone, timedelta
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




def _parse_workday_token(token: str) -> tuple[str, str, str]:
    """
    Parse a Workday board token into (host, tenant, site_id).
    Accepts:
      - 'fnz.wd3.myworkdayjobs.com/fnz_careers'
      - 'fnz.wd3/fnz_careers'
      - 'https://fnz.wd3.myworkdayjobs.com/en-US/fnz_careers'
      - 'https://elevancehealth.wd1.myworkdayjobs.com/carelonglobal_in'
      - 'accenture.wd103.myworkdayjobs.com/AccentureCareers'
    """
    token = token.strip()
    if token.startswith("http://") or token.startswith("https://"):
        parsed = urllib.parse.urlparse(token)
        host = parsed.netloc
        path_parts = [p for p in parsed.path.split("/") if p and p not in ("en-US", "en")]
        site = path_parts[0] if path_parts else ""
    else:
        parts = token.split("/")
        host_part = parts[0]
        site = parts[1] if len(parts) > 1 else ""
        if "myworkdayjobs.com" not in host_part:
            host = f"{host_part}.myworkdayjobs.com"
        else:
            host = host_part

    tenant = host.split(".")[0]
    return host, tenant, site


def _parse_workday_posted_on(posted_on_str: str) -> datetime | None:
    """Parse Workday relative/text posting dates like 'Posted Today', 'Posted 2 Days Ago'."""
    if not posted_on_str:
        return None
    s = posted_on_str.lower().strip()
    now = datetime.now(timezone.utc)
    if "today" in s:
        return now
    if "yesterday" in s:
        return now - timedelta(days=1)
    m = re.search(r'posted\s+(\d+)\s+days?\s+ago', s)
    if m:
        return now - timedelta(days=int(m.group(1)))
    m_hours = re.search(r'posted\s+(\d+)\s+hours?\s+ago', s)
    if m_hours:
        return now - timedelta(hours=int(m_hours.group(1)))
    if "30+" in s:
        return now - timedelta(days=35)
    return None


async def fetch_workday_jobs(board_token: str) -> tuple[list[dict], list[dict], bool]:
    """
    Fetch published jobs from a Workday career portal.
    Uses Workday's public CXS JSON API.
    Paginates up to 100 jobs (5 pages) or until encountering stale postings.
    Returns (normalized_jobs, raw_jobs, is_truncated).
    """
    host, tenant, site = _parse_workday_token(board_token)
    if not host or not site:
        logger.warning(f"Workday: Invalid token '{board_token}'. Expected 'host/site_id'.")
        return [], [], False

    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    raw_jobs = []
    is_truncated = False
    page_size = 20
    max_pages = 5

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for page in range(max_pages):
            offset = page * page_size
            payload = {
                "appliedFacets": {},
                "limit": page_size,
                "offset": offset,
                "searchText": ""
            }

            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning(f"Workday HTTP error for {board_token} (page {page}): {e.response.status_code}")
                if page == 0:
                    raise
                break
            except Exception as e:
                logger.warning(f"Workday fetch failed for {board_token} (page {page}): {e}")
                if page == 0:
                    raise
                break

            postings = data.get("jobPostings", [])
            total = data.get("total", 0)
            if not postings:
                break

            raw_jobs.extend(postings)

            if len(raw_jobs) >= total or len(postings) < page_size:
                break

            if page == max_pages - 1 and len(raw_jobs) < total:
                is_truncated = True

    normalized = []
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for job in raw_jobs:
            try:
                title = job.get("title", "Untitled")
                ext_path = job.get("externalPath", "")
                if not ext_path:
                    continue

                bullets = job.get("bulletFields") or []
                external_id = bullets[0] if bullets else ""
                if not external_id:
                    slug_match = re.search(r'_([A-Z0-9\-]+)$', ext_path)
                    external_id = slug_match.group(1) if slug_match else ext_path.split("/")[-1]

                location = job.get("locationsText")
                posted_on = job.get("postedOn")
                published_at = _parse_workday_posted_on(posted_on)

                job_web_url = f"https://{host}/en-US/{site}{ext_path}"
                clean_url = job_web_url.split("?")[0].rstrip("/")
                if clean_url.endswith("/apply") or clean_url.endswith("/applyManually"):
                    clean_url = re.sub(r'/apply(/applyManually)?$', '', clean_url)

                detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{ext_path}"
                description = ""
                try:
                    d_resp = await client.get(detail_url, headers=headers)
                    if d_resp.status_code == 200:
                        d_data = d_resp.json()
                        info = d_data.get("jobPostingInfo", {})
                        raw_desc = info.get("jobDescription") or ""
                        description = _strip_html(raw_desc)
                        start_date = info.get("startDate")
                        if start_date:
                            try:
                                published_at = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug(f"Workday detail fetch skipped for {ext_path}: {e}")

                normalized.append({
                    "external_id": str(external_id),
                    "title": title,
                    "location": location,
                    "department": "",
                    "description": description,
                    "published_at": published_at,
                    "job_url": clean_url,
                    "apply_url": clean_url,
                    "source_provider": "WORKDAY",
                })
            except Exception as e:
                logger.warning(f"Error normalizing Workday job {job.get('externalPath')}: {e}")
                continue

    logger.info(f"Workday [{board_token}]: fetched {len(normalized)} jobs (raw={len(raw_jobs)}, truncated={is_truncated})")
    return normalized, raw_jobs, is_truncated


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
    elif provider == "WORKDAY":
        return await fetch_workday_jobs(token)
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
    elif provider == "WORKDAY":
        host, tenant, site = _parse_workday_token(token)
        if not host or not site:
            return False
        wday_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        wday_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json"
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.post(wday_url, json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, headers=wday_headers)
                return resp.status_code == 200
        except Exception:
            return False
    else:
        return False
        
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "FroncyBot/2.0"})
            return resp.status_code == 200
    except Exception:
        return False
