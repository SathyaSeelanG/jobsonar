"""Company career-page watchlist — individual job extraction.

Upgraded from page-level alerts to extracting individual job listings by:
1. Auto-detecting which ATS the company uses (Greenhouse, Lever, Ashby, etc.)
2. Calling that ATS's public API to get individual jobs
3. Falling back to JSON-LD / __NEXT_DATA__ / HTML card extraction
4. Only falling back to page-level scan as a last resort

Returns real Job objects with titles, URLs, descriptions, and inferred
experience levels — not just "go verify this page" entries.

Fails soft per company; one broken/blocked/JS-only page never kills the run.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import urllib.parse
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

from ..models import Job
from .scrapers import DELAY, _headers

MERN_KEYWORDS = (
    "react", "node", "mongo", "express", "mern", "full stack", "full-stack",
    "frontend", "front-end", "javascript", "typescript",
    "python", "django", "flask", "fastapi",
)

# Enhanced selectors for extracting job descriptions from individual posting pages
JOB_DESCRIPTION_SELECTORS = [
    # Schema.org / structured data
    "[itemprop='description']",
    # Generic job posting selectors
    ".job-description",
    ".job-posting-description",
    ".posting-description",
    ".description",
    ".job-details",
    ".job-detail",
    ".job-content",
    ".posting",
    ".posting-body",
    # ATS-specific selectors (Greenhouse, Lever, etc.)
    "[data-test-id='description']",
    ".gh-jobs-board-opening-body",
    ".lever-posting-body",
    ".ashby-job-description",
    # Generic containers
    "main",
    "article",
    "[role='main']",
]


def _find_careers_link(homepage: str, soup: BeautifulSoup) -> str | None:
    for a in soup.find_all("a", href=True):
        text = (a.get_text(strip=True) or "").lower()
        href = a["href"].lower()
        if any(k in text or k in href for k in ("career", "job", "hiring")):
            return urllib.parse.urljoin(homepage, a["href"])
    return None


def _static_fetch(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
        if resp.status_code != 200:
            return None
        time.sleep(DELAY)
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


def _static_fetch_html(url: str) -> str:
    """Fetch raw HTML string from URL. Returns '' on failure."""
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
        if resp.status_code != 200:
            return ""
        time.sleep(DELAY)
        return resp.text
    except Exception:
        return ""


def _js_fetch(url: str) -> str:
    """Rendered page text via headless Playwright. '' on any failure."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_context().new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            text = page.inner_text("body")
            html = page.content()
            browser.close()
            return html  # return HTML, not just text
    except Exception:
        return ""


def _extract_text(html: str, max_len: int = 6000) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        "[itemprop='description']",
        ".job-description",
        ".description",
        ".job-details",
        ".posting",
        "main",
        "article",
    ):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if len(text) > 200:
                return text[:max_len]
    body = soup.select_one("body")
    return body.get_text(" ", strip=True)[:max_len] if body else ""


def _extract_text_improved(html: str, max_len: int = 6000) -> str:
    """Enhanced text extraction targeting job description sections.
    
    Tries multiple selector strategies to find the richest job description
    content, with fallbacks to generic containers.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    
    # Try each selector in order
    for selector in JOB_DESCRIPTION_SELECTORS:
        try:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if len(text) > 200:
                    return text[:max_len]
        except Exception:
            continue
    
    # Fallback: extract from body with quality heuristic
    body = soup.select_one("body")
    if body:
        # Remove script/style tags to reduce noise
        for tag in body.find_all(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = body.get_text(" ", strip=True)
        return text[:max_len] if text else ""
    
    return ""


def _fetch_job_detail(url: str, js_rendered: bool = False) -> str:
    """Fetch and extract full job description from individual job posting page.
    
    Tries static fetch first, then falls back to JS rendering if needed.
    Returns extracted description text or empty string on failure.
    """
    if not url or not url.startswith("http"):
        return ""
    
    # Try static fetch first (faster)
    html = _static_fetch_html(url) if not js_rendered else ""
    
    # Fall back to JS rendering if static fetch failed or if js_rendered flag is set
    if not html:
        html = _js_fetch(url)
    
    if not html:
        return ""
    
    detail = _extract_text_improved(html)
    return detail


def _hydrate_job_details(jobs: list[Job], careers_url: str, js_rendered: bool = False) -> list[Job]:
    """Fetch individual job pages to enrich job descriptions."""
    jobs_needing_detail = []
    for i, job in enumerate(jobs):
        desc_len = len((job.description or "").strip())
        has_valid_url = job.url and job.url.startswith("http") and job.url != careers_url
        
        needs_detail = (desc_len < 500 or not has_valid_url)
        if needs_detail:
            jobs_needing_detail.append((i, job))
    
    if not jobs_needing_detail:
        return jobs
        
    if js_rendered:
        # For JS rendered pages, fetching in parallel spawns too many Chromium instances.
        # It's much faster and safer to use a single browser and fetch sequentially.
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_context().new_page()
                for idx, job in jobs_needing_detail:
                    url = job.url or careers_url
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=15000)
                        html = page.content()
                        detail = _extract_text_improved(html)
                        if detail and len(detail) > 100:
                            jobs[idx].description = detail[:6000]
                    except Exception:
                        pass
                browser.close()
        except Exception:
            pass
    else:
        # Static pages can be fetched in parallel safely using requests
        def fetch_and_update(idx_job):
            idx, job = idx_job
            try:
                detail = _fetch_job_detail(job.url or careers_url, js_rendered=False)
                if detail and len(detail) > 100:
                    return (idx, detail)
            except Exception:
                pass
            return (idx, None)
            
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch_and_update, item) for item in jobs_needing_detail]
            for future in as_completed(futures):
                try:
                    idx, detail = future.result()
                    if detail:
                        jobs[idx].description = detail[:6000]
                except Exception:
                    continue
                    
    return jobs


def _matches(text_lower: str, signals: list[str]) -> list[str]:
    return [s for s in signals if s in text_lower]


def _job_matches_keywords(job: Job) -> bool:
    """Check if a job's title or description contains relevant keywords."""
    text = f"{job.title} {job.description}".lower()
    return any(kw in text for kw in MERN_KEYWORDS)


