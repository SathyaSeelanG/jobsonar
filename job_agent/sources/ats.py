"""Direct ATS feeds — Greenhouse & Lever public job-board APIs (no auth needed),
plus Ashby, Workday, SmartRecruiters, Rippling, and best-effort Keka scraper.
Also includes generic JSON-LD and __NEXT_DATA__ extraction for custom career pages."""
import html as html_mod
import json
import re
import time
import urllib.parse

import requests

from ..models import Job
from .scrapers import _headers, DELAY


def fetch_greenhouse(board_token: str) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    resp = requests.get(url, headers=_headers(), timeout=30)
    if resp.status_code != 200:
        return []
    jobs = []
    for item in resp.json().get("jobs", []):
        desc = (item.get("content") or "")
        if desc:
            desc = html_mod.unescape(desc)
            desc = re.sub(r"<[^>]+>", " ", desc).strip()
        location = (item.get("location") or {}).get("name", "")
        jobs.append(Job(
            title=item.get("title", ""),
            company=board_token,
            location=location,
            url=item.get("absolute_url", ""),
            description=desc[:6000],
            source="greenhouse",
            posted_at=item.get("updated_at", ""),
        ))
    return jobs


def fetch_lever(board_token: str) -> list[Job]:
    for base in ("https://api.lever.co", "https://api.eu.lever.co"):
        url = f"{base}/v0/postings/{board_token}?mode=json"
        resp = requests.get(url, headers=_headers(), timeout=30)
        if resp.status_code == 200:
            break
    else:
        return []
    jobs = []
    for item in resp.json():
        cats = item.get("categories") or {}
        desc = item.get("descriptionPlain", "") or item.get("description", "")
        if desc:
            desc = html_mod.unescape(desc)
            desc = re.sub(r"<[^>]+>", " ", desc).strip()
        salary = ""
        sr = item.get("salaryRange") or {}
        if sr.get("min") and sr.get("max"):
            currency = sr.get("currency", "INR")
            interval = sr.get("interval", "yearly")
            salary = f"{currency} {sr['min']}-{sr['max']}/{interval}"
        jobs.append(Job(
            title=item.get("text", ""),
            company=board_token,
            location=cats.get("location", ""),
            url=item.get("hostedUrl", ""),
            description=desc[:6000],
            source="lever",
            salary=salary,
        ))
    return jobs


