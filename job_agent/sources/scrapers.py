"""No-API job sources — scrape public listing pages directly.

Polite scraping: rotating headers, retry-with-backoff on block responses,
delays between calls. Markup changes over time; every parser fails soft and
returns [] on error (except BlockedError, which callers can log distinctly).
"""
import random
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

from ..models import Job

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]
DELAY = 0.5  # base seconds between requests
MAX_RETRIES = 2  # retries on 403/429 before raising BlockedError
HYDRATE_LIMIT = 12  # only fetch full descriptions for the top N cards per source call
LIST_TIMEOUT = 15
DETAIL_TIMEOUT = 10


class BlockedError(Exception):
    """Raised when a site consistently returns 403/429 after retries."""


def _headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _get(url: str, _retry: int = 0) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=_headers(), timeout=LIST_TIMEOUT)
    except Exception:
        return None
    if resp.status_code in (403, 429):
        if _retry < MAX_RETRIES:
            time.sleep(DELAY * (2 ** _retry) + random.uniform(0, 1))
            return _get(url, _retry + 1)
        raise BlockedError(f"blocked (HTTP {resp.status_code}) after {MAX_RETRIES} retries")
    if resp.status_code != 200:
        return None
    time.sleep(DELAY)
    return BeautifulSoup(resp.text, "html.parser")


def _q(s: str) -> str:
    return urllib.parse.quote_plus(s)


def _full_description(url: str, selectors: list[str], max_len: int = 6000) -> str:
    """Best-effort fetch of a job's own detail page for the real JD (not just
    the card snippet). Returns '' on any failure so callers can fall back."""
    if not url:
        return ""
    try:
        soup = _get(url)
    except BlockedError:
        return ""
    if not soup:
        return ""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(" ", strip=True)
            if len(text) > 200:
                return text[:max_len]
    body = soup.select_one("body")
    return body.get_text(" ", strip=True)[:max_len] if body else ""


def _hydrate(jobs: list[Job], selectors: list[str], limit: int = HYDRATE_LIMIT) -> list[Job]:
    """Replace card snippets with full descriptions for the top `limit` jobs."""
    for job in jobs[:limit]:
        full = _full_description(job.url, selectors)
        if full:
            job.description = full
    return jobs


# ---------------------------------------------------------------- SimplyHired
def scrape_simplyhired(query: str, location: str, max_results: int = 20) -> list[Job]:
    """SimplyHired sits behind a Cloudflare JS challenge that a plain
    `requests` call can never pass (no JS execution), so this drives headless
    Playwright the same way scrape_naukri does."""
    jobs = []
    seen = set()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=random.choice(USER_AGENTS))
            page_obj = context.new_page()
            page = 1
            while len(jobs) < max_results:
                url = f"https://www.simplyhired.co.in/search?q={_q(query)}&l={_q(location)}"
                if page > 1:
                    url += f"&pn={page}"
                try:
                    page_obj.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page_obj.wait_for_selector("a[href^='/job/']", timeout=8000)
                except Exception:
                    break
                soup = BeautifulSoup(page_obj.content(), "html.parser")
                before = len(jobs)
                for a in soup.select("a[href^='/job/']"):
                    title = a.get_text(strip=True)
                    if not title or len(title) < 3:
                        continue
                    job_url = "https://www.simplyhired.co.in" + a["href"].split("?")[0]
                    if job_url in seen:
                        continue
                    seen.add(job_url)
                    card = a.find_parent("li") or a.find_parent("div")
                    company = location_txt = snippet = ""
                    apply_type = "apply_now"
                    if card:
                        comp = card.select_one("[data-testid='companyName'], .companyName, span")
                        company = comp.get_text(strip=True) if comp else ""
                        loc = card.select_one("[data-testid='searchSerpJobLocation'], .jobLocation")
                        location_txt = loc.get_text(strip=True) if loc else location
                        card_txt = card.get_text(" ", strip=True)
                        snippet = card_txt[:1500]
                        # Require an explicit child element with exact text 'Quick apply'
                        for tag in card.find_all(["div", "span", "p", "button"]):
                            if tag.get_text(strip=True).lower() == "quick apply":
                                apply_type = "quick_apply"
                                break
                    jobs.append(Job(
                        title=title, company=company, location=location_txt or location,
                        url=job_url, description=snippet, source="simplyhired",
                        apply_type=apply_type
                    ))
                    if len(jobs) >= max_results:
                        break
                if len(jobs) == before:
                    break
                page += 1
                time.sleep(DELAY)

            for job in jobs[:HYDRATE_LIMIT]:
                if not job.url:
                    continue
                try:
                    detail = context.new_page()
                    detail.goto(job.url, wait_until="domcontentloaded", timeout=DETAIL_TIMEOUT * 1000)
                    dsoup = BeautifulSoup(detail.content(), "html.parser")
                    
                    # Decompose sidebar (e.g. 'Our most similar jobs' widget)
                    for side in dsoup.select("aside, [data-testid='similarJobs'], .similar-jobs, #similar-jobs"):
                        side.decompose()
                        
                    main_header = dsoup.select_one("[data-testid='viewJobHeader'], header, .viewjob-header, main") or dsoup
                    qa_btn = main_header.select_one("[data-testid='quickApplyButton'], button[data-testid*='quickApply']")
                    if qa_btn:
                        job.apply_type = "quick_apply"
                    else:
                        is_qa = False
                        for tag in main_header.find_all(["button", "span", "div", "a"]):
                            if tag.get_text(strip=True).lower() == "quick apply":
                                is_qa = True
                                break
                        if is_qa:
                            job.apply_type = "quick_apply"
                        elif not getattr(job, "apply_type", ""):
                            job.apply_type = "apply_now"

                    for sel in ["[data-testid='viewJobBodyJobFullDescriptionContent']",
                                "#job-details", ".viewjob-description", "article"]:
                        el = dsoup.select_one(sel)
                        if el:
                            text = el.get_text(" ", strip=True)
                            if len(text) > 200:
                                job.description = text[:6000]
                                break
                    detail.close()
                except Exception:
                    pass
            browser.close()
    except Exception:
        return _dedupe(jobs)
    return _dedupe(jobs)


