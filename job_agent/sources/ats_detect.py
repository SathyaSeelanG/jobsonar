"""ATS platform auto-detection.

Given a careers page URL or HTML content, detect which ATS (Applicant Tracking
System) the company uses and return the platform name + token/slug needed to
call that ATS's public job API.

Usage:
    platform, params = detect_ats(html_content, careers_url)
    # platform = "greenhouse", params = {"board_token": "stripetech"}
"""
import re
import time

import requests

from .scrapers import _headers, DELAY


# Subdomains that turn up on careers pages as CDN, asset or docs hosts and are
# never a tenant slug. Without this, CoreStack's page — which links
# files.freshteam.com for an attachment — was attributed to the Freshteam tenant
# "files", and any such false positive short-circuits the signature table for
# that company because detect_ats_from_html returns the first match.
_NOT_A_TENANT = (r"(?!(?:www|files|assets?|static|cdn|img|images|media|video|s3"
                 r"|api|app|help|support|docs|blog|status|mail|go|link)\b)")

# (platform_name, regex_pattern, param_key)
#
# Order matters: detect_ats_from_html returns the FIRST match, so every platform
# fetch_ats_jobs() can actually fetch is listed before the detection-only tail.
# A careers page that embeds two ATS widgets then resolves to the one we can
# read rather than the one we can only name.
ATS_SIGNATURES = [
    # --- fetchable: a public JSON/XML feed exists and ats.py implements it ---
    # The embedded-iframe form carries the board token in the query string, so
    # it has to be tried before the generic path form — otherwise the path
    # segment "job_board" is captured as the token and the fetch 404s.
    ("greenhouse",      r"boards\.greenhouse\.io/embed/job_board\?for=([\w-]+)",            "board_token"),
    # Greenhouse moved boards to job-boards.greenhouse.io; the old
    # boards.greenhouse.io host is still served, so match either.
    ("greenhouse",      r"(?:job-)?boards\.greenhouse\.io/(?:embed/)?([\w-]+)",             "board_token"),
    ("greenhouse",      r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)",                   "board_token"),
    # Lever runs a separate EU cluster on jobs.eu.lever.co.
    ("lever",           r"jobs\.(?:eu\.)?lever\.co/([\w-]+)",                               "site_slug"),
    ("ashby",           r"jobs\.ashbyhq\.com/([\w.-]+)",                                    "company_name"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)",                 "company_id"),
    ("workday",         r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/([\w-]+)",                  "tenant_dc_site"),
    ("rippling",        r"ats\.rippling\.com/([\w-]+)/jobs",                                "slug"),
    # The (?<![\w.-]) guard on every subdomain pattern below stops re.search
    # from starting mid-label: without it "apply.workable.com" matches from
    # "pply" and the captured slug is garbage, and a (?!www\.) lookahead alone
    # is sidestepped the same way. _NOT_A_TENANT then rules out asset hosts.
    ("recruitee",       rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.recruitee\.com/(?:o|offers|jobs)",  "company"),
    ("personio",        rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.jobs\.personio\.(?:com|de)",        "company"),
    ("breezy",          rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.breezy\.hr",                        "company"),
    ("workable",        r"apply\.workable\.com/(?!api/)([\w-]+)",                                  "company"),
    ("workable",        rf"(?<![\w.-])(?!apply\b){_NOT_A_TENANT}([\w-]+)\.workable\.com",          "company"),
    ("keka",            rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.keka\.com/careers",                 "subdomain"),
    # Envelope confirmed, record fields unverified — see fetch_bamboohr.
    ("bamboohr",        rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.bamboohr\.com/careers",             "company"),

    # --- detection-only: no guessable public feed, so fetch_ats_jobs returns []
    # and the watchlist cascade falls through to JSON-LD / rendered-HTML
    # extraction. Probed and confirmed closed: Freshteam /api/job_postings ->
    # 404/503, Darwinbox /ms/candidate/careers/getJobs -> 404, PeopleStrong
    # /api/jobs -> 403, Zoho Recruit portal -> HTML only. They are listed so
    # scrape-report can attribute a company to its ATS instead of "unknown".
    ("zohorecruit",     rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.zohorecruit\.(?:com|in|eu)",                 "company"),
    ("darwinbox",       rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.darwinbox\.(?:com|in)",                      "company"),
    ("freshteam",       rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.freshteam\.com",                             "company"),
    ("oraclecloud",     rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.oraclecloud\.com/hcmUI/CandidateExperience", "company"),
    ("successfactors",  rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.(?:successfactors|sapsf)\.(?:com|eu)",       "company"),
    ("taleo",           rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.taleo\.net",                                 "company"),
    ("peoplestrong",    rf"(?<![\w.-]){_NOT_A_TENANT}([\w-]+)\.peoplestrong\.com",                          "company"),
]

# Platforms recognised by ATS_SIGNATURES that fetch_ats_jobs() cannot fetch.
# Kept next to the table so the two never drift: docs/SOURCES.md and
# scrape-report both read this instead of hard-coding a list.
DETECTION_ONLY = frozenset({
    "zohorecruit", "darwinbox", "freshteam", "oraclecloud",
    "successfactors", "taleo", "peoplestrong",
})


def detect_ats_from_html(html: str, careers_url: str = "") -> tuple[str, dict] | None:
    """Detect which ATS a careers page uses by scanning HTML + URL.

    Returns (platform_name, {token_key: token_value, ...}) or None.
    """
    search_text = f"{html} {careers_url}"

    for platform, pattern, token_key in ATS_SIGNATURES:
        m = re.search(pattern, search_text)
        if m:
            groups = m.groups()
            if platform == "workday":
                return platform, {"tenant": groups[0], "dc": groups[1], "site": groups[2]}
            else:
                return platform, {token_key: groups[0]}

    return None


def detect_ats_from_url(url: str) -> tuple[str, dict] | None:
    """Convenience: fetch a URL and detect its ATS. Returns None on failure."""
    try:
        resp = requests.get(url, headers=_headers(), timeout=20)
        if resp.status_code != 200:
            return None
        time.sleep(DELAY)
        return detect_ats_from_html(resp.text, url)
    except Exception:
        return None


def parse_jsonld_jobs(html: str) -> list[dict]:
    """Extract JSON-LD JobPosting structured data from HTML.

    Returns a list of dicts, each with keys:
        title, description, url, location, datePosted, employmentType,
        experienceRequirements, baseSalary, hiringOrganization
    """
    import json
    jobs = []
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    ):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue

        items = []
        if isinstance(data, dict):
            if data.get("@type") == "JobPosting":
                items.append(data)
            elif "@graph" in data:
                items.extend(
                    item for item in data["@graph"]
                    if isinstance(item, dict) and item.get("@type") == "JobPosting"
                )
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    items.append(item)

        for item in items:
            loc = item.get("jobLocation", {})
            if isinstance(loc, dict) and loc.get("@type") == "Place":
                addr = loc.get("address", {})
                location = f"{addr.get('addressLocality', '')}, {addr.get('addressCountry', '')}"
            elif isinstance(loc, dict):
                location = loc.get("name", "")
            else:
                location = ""

            org = item.get("hiringOrganization", {})
            salary_obj = item.get("baseSalary", {})
            salary = ""
            if salary_obj:
                val = salary_obj.get("value", {})
                salary = f"{salary_obj.get('currency', '')} {val.get('value', '')} {val.get('unitText', '')}".strip()

            desc = item.get("description", "")
            if isinstance(desc, str):
                import html as html_mod
                desc = html_mod.unescape(desc)
                desc = re.sub(r"<[^>]+>", " ", desc).strip()

            jobs.append({
                "title": item.get("title", ""),
                "description": desc[:6000],
                "url": item.get("url", item.get("sameAs", "")),
                "location": location,
                "datePosted": item.get("datePosted", ""),
                "employmentType": item.get("employmentType", ""),
                "experienceRequirements": item.get("experienceRequirements", ""),
                "baseSalary": salary,
                "hiringOrganization": org.get("name", "") if isinstance(org, dict) else "",
            })

    return jobs


def parse_nextdata_jobs(html: str) -> list[dict]:
    """Extract job listings from __NEXT_DATA__ JSON in Next.js career pages.

    Returns a list of dicts with keys: title, url, description, location, company.
    """
    import json
    m = re.search(r'<script\s+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return []

    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return []

    jobs = []
    props = data.get("props", {}).get("pageProps", {})

    # Try known data paths
    job_lists = []
    for key in ("jobPosts", "jobPostings", "jobs", "openings", "positions", "data"):
        val = props.get(key)
        if isinstance(val, list):
            job_lists.append(val)
        elif isinstance(val, dict):
            # Greenhouse-style: {"data": [...]}
            for subkey in ("data", "jobs", "jobPostings"):
                subval = val.get(subkey)
                if isinstance(subval, list):
                    job_lists.append(subval)
                elif isinstance(subval, dict):
                    for sub2 in ("data",):
                        sub2val = subval.get(sub2)
                        if isinstance(sub2val, list):
                            job_lists.append(sub2val)

    # Nested under company
    company_data = props.get("company", {})
    if isinstance(company_data, dict):
        for key in ("jobPostings", "jobs", "openings"):
            val = company_data.get(key)
            if isinstance(val, list):
                job_lists.append(val)

    for job_list in job_lists:
        for item in job_list:
            if not isinstance(item, dict):
                continue
            title = item.get("title", item.get("name", item.get("text", "")))
            if not title:
                continue
            url = item.get("absolute_url", item.get("hostedUrl", item.get("url", item.get("jobUrl", ""))))
            desc = item.get("content", item.get("description", item.get("descriptionPlain", "")))
            if isinstance(desc, str):
                import html as html_mod
                desc = html_mod.unescape(desc)
                desc = re.sub(r"<[^>]+>", " ", desc).strip()
            loc = item.get("location", "")
            if isinstance(loc, dict):
                loc = loc.get("name", "")
            company = item.get("company", item.get("hiringOrganization", ""))
            if isinstance(company, dict):
                company = company.get("name", "")

            jobs.append({
                "title": title,
                "url": url,
                "description": (desc or "")[:6000],
                "location": str(loc),
                "company": str(company),
            })

    return jobs


def extract_jobs_from_html(html: str, careers_url: str = "") -> list[dict]:
    """Generic fallback: extract job cards from HTML by common patterns.

    Tries JSON-LD first, then __NEXT_DATA__, then HTML link detection.
    """
    # 1. JSON-LD (most reliable structured data)
    jobs = parse_jsonld_jobs(html)
    if jobs:
        return jobs

    # 2. __NEXT_DATA__ (Next.js SPAs)
    jobs = parse_nextdata_jobs(html)
    if jobs:
        return jobs

    # 3. HTML link-based extraction (heuristic)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_urls = set()

    JOB_LINK_RE = re.compile(r"/jobs?/|/careers?/|/apply/|/posting/|/requisition/", re.I)
    NOISE_RE = re.compile(r"\d+\s*open positions?.*$|more details$", re.I)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Anchors often wrap a title plus badges ("Junior Developer", "1 open
        # position", "Calicut, India", a date) as separate child text nodes.
        # get_text(strip=True) joins them with no separator at all, producing
        # glued garbage like "Junior Developer1\n  open positions...". Take
        # only the first text line, which is consistently the job title.
        first_line = next((s.strip() for s in a.stripped_strings), "")
        text = NOISE_RE.sub("", first_line).strip()
        if not text or len(text) < 4:
            continue
        if not JOB_LINK_RE.search(href):
            continue
        full_url = href if href.startswith("http") else ""
        if not full_url and careers_url:
            import urllib.parse
            full_url = urllib.parse.urljoin(careers_url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Try to get description from parent card
        card = a.find_parent(["li", "div", "article", "tr"])
        desc = card.get_text(" ", strip=True)[:2000] if card else ""

        jobs.append({
            "title": text,
            "url": full_url,
            "description": desc,
            "location": "",
            "company": "",
        })

    return jobs