def check_company(entry: dict, fresher_signals: list[str], negative_signals: list[str],
                  extract_jobs: bool = True) -> list[Job]:
    """Check a company's careers page for job listings.

    When extract_jobs=True (default), attempts to extract individual job
    listings via ATS detection + API calls + structured data parsing.
    When extract_jobs=False, falls back to page-level signal scanning.
    """
    name = entry["name"]
    homepage = entry["homepage"]
    careers_url = entry.get("careers_url_override")
    js_rendered = entry.get("js_rendered", False)
    explicit_ats = entry.get("ats")
    explicit_token = entry.get("board_token")

    careers_page_url = careers_url or homepage

    if not extract_jobs:
        # Page-level "verify manually" scanning is disabled — it produced
        # generic, non-actionable placeholder entries instead of real jobs.
        return []

    # When no careers URL is configured, resolve it from the homepage first.
    # Scanning the homepage directly misses most embedded ATS boards.
    if not careers_url:
        if js_rendered:
            homepage_html = _js_fetch(homepage)
            if homepage_html:
                soup = BeautifulSoup(homepage_html, "html.parser")
                careers_page_url = _find_careers_link(homepage, soup) or homepage
        else:
            homepage_soup = _static_fetch(homepage)
            if homepage_soup:
                careers_page_url = _find_careers_link(homepage, homepage_soup) or homepage

    # Strategy 1: Use explicit ATS config from companies.yaml
    if explicit_ats and explicit_token:
        from .ats import fetch_ats_jobs, infer_experience_level
        # Each fetcher reads its token under a different key. The fallback
        # "<platform>_token" is kept for unknown platforms but matches nothing
        # in fetch_ats_jobs, so such a company simply falls through below.
        param_keys = {
            "greenhouse": "board_token",
            "lever": "site_slug",
            "ashby": "company_name",
            "smartrecruiters": "company_id",
            "rippling": "slug",
            "keka": "subdomain",
            "recruitee": "company",
            "personio": "company",
            "breezy": "company",
            "workable": "company",
            "bamboohr": "company",
        }
        params = {param_keys.get(explicit_ats, f"{explicit_ats}_token"): explicit_token}

        try:
            jobs = fetch_ats_jobs(explicit_ats, params)
            # Only commit to the explicit ATS if it actually yielded something.
            # A stale or renamed token used to end the cascade here and drop the
            # company entirely, even though Strategies 2-5 could still find it.
            if jobs:
                jobs = _hydrate_job_details(jobs, careers_page_url, js_rendered=js_rendered)
                return _filter_and_enrich(jobs, name, careers_page_url)
        except Exception:
            pass

    # Strategy 2: Fetch careers page HTML and detect ATS
    html = ""
    if js_rendered:
        html = _js_fetch(careers_page_url)
    else:
        html = _static_fetch_html(careers_page_url)

    if not html:
        # If static fetch failed and page might be JS-rendered, try Playwright
        html = _js_fetch(careers_page_url)

    if not html:
        return []

    # Strategy 3: Auto-detect ATS from HTML
    from .ats_detect import detect_ats_from_html
    detected = detect_ats_from_html(html, careers_page_url)
    if detected:
        platform, params = detected
        from .ats import fetch_ats_jobs
        try:
            jobs = fetch_ats_jobs(platform, params)
            if jobs:
                jobs = _hydrate_job_details(jobs, careers_page_url, js_rendered=js_rendered)
                return _filter_and_enrich(jobs, name, careers_page_url)
        except Exception as e:
            print(f"[{name}] ATS fetch failed: {e}")
            pass

    # Strategy 4: JSON-LD extraction
    from .ats_detect import parse_jsonld_jobs
    jsonld_items = parse_jsonld_jobs(html)
    if jsonld_items:
        from .ats import infer_experience_level
        jobs = []
        for item in jsonld_items:
            title = item.get("title", "")
            if not title:
                continue
            job = Job(
                title=title,
                company=item.get("hiringOrganization", "") or name,
                location=item.get("location", ""),
                url=item.get("url", careers_page_url),
                description=item.get("description", "")[:6000],
                source="watchlist:jsonld",
                salary=item.get("baseSalary", ""),
            )
            job.experience_level = infer_experience_level(job.title, job.description)
            job.company_careers_url = careers_page_url
            jobs.append(job)
        if jobs:
            jobs = _hydrate_job_details(jobs, careers_page_url, js_rendered=js_rendered)
            return _filter_and_enrich(jobs, name, careers_page_url)

    # Strategy 5: __NEXT_DATA__ extraction
    from .ats_detect import parse_nextdata_jobs
    next_items = parse_nextdata_jobs(html)
    if next_items:
        from .ats import infer_experience_level
        jobs = []
        for item in next_items:
            title = item.get("title", "")
            if not title:
                continue
            job = Job(
                title=title,
                company=item.get("company", "") or name,
                location=item.get("location", ""),
                url=item.get("url", careers_page_url),
                description=item.get("description", "")[:6000],
                source="watchlist:nextdata",
            )
            job.experience_level = infer_experience_level(job.title, job.description)
            job.company_careers_url = careers_page_url
            jobs.append(job)
        if jobs:
            jobs = _hydrate_job_details(jobs, careers_page_url, js_rendered=js_rendered)
            return _filter_and_enrich(jobs, name, careers_page_url)

    # Strategy 6: HTML card/link extraction (heuristic fallback)
    from .ats_detect import extract_jobs_from_html
    html_items = extract_jobs_from_html(html, careers_page_url)
    if html_items:
        from .ats import infer_experience_level
        jobs = []
        for item in html_items:
            title = item.get("title", "")
            if not title:
                continue
            job = Job(
                title=title,
                company=name,
                location=item.get("location", ""),
                url=item.get("url", careers_page_url),
                description=item.get("description", "")[:6000],
                source="watchlist:html",
            )
            job.experience_level = infer_experience_level(job.title, job.description)
            job.company_careers_url = careers_page_url
            jobs.append(job)
        if jobs:
            jobs = _hydrate_job_details(jobs, careers_page_url, js_rendered=js_rendered)
            return _filter_and_enrich(jobs, name, careers_page_url)

    # No individually-extractable jobs found for this company — skip it
    # rather than emitting a generic "verify manually" placeholder.
    return []