def fetch_ashby(company_name: str) -> list[Job]:
    """Ashby public job board API — returns all jobs in one response."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company_name}?includeCompensation=true"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        if resp.status_code != 200:
            return []
    except Exception:
        return []
    jobs = []
    for item in resp.json().get("jobs", []):
        if not item.get("isListed", True):
            continue
        desc = item.get("descriptionPlain", "") or item.get("descriptionHtml", "")
        if desc and "<" in desc:
            desc = html_mod.unescape(desc)
            desc = re.sub(r"<[^>]+>", " ", desc).strip()
        salary = ""
        comp = item.get("compensation", {})
        if comp.get("compensationTierSummary"):
            salary = comp["compensationTierSummary"]
        jobs.append(Job(
            title=item.get("title", ""),
            company=company_name,
            location=item.get("location", ""),
            url=item.get("jobUrl", ""),
            description=(desc or "")[:6000],
            source="ashby",
            salary=salary,
        ))
    return jobs


def fetch_workday(tenant: str, dc: str, site: str) -> list[Job]:
    """Workday CXS API — paginated, max 20 per page."""
    base = f"https://{tenant}.{dc}.myworkdayjobs.com"
    api_base = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    jobs = []
    offset = 0
    max_pages = 10  # cap to avoid infinite loops

    for _ in range(max_pages):
        payload = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""}
        try:
            resp = requests.post(
                api_base, json=payload,
                headers={**_headers(), "Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code != 200:
                break
            time.sleep(1.5)
        except Exception:
            break

        data = resp.json()
        postings = data.get("jobPostings", [])
        total = data.get("total", 0)

        for item in postings:
            external_path = item.get("externalPath", "")
            job_url = f"{base}/en-US{external_path}" if external_path else ""
            # Fetch individual job detail for description
            desc = ""
            if external_path:
                try:
                    detail_resp = requests.get(
                        f"{base}/wday/cxs/{tenant}/{site}{external_path}",
                        headers={**_headers(), "Content-Type": "application/json"},
                        timeout=20,
                    )
                    if detail_resp.status_code == 200:
                        detail_data = detail_resp.json()
                        desc = detail_data.get("jobPostingInfo", {}).get("jobDescription", "")
                        if desc:
                            desc = html_mod.unescape(desc)
                            desc = re.sub(r"<[^>]+>", " ", desc).strip()
                        if not job_url:
                            job_url = detail_data.get("jobPostingInfo", {}).get("externalPath", "")
                except Exception:
                    pass
                time.sleep(1.5)

            jobs.append(Job(
                title=item.get("title", ""),
                company=tenant,
                location=item.get("locationsText", ""),
                url=job_url,
                description=desc[:6000] if desc else item.get("bulletFields", [""])[0],
                source="workday",
            ))

        offset += 20
        if offset >= total:
            break

    return jobs


def fetch_smartrecruiters(company_id: str, max_results: int = 50) -> list[Job]:
    """SmartRecruiters API — paginated listing + per-posting detail calls."""
    base_url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
    jobs = []
    offset = 0
    limit = 100

    while len(jobs) < max_results:
        try:
            resp = requests.get(
                f"{base_url}?limit={limit}&offset={offset}",
                headers=_headers(), timeout=30,
            )
            if resp.status_code != 200:
                break
            time.sleep(DELAY)
        except Exception:
            break

        data = resp.json()
        content = data.get("content", [])
        if not content:
            break

        for item in content:
            posting_id = item.get("id", "")
            title = item.get("name", "")
            if not title:
                continue
            location = ""
            loc_list = item.get("location", {})
            if isinstance(loc_list, dict):
                location = loc_list.get("city", "") or loc_list.get("name", "")
            job_url = item.get("ref", "")
            # Fetch detail for description
            desc = ""
            if posting_id:
                try:
                    detail_resp = requests.get(
                        f"{base_url}/{posting_id}",
                        headers=_headers(), timeout=20,
                    )
                    if detail_resp.status_code == 200:
                        detail = detail_resp.json()
                        desc = detail.get("description", "")
                        if desc:
                            desc = html_mod.unescape(desc)
                            desc = re.sub(r"<[^>]+>", " ", desc).strip()
                except Exception:
                    pass
                time.sleep(DELAY)

            jobs.append(Job(
                title=title,
                company=company_id,
                location=location,
                url=job_url,
                description=desc[:6000],
                source="smartrecruiters",
            ))
            if len(jobs) >= max_results:
                break

        offset += limit
        total = data.get("totalFound", 0)
        if offset >= total:
            break

    return jobs


def fetch_rippling(slug: str) -> list[Job]:
    """Rippling ATS public job board API."""
    url = f"https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        if resp.status_code != 200:
            return []
    except Exception:
        return []
    jobs = []
    for item in resp.json():
        title = item.get("name", "")
        if not title:
            continue
        job_url = item.get("url", "")
        loc_obj = item.get("workLocation", {})
        location = loc_obj.get("label", "") if isinstance(loc_obj, dict) else ""
        desc = item.get("description", "") or item.get("descriptionPlain", "")
        if desc:
            desc = html_mod.unescape(desc)
            desc = re.sub(r"<[^>]+>", " ", desc).strip()
        jobs.append(Job(
            title=title,
            company=slug,
            location=location,
            url=job_url,
            description=(desc or "")[:6000],
            source="rippling",
        ))
    return jobs


def fetch_keka(subdomain: str, max_results: int = 20) -> list[Job]:
    """Best-effort scraper for public Keka careers boards (e.g. SurveySparrow
    runs one at surveysparrow.keka.com/careers). Keka boards are JS-rendered,
    so this uses headless Playwright rather than guessing at an internal API."""
    url = f"https://{subdomain}.keka.com/careers"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_context().new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            card_selectors = "a[href*='jobdetails'], .job-list-item, .jobs-list-item, .career-job-card"
            page.wait_for_selector(card_selectors, timeout=10000)
            cards = page.query_selector_all(card_selectors)
            jobs = []
            for card in cards[:max_results]:
                title = card.inner_text().strip().split("\n")[0]
                if not title:
                    continue
                href = card.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = f"https://{subdomain}.keka.com/{href.lstrip('/')}"
                jobs.append(Job(
                    title=title,
                    company=subdomain,
                    location="",
                    url=href or url,
                    description=card.inner_text()[:2000],
                    source="keka",
                ))
            browser.close()
            return jobs
    except Exception:
        return []


def fetch_jsonld(careers_url: str) -> list[Job]:
    """Generic JSON-LD JobPosting extraction from any career page."""
    from .ats_detect import parse_jsonld_jobs
    try:
        resp = requests.get(careers_url, headers=_headers(), timeout=20)
        if resp.status_code != 200:
            return []
        time.sleep(DELAY)
    except Exception:
        return []

    items = parse_jsonld_jobs(resp.text)
    jobs = []
    for item in items:
        title = item.get("title", "")
        if not title:
            continue
        jobs.append(Job(
            title=title,
            company=item.get("hiringOrganization", ""),
            location=item.get("location", ""),
            url=item.get("url", careers_url),
            description=item.get("description", "")[:6000],
            source="jsonld",
            posted_at=item.get("datePosted", ""),
            salary=item.get("baseSalary", ""),
        ))
    return jobs


def fetch_nextdata(careers_url: str) -> list[Job]:
    """Generic __NEXT_DATA__ extraction from Next.js career pages."""
    from .ats_detect import parse_nextdata_jobs
    try:
        resp = requests.get(careers_url, headers=_headers(), timeout=20)
        if resp.status_code != 200:
            return []
        time.sleep(DELAY)
    except Exception:
        return []

    items = parse_nextdata_jobs(resp.text)
    jobs = []
    for item in items:
        title = item.get("title", "")
        if not title:
            continue
        jobs.append(Job(
            title=title,
            company=item.get("company", ""),
            location=item.get("location", ""),
            url=item.get("url", careers_url),
            description=item.get("description", "")[:6000],
            source="nextdata",
        ))
    return jobs


def infer_experience_level(title: str, description: str) -> str:
    """Infer experience level from job title and description text.

    Order of checks: explicit fresher/intern wording first, then numeric
    year ranges ("0-1 yrs", "1-2 years", "2-3 yrs of experience" — using the
    midpoint of the range), then single seniority keywords, then a single
    year figure ("3+ years experience").
    """
    text = f"{title} {description}".lower()
    # Some ATS pages (e.g. Lever) render multi-digit numbers with a stray space
    # between digits ("1 0 years" instead of "10 years"), which corrupts every
    # regex below — "6 to 1 0 years" was misread as "0 years" (fresher) instead
    # of 10. Collapse "<digit> <digit>" sequences back together first.
    text = re.sub(r"(?<=\d) (?=\d\b)", "", text)
    if re.search(r"\b(intern(?:ship)?|trainee|fresher|entry.?level|no experience|graduate program)\b", text):
        return "fresher"

    # Range like "0-1", "1-2", "2-3", "3-5 years" — most India job postings
    # phrase experience this way, so check ranges before single-number.
    range_m = re.search(r"(\d+)\s*(?:-|to|\+?\s*–)\s*(\d+)\s*\+?\s*(?:years?|yrs?)", text)
    if range_m:
        lo, hi = int(range_m.group(1)), int(range_m.group(2))
        if hi <= 1:
            return "fresher"
        avg = (lo + hi) / 2
        if avg <= 2:
            return "junior"
        if avg <= 5:
            return "mid"
        return "senior"

    if re.search(r"\b0\s*\+?\s*(?:years?|yrs?)\b", text):
        return "fresher"
    if re.search(r"\b(junior|jr\.)\b", text):
        return "junior"
    if re.search(r"\b(senior|sr\.|lead|staff|principal|architect)\b", text):
        return "senior"

    yrs = re.search(r"(\d+)\s*\+?\s*(?:years?|yrs?)\s*(?:of)?\s*(?:experience)?", text)
    if yrs:
        y = int(yrs.group(1))
        if y == 0:
            return "fresher"
        if y <= 2:
            return "junior"
        if y <= 5:
            return "mid"
        return "senior"
    return ""


def fetch_ats_jobs(platform: str, params: dict) -> list[Job]:
    """Dispatch to the correct ATS fetcher based on platform name."""
    if platform == "greenhouse":
        return fetch_greenhouse(params.get("board_token", ""))
    elif platform == "lever":
        return fetch_lever(params.get("site_slug", ""))
    elif platform == "ashby":
        return fetch_ashby(params.get("company_name", ""))
    elif platform == "workday":
        return fetch_workday(params.get("tenant", ""), params.get("dc", ""), params.get("site", ""))
    elif platform == "smartrecruiters":
        return fetch_smartrecruiters(params.get("company_id", ""))
    elif platform == "rippling":
        return fetch_rippling(params.get("slug", ""))
    elif platform == "keka":
        return fetch_keka(params.get("subdomain", ""))
    return []
