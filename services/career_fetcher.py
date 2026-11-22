"""
Career Page Fetchers for Froncy V2.
Supports: Greenhouse (Phase 1).
Future: Lever, Ashby.

All fetchers are pure HTTP — no browser automation, no authentication.
All public endpoints only.
"""
import html
import re
import json
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


def _parse_amazon_token(token: str) -> tuple[str | None, str | None]:
    """
    Parse an Amazon board token into (category, country).
    Accepts:
      - 'software-development/IND' -> ('software-development', 'IND')
      - 'IND' -> ('software-development', 'IND')
      - 'software-development/USA' -> ('software-development', 'USA')
      - 'data-science/IND' -> ('data-science', 'IND')
      - 'all/IND' -> (None, 'IND')
      - 'category=software-development&country=IND' -> ('software-development', 'IND')
    """
    ISO2_TO_ISO3 = {
        "IN": "IND",
        "US": "USA",
        "UK": "GBR",
        "GB": "GBR",
        "CA": "CAN",
        "DE": "DEU",
        "AU": "AUS",
        "IE": "IRL",
        "SG": "SGP",
        "NL": "NLD",
        "FR": "FRA",
        "JP": "JPN",
    }

    def _normalize_country(c: str | None) -> str | None:
        if not c:
            return None
        c_clean = c.strip().upper()
        return ISO2_TO_ISO3.get(c_clean, c_clean)

    token = (token or "").strip()
    if "=" in token:
        import urllib.parse
        parsed = urllib.parse.parse_qs(token)
        cat = parsed.get("category", [None])[0] or parsed.get("category[]", [None])[0]
        country = parsed.get("country", [None])[0] or parsed.get("country[]", [None])[0]
        return cat, _normalize_country(country)

    if "/" in token:
        parts = token.split("/", 1)
        cat = parts[0].strip() if parts[0].strip().lower() != "all" else None
        country = parts[1].strip() if parts[1].strip().lower() != "all" else None
        return cat, _normalize_country(country)

    # If single 2 or 3 letter uppercase token (e.g. IN, IND, US, USA), default category to software-development
    if len(token) in (2, 3) and token.isalpha():
        return "software-development", _normalize_country(token)

    return token.lower(), None