def _filter_and_enrich(jobs: list[Job], company_name: str, careers_url: str) -> list[Job]:
    """Filter jobs by MERN keywords and enrich with company info."""
    from .ats import infer_experience_level
    filtered = []
    seen_titles = set()
    for job in jobs:
        # Set company if missing
        if not job.company:
            job.company = company_name
        # Infer experience level
        if not job.experience_level:
            job.experience_level = infer_experience_level(job.title, job.description)
        # Set careers URL
        job.company_careers_url = careers_url
        # Dedupe by normalized title
        norm_title = job.title.lower().strip()
        if norm_title in seen_titles:
            continue
        seen_titles.add(norm_title)
        # Filter: must match MERN/Python keywords
        if _job_matches_keywords(job):
            filtered.append(job)
    return filtered


def scan_watchlist(config_path: Path | str, extract_jobs: bool = True, company_limit: int = 0,
                    max_workers: int = 8) -> list[Job]:
    if isinstance(config_path, str):
        config_path = Path(config_path)
    if not config_path or not config_path.exists():
        return []
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    fresher_signals = [s.lower() for s in cfg.get("fresher_signals", [])]
    negative_signals = [s.lower() for s in cfg.get("negative_signals", [])]
    jobs = []
    companies = cfg.get("companies", [])
    if company_limit and company_limit > 0:
        companies = companies[:company_limit]
    static_entries = [entry for entry in companies if not entry.get("js_rendered")]
    js_entries = [entry for entry in companies if entry.get("js_rendered")]

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(static_entries)))) as pool:
        futures = {
            pool.submit(check_company, entry, fresher_signals, negative_signals, extract_jobs): entry
            for entry in static_entries
        }
        for future in as_completed(futures):
            try:
                jobs += future.result()
            except Exception as e:
                import traceback
                traceback.print_exc()
                continue

    # JS-rendered companies need a real (headless) browser per fetch, which is
    # heavier than a plain HTTP request — run these with modest parallelism
    # (a few Chromium instances at once) instead of one-by-one, since the
    # watchlist now includes ~20 JS-rendered corporate career sites.
    if js_entries:
        with ThreadPoolExecutor(max_workers=min(4, len(js_entries))) as pool:
            futures = {
                pool.submit(check_company, entry, fresher_signals, negative_signals, extract_jobs): entry
                for entry in js_entries
            }
            for future in as_completed(futures):
                try:
                    jobs += future.result()
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    continue
    return jobs