# ------------------------------------------------- LinkedIn (public guest API)
def scrape_linkedin(query: str, location: str, max_results: int = 25) -> list[Job]:
    """LinkedIn's public jobs-guest endpoint — no login, returns HTML cards."""
    jobs = []
    seen = set()
    page_size = 25
    for start in range(0, max_results, page_size):
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
               f"?keywords={_q(query)}&location={_q(location)}&start={start}")
        soup = _get(url)
        if not soup:
            break
        before = len(jobs)
        for card in soup.select("div.base-search-card, li"):
            title_el = card.select_one("h3.base-search-card__title, h3")
            link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
            if not (title_el and link_el):
                continue
            job_url = link_el["href"].split("?")[0]
            if job_url in seen:
                continue
            seen.add(job_url)
            company_el = card.select_one("h4.base-search-card__subtitle, h4")
            loc_el = card.select_one("span.job-search-card__location")
            date_el = card.select_one("time")
            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                location=loc_el.get_text(strip=True) if loc_el else location,
                url=job_url,
                description=card.get_text(" ", strip=True)[:1500],
                source="linkedin",
                posted_at=date_el.get("datetime", "") if date_el else "",
            ))
            if len(jobs) >= max_results:
                break
        if len(jobs) == before:
            break
    jobs = _hydrate_linkedin(jobs)
    return _dedupe(jobs)


_LINKEDIN_DESC_SELECTORS = [
    "div.description__text", "div.show-more-less-html__markup", "section.description",
]


def _unwrap_redirect(url: str) -> str:
    """LinkedIn's signed-out apply flow routes through a login-gate URL
    (e.g. /signup/cold-join or /authwall) carrying the real destination in a
    'session_redirect' query param. Unwrap it so we land on the company's own
    ATS/careers page instead of a LinkedIn login screen."""
    parsed = urllib.parse.urlparse(url)
    if "linkedin.com" not in parsed.netloc:
        return url
    qs = urllib.parse.parse_qs(parsed.query)
    target = qs.get("session_redirect", [""])[0]
    if target and "linkedin.com" not in urllib.parse.urlparse(target).netloc:
        return target
    return ""


def _external_apply_url(soup) -> str:
    """LinkedIn guest job pages often route "Apply" off-site to the company's
    own ATS/careers page, which usually has the real full JD instead of (or in
    addition to) LinkedIn's own snippet."""
    code_el = soup.find("code", id="applyUrl")
    if code_el:
        m = re.search(r'"(https?://[^"]+)"', code_el.decode_contents())
        if m:
            return _unwrap_redirect(m.group(1)) or m.group(1)
    a = soup.select_one("a.apply-button, a[data-tracking-control-name*='apply']")
    if a:
        href = a.get("href", "")
        if href.startswith("http"):
            if "linkedin.com" not in href:
                return href
            return _unwrap_redirect(href)
    return ""


def _hydrate_linkedin(jobs: list[Job], limit: int = HYDRATE_LIMIT) -> list[Job]:
    """Fetch each job's own LinkedIn detail page for the full description,
    then follow an external apply link (if present) and prefer that page's
    text when it's more complete than what LinkedIn shows."""
    for job in jobs[:limit]:
        if not job.url:
            continue
        time.sleep(DELAY + random.uniform(0, 1))
        try:
            soup = _get(job.url)
        except BlockedError:
            continue
        if not soup:
            continue

        full = ""
        for sel in _LINKEDIN_DESC_SELECTORS:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(" ", strip=True)
                if len(text) > 200:
                    full = text[:6000]
                    break

        apply_url = _external_apply_url(soup)
        if apply_url:
            job.company_careers_url = apply_url
            time.sleep(DELAY + random.uniform(0, 1))
            try:
                ext_soup = _get(apply_url)
            except BlockedError:
                ext_soup = None
            if ext_soup:
                body = ext_soup.select_one("main, article") or ext_soup.select_one("body")
                ext_text = body.get_text(" ", strip=True)[:6000] if body else ""
                if len(ext_text) > len(full):
                    full = ext_text

        if full:
            job.description = full
    return jobs