async def fetch_amazon_jobs(board_token: str) -> tuple[list[dict], list[dict], bool]:
    """
    Fetch published jobs from Amazon Careers (amazon.jobs). Public JSON API.
    Returns (normalized_jobs, raw_jobs, is_truncated).
    """
    category, country = _parse_amazon_token(board_token)

    url = "https://www.amazon.jobs/en/search.json"
    params = {
        "sort": "recent",
        "result_limit": 100,
        "offset": 0,
    }
    if category:
        params["category[]"] = category
    if country:
        params["country"] = country

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
    except Exception as e:
        logger.error(f"Amazon [{board_token}]: network error: {e}")
        return [], [], False

    if resp.status_code != 200:
        logger.error(f"Amazon [{board_token}]: HTTP {resp.status_code}")
        return [], [], False

    try:
        data = resp.json()
    except Exception as e:
        logger.error(f"Amazon [{board_token}]: failed to parse JSON: {e}")
        return [], [], False

    # Tripwire: Verify expected schema structure
    if not isinstance(data, dict) or "jobs" not in data or not isinstance(data.get("jobs"), list):
        logger.error(f"Amazon [{board_token}]: unexpected JSON shape: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return [], [], False

    raw_jobs = data.get("jobs") or []
    hits = data.get("hits") or len(raw_jobs)
    is_truncated = hits > len(raw_jobs)

    normalized = []
    from dateutil.parser import parse as parse_date

    for job in raw_jobs:
        try:
            external_id = job.get("id_icims") or job.get("id")
            if not external_id:
                continue

            title = (job.get("title") or "Untitled").strip()
            location = (job.get("location") or job.get("normalized_location") or "Unknown").strip()
            dept = job.get("job_category") or category or "Software Development"

            # Parse published_at
            published_at = None
            posted_date = job.get("posted_date")
            if posted_date:
                try:
                    published_at = parse_date(posted_date)
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            # Full description text combining basic & preferred qualifications
            desc_parts = []
            if job.get("description"):
                desc_parts.append(job["description"].strip())
            if job.get("basic_qualifications"):
                desc_parts.append("Basic Qualifications:\n" + job["basic_qualifications"].strip())
            if job.get("preferred_qualifications"):
                desc_parts.append("Preferred Qualifications:\n" + job["preferred_qualifications"].strip())

            full_description = _strip_html("\n\n".join(desc_parts))
            job_path = job.get("job_path") or f"/en/jobs/{external_id}"
            clean_url = f"https://www.amazon.jobs{job_path}"

            normalized.append({
                "external_id": str(external_id),
                "title": title,
                "location": location,
                "department": dept,
                "description": full_description,
                "published_at": published_at,
                "job_url": clean_url,
                "apply_url": clean_url,
                "source_provider": "AMAZON",
            })
        except Exception as e:
            logger.warning(f"Error normalizing Amazon job {job.get('id_icims')}: {e}")
            continue

    logger.info(f"Amazon [{board_token}]: fetched {len(normalized)} jobs (raw={len(raw_jobs)}, hits={hits})")
    return normalized, raw_jobs, is_truncated


def _parse_apple_token(token: str) -> tuple[str | None, str | None]:
    """
    Parse an Apple board token into (search_query, location).
    Accepts:
      - 'india-INDC' -> (None, 'india-INDC')
      - 'IND' / 'IN' / 'India' -> (None, 'india-INDC')
      - 'USA' / 'US' / 'United States' -> (None, 'united-states-USA')
      - 'Software/india-INDC' -> ('Software', 'india-INDC')
      - 'Software/IND' -> ('Software', 'india-INDC')
      - 'Software' -> ('Software', 'india-INDC')
    """
    token = (token or "").strip()
    if not token:
        return None, "india-INDC"

    COUNTRY_MAP = {
        "IND": "india-INDC",
        "IN": "india-INDC",
        "INDIA": "india-INDC",
        "USA": "united-states-USA",
        "US": "united-states-USA",
        "UNITED STATES": "united-states-USA",
        "GBR": "united-kingdom-GBR",
        "UK": "united-kingdom-GBR",
        "CAN": "canada-CAN",
        "CA": "canada-CAN",
        "SGP": "singapore-SGP",
        "SG": "singapore-SGP",
        "DEU": "germany-DEU",
        "DE": "germany-DEU",
        "AUS": "australia-AUS",
        "AU": "australia-AUS",
    }

    if "/" in token:
        parts = token.split("/", 1)
        query = parts[0].strip() if parts[0].strip().lower() != "all" else None
        loc_raw = parts[1].strip()
        loc = COUNTRY_MAP.get(loc_raw.upper(), loc_raw)
        return query, loc

    # If matches a country code directly
    if token.upper() in COUNTRY_MAP:
        return None, COUNTRY_MAP[token.upper()]
    if token.lower().endswith("-indc") or token.lower().endswith("-usa") or token.lower().endswith("-gbr"):
        return None, token

    # Default: treated as search query within India
    return token, "india-INDC"


async def fetch_apple_jobs(board_token: str) -> tuple[list[dict], list[dict], bool]:
    """
    Fetch published jobs from Apple Careers (jobs.apple.com).
    Zero-browser plain HTTP parsing via React Router static hydration payload.
    Omits 'sort' parameter so Apple defaults to reverse chronological order (newest first).
    Returns (normalized_jobs, raw_jobs, is_truncated).
    """
    query, location = _parse_apple_token(board_token)
    url = "https://jobs.apple.com/en-in/search"
    params = {}
    if query:
        params["search"] = query
    if location:
        params["location"] = location

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
    except Exception as e:
        logger.error(f"Apple [{board_token}]: network error: {e}")
        return [], [], False

    if resp.status_code != 200:
        logger.error(f"Apple [{board_token}]: HTTP {resp.status_code}")
        return [], [], False

    # Defensive Tripwire: Locate window.__staticRouterHydrationData
    match = re.search(r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\((.*?)\);", resp.text)
    if not match:
        logger.error(f"Apple [{board_token}]: tripwire triggered — __staticRouterHydrationData not found in HTML response")
        return [], [], False

    try:
        raw_json = json.loads(match.group(1))
        apple_data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except Exception as e:
        logger.error(f"Apple [{board_token}]: failed to parse hydration JSON: {e}")
        return [], [], False

    search_info = apple_data.get("loaderData", {}).get("search", {})
    raw_jobs = search_info.get("searchResults")
    if not isinstance(raw_jobs, list):
        logger.error(f"Apple [{board_token}]: unexpected searchResults structure: {type(raw_jobs)}")
        return [], [], False

    total_records = search_info.get("totalRecords", len(raw_jobs))
    is_truncated = total_records > len(raw_jobs)
    normalized = []
    from dateutil.parser import parse as parse_date

    for job in raw_jobs:
        try:
            ext_id = str(job.get("positionId") or job.get("id"))
            if not ext_id:
                continue

            title = (job.get("postingTitle") or "Untitled").strip()
            loc_names = [l.get("name") or l.get("countryName") for l in job.get("locations", []) if l.get("name") or l.get("countryName")]
            location = ", ".join(loc_names) if loc_names else "India"
            dept = job.get("team", {}).get("teamName") or "Engineering"
            desc = _strip_html(job.get("jobSummary") or "")

            published_at = None
            date_raw = job.get("postDateInGMT") or job.get("postingDate")
            if date_raw:
                try:
                    published_at = parse_date(date_raw)
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            transformed_title = job.get("transformedPostingTitle") or ""
            pos_id = job.get("positionId") or ext_id
            clean_url = f"https://jobs.apple.com/en-in/details/{pos_id}/{transformed_title}"

            normalized.append({
                "external_id": ext_id,
                "title": title,
                "location": location,
                "department": dept,
                "description": desc,
                "published_at": published_at,
                "job_url": clean_url,
                "apply_url": clean_url,
                "source_provider": "APPLE",
            })
        except Exception as e:
            logger.warning(f"Error normalizing Apple job {job.get('id')}: {e}")
            continue

    logger.info(f"Apple [{board_token}]: fetched {len(normalized)} jobs (raw={len(raw_jobs)}, totalRecords={total_records})")
    return normalized, raw_jobs, is_truncated


def _parse_google_token(token: str) -> tuple[str | None, str | None]:
    """
    Parse a Google board token into (search_query, location).
    Accepts:
      - 'India' / 'IND' / 'IN' -> (None, 'India')
      - 'USA' / 'US' / 'United States' -> (None, 'United States')
      - 'software/India' -> ('software', 'India')
      - 'software/IND' -> ('software', 'India')
      - 'software' -> ('software', 'India')
    """
    token = (token or "").strip()
    if not token:
        return None, "India"

    COUNTRY_MAP = {
        "IND": "India",
        "IN": "India",
        "INDIA": "India",
        "USA": "United States",
        "US": "United States",
        "UNITED STATES": "United States",
        "GBR": "United Kingdom",
        "UK": "United Kingdom",
        "CAN": "Canada",
        "CA": "Canada",
        "SGP": "Singapore",
        "SG": "Singapore",
        "DEU": "Germany",
        "DE": "Germany",
        "AUS": "Australia",
        "AU": "Australia",
    }

    if "/" in token:
        parts = token.split("/", 1)
        query = parts[0].strip() if parts[0].strip().lower() != "all" else None
        loc_raw = parts[1].strip()
        loc = COUNTRY_MAP.get(loc_raw.upper(), loc_raw)
        return query, loc

    if token.upper() in COUNTRY_MAP:
        return None, COUNTRY_MAP[token.upper()]

    # Default: search query within India
    return token, "India"


async def fetch_google_jobs(board_token: str) -> tuple[list[dict], list[dict], bool]:
    """
    Fetch published jobs from Google Careers (careers.google.com).
    Zero-browser plain HTTP parsing via AF_initDataCallback payload.
    Returns (normalized_jobs, raw_jobs, is_truncated).
    """
    query, location = _parse_google_token(board_token)
    url = "https://careers.google.com/jobs/results/"
    params = {}
    if query:
        params["q"] = query
    if location:
        params["location"] = location

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
    except Exception as e:
        logger.error(f"Google [{board_token}]: network error: {e}")
        return [], [], False

    if resp.status_code != 200:
        logger.error(f"Google [{board_token}]: HTTP {resp.status_code}")
        return [], [], False

    # Defensive Tripwire: Locate AF_initDataCallback with key: 'ds:1'
    match = re.search(r"AF_initDataCallback\(\{key:\s*'ds:1'.*?data:(.*?),\s*sideChannel:", resp.text, re.DOTALL)
    if not match:
        logger.error(f"Google [{board_token}]: tripwire triggered — AF_initDataCallback ds:1 not found in HTML response")
        return [], [], False

    try:
        data = json.loads(match.group(1).strip())
    except Exception as e:
        logger.error(f"Google [{board_token}]: failed to parse AF_initDataCallback JSON: {e}")
        return [], [], False

    if not isinstance(data, list) or len(data) == 0 or not isinstance(data[0], list):
        logger.error(f"Google [{board_token}]: unexpected JSON shape: {type(data)}")
        return [], [], False

    raw_jobs = data[0]
    total_records = data[2] if len(data) > 2 and isinstance(data[2], int) else len(raw_jobs)
    is_truncated = total_records > len(raw_jobs)

    normalized = []
    for job in raw_jobs:
        try:
            # Schema tripwire check on positional elements
            if not isinstance(job, list) or len(job) < 11 or not isinstance(job[0], str) or not isinstance(job[1], str):
                continue

            ext_id = str(job[0])
            title = job[1].strip()
            apply_url = job[2] if len(job) > 2 and isinstance(job[2], str) else f"https://careers.google.com/jobs/results/{ext_id}"
            clean_url = f"https://careers.google.com/jobs/results/{ext_id}"

            # Assemble full description from components
            desc_parts = []
            if len(job) > 10 and isinstance(job[10], list) and len(job[10]) > 1 and job[10][1]:
                desc_parts.append(job[10][1])
            if len(job) > 3 and isinstance(job[3], list) and len(job[3]) > 1 and job[3][1]:
                desc_parts.append("Responsibilities:\n" + job[3][1])
            if len(job) > 4 and isinstance(job[4], list) and len(job[4]) > 1 and job[4][1]:
                desc_parts.append("Qualifications:\n" + job[4][1])
            full_desc = _strip_html("\n\n".join(desc_parts))

            # Locations
            locs = []
            if len(job) > 9 and isinstance(job[9], list):
                for loc_entry in job[9]:
                    if isinstance(loc_entry, list) and loc_entry:
                        locs.append(loc_entry[0])
            location = ", ".join(locs) if locs else "India"

            # Published at timestamp
            published_at = None
            if len(job) > 12 and isinstance(job[12], list) and job[12] and isinstance(job[12][0], (int, float)):
                try:
                    published_at = datetime.fromtimestamp(job[12][0], tz=timezone.utc)
                except Exception:
                    pass

            normalized.append({
                "external_id": ext_id,
                "title": title,
                "location": location,
                "department": "Engineering",
                "description": full_desc,
                "published_at": published_at,
                "job_url": clean_url,
                "apply_url": apply_url,
                "source_provider": "GOOGLE",
            })
        except Exception as e:
            logger.warning(f"Error normalizing Google job: {e}")
            continue

    logger.info(f"Google [{board_token}]: fetched {len(normalized)} jobs (raw={len(raw_jobs)}, total={total_records})")
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
    elif provider == "AMAZON":
        return await fetch_amazon_jobs(token)
    elif provider == "APPLE":
        return await fetch_apple_jobs(token)
    elif provider == "GOOGLE":
        return await fetch_google_jobs(token)
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
    elif provider == "AMAZON":
        category, country = _parse_amazon_token(token)
        url = "https://www.amazon.jobs/en/search.json"
        params = {"result_limit": 1}
        if category:
            params["category[]"] = category
        if country:
            params["country"] = country
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = await client.get(url, params=params, headers=headers)
                return resp.status_code == 200 and isinstance(resp.json().get("jobs"), list)
        except Exception:
            return False
    elif provider == "APPLE":
        query, location = _parse_apple_token(token)
        url = "https://jobs.apple.com/en-in/search"
        params = {}
        if query:
            params["search"] = query
        if location:
            params["location"] = location
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = await client.get(url, params=params, headers=headers)
                return resp.status_code == 200 and "__staticRouterHydrationData" in resp.text
        except Exception:
            return False
    elif provider == "GOOGLE":
        query, location = _parse_google_token(token)
        url = "https://careers.google.com/jobs/results/"
        params = {}
        if query:
            params["q"] = query
        if location:
            params["location"] = location
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = await client.get(url, params=params, headers=headers)
                return resp.status_code == 200 and "AF_initDataCallback" in resp.text
        except Exception:
            return False
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