# ------------------------------------------------------------------- TimesJobs
def scrape_timesjobs(query: str, location: str, max_results: int = 20) -> list[Job]:
    """TimesJobs was rebuilt as a client-rendered Next.js app — the server
    response is just a loading shell with no job markup, so a plain
    `requests` fetch always sees zero cards. Drive headless Playwright
    instead, same as scrape_naukri/scrape_simplyhired."""
    jobs = []
    seen = set()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=random.choice(USER_AGENTS))
            page_obj = context.new_page()
            for page in range(1, max(2, (max_results // 25) + 3)):
                url = ("https://www.timesjobs.com/candidate/job-search.html?searchType=personalizedSearch"
                       f"&from=submit&txtKeywords={_q(query)}&txtLocation={_q(location)}"
                       f"&sequence={page}&startPage=1")
                try:
                    page_obj.goto(url, wait_until="domcontentloaded", timeout=25000)
                    page_obj.wait_for_selector("div.srp-card h2", timeout=15000)
                    page_obj.wait_for_timeout(500)
                except Exception:
                    break
                soup = BeautifulSoup(page_obj.content(), "html.parser")
                before = len(jobs)
                for card in soup.select("div.srp-card"):
                    title_el = card.select_one("h2")
                    link_el = card.select_one("a[href*='job-detail']")
                    if not title_el or not link_el:
                        continue
                    job_url = link_el.get("href", "")
                    if not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    comp_el = card.select_one(".text-xs.text-gray-400 span")
                    jobs.append(Job(
                        title=title_el.get_text(strip=True),
                        company=comp_el.get_text(strip=True) if comp_el else "",
                        location=location,
                        url=job_url,
                        description=card.get_text(" ", strip=True)[:1500],
                        source="timesjobs",
                    ))
                    if len(jobs) >= max_results:
                        break
                if len(jobs) == before:
                    break
                time.sleep(DELAY)

            for job in jobs[:HYDRATE_LIMIT]:
                if not job.url:
                    continue
                try:
                    detail = context.new_page()
                    detail.goto(job.url, wait_until="domcontentloaded", timeout=DETAIL_TIMEOUT * 1000)
                    dsoup = BeautifulSoup(detail.content(), "html.parser")
                    for sel in [".job-description", "#jobDescription", "article", ".rtd-content"]:
                        el = dsoup.select_one(sel)
                        if el:
                            text = el.get_text(" ", strip=True)
                            if len(text) > 200:
                                job.description = text[:6000]
                                break
                    detail.close()
                except Exception:
                    pass
            browser.close()
    except Exception:
        return _dedupe(jobs)
    return _dedupe(jobs)


# ------------------------------------------------------- Naukri (needs browser)
def scrape_naukri(query: str, location: str, max_results: int = 20) -> list[Job]:
    """Naukri is JS-rendered — uses headless Playwright."""
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    url = f"https://www.naukri.com/{slug(query)}-jobs-in-{slug(location)}?sort=r"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=random.choice(USER_AGENTS))
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector(".srp-jobtuple-wrapper, article.jobTuple", timeout=7000)
            cards = page.query_selector_all(".srp-jobtuple-wrapper, article.jobTuple")
            jobs = []
            for card in cards[:max_results]:
                title_el = card.query_selector("a.title")
                if not title_el:
                    continue
                comp_el = card.query_selector(".comp-name, a.comp-name, a.subTitle")
                loc_el = card.query_selector(".locWdth, .loc span, .location span")
                
                date_el = card.query_selector("span[class*='date'], span[class*='post-day'], span[class*='job-post-day']")
                posted_at = date_el.inner_text().strip() if date_el else ""

                jobs.append(Job(
                    title=title_el.inner_text().strip(),
                    company=comp_el.inner_text().strip() if comp_el else "",
                    location=loc_el.inner_text().strip() if loc_el else location,
                    url=title_el.get_attribute("href") or "",
                    description=card.inner_text()[:1500],
                    source="naukri",
                    posted_at=posted_at,
                ))
            # Hydrate top N with full JD from the detail page, same browser session.
            for job in jobs[:HYDRATE_LIMIT]:
                if not job.url:
                    continue
                try:
                    detail = context.new_page()
                    detail.goto(job.url, wait_until="domcontentloaded", timeout=DETAIL_TIMEOUT * 1000)
                    el = detail.query_selector(".styles_JDC__dang-inner-html__h0K4t, .job-desc, section.job-desc")
                    if el:
                        text = el.inner_text().strip()
                        if len(text) > 200:
                            job.description = text[:6000]
                    detail.close()
                except Exception:
                    pass
            browser.close()
            return _dedupe(jobs)
    except Exception as e:
        raise e

def _dedupe(jobs: list[Job]) -> list[Job]:
    seen, out = set(), []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            out.append(j)
    return out
