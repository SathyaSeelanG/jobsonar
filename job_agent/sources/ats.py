"""Direct ATS feeds — Greenhouse & Lever public job-board APIs (no auth needed),
plus Ashby, Workday, SmartRecruiters, Rippling, Recruitee, Personio, Breezy,
Workable, and best-effort Keka/BambooHR scrapers.
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


def _workday_posted(raw: str) -> str:
    """Turn Workday's relative postedOn text into an ISO date.

    Workday sends no timestamp — only prose like "Posted Today", "Posted
    Yesterday", "Posted 5 Days Ago" or "Posted 30+ Days Ago". Left as-is it
    doesn't parse, so every Workday job took the "no date, can't prove it's old"
    branch and was kept forever. Converting here is what lets the freshness gate
    actually act on them. Unrecognised wording yields "" — the old behaviour.
    """
    text = (raw or "").lower()
    if not text:
        return ""
    from datetime import datetime, timedelta, timezone
    if "today" in text or "just posted" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    else:
        match = re.search(r"(\d+)\s*\+?\s*(day|week|month)", text)
        if not match:
            return ""
        count = int(match.group(1))
        days = count * {"day": 1, "week": 7, "month": 30}[match.group(2)]
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def fetch_workday(tenant: str, dc: str, site: str, max_results: int = 50) -> list[Job]:
    """Workday CXS API — paginated, 20 per page, one detail call per posting.

    The detail call is what makes this the most expensive fetcher in the file: a
    tenant with 800 open roles would be 40 listing calls plus 800 detail calls.
    max_results caps both, so the cost is bounded by max_results_per_query the
    same way every other fetcher is.
    """
    base = f"https://{tenant}.{dc}.myworkdayjobs.com"
    api_base = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    jobs = []
    offset = 0
    total = None
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
            time.sleep(DELAY)
        except Exception:
            break

        try:
            data = resp.json()
        except Exception:
            break
        postings = data.get("jobPostings", [])
        # Workday reports "total" on the first page only; every later page sends
        # 0. Re-reading it each pass made "offset >= total" true from page 2
        # onwards, so this used to stop at 40 postings no matter how many the
        # tenant had. Capture it once.
        if total is None:
            total = data.get("total") or 0
        if not postings:
            break

        for item in postings:
            if len(jobs) >= max_results:
                break
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
                time.sleep(DELAY)

            jobs.append(Job(
                title=item.get("title", ""),
                company=tenant,
                location=item.get("locationsText", ""),
                url=job_url,
                description=desc[:6000] if desc else item.get("bulletFields", [""])[0],
                source="workday",
                posted_at=_workday_posted(item.get("postedOn", "")),
            ))

        offset += 20
        if len(jobs) >= max_results or offset >= total:
            break

    return jobs


def _sr_description(detail: dict) -> str:
    """Assemble a SmartRecruiters description from its jobAd sections.

    The posting's top-level "description" is always null on this API; the real
    text lives in jobAd.sections as separate companyDescription /
    jobDescription / qualifications / additionalInformation blocks. Reading the
    top-level field meant every SmartRecruiters job arrived with an empty
    description, which zeroes the keyword score and hides the years-of-
    experience wording the fresher gate looks for.
    """
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    if not isinstance(sections, dict):
        return ""
    # Job-specific text first: if the 6000-char cap truncates anything it should
    # be the boilerplate company blurb, not the requirements.
    order = ("jobDescription", "qualifications", "additionalInformation",
             "companyDescription")
    parts = []
    for key in order:
        block = sections.get(key)
        if isinstance(block, dict) and block.get("text"):
            parts.append(_plain(block["text"]))
    return "\n\n".join(p for p in parts if p)


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
            # "ref" is the API endpoint for the posting, not a page a human can
            # open — the detail call is where the real jobs.smartrecruiters.com
            # link lives, so it is only the fallback.
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
                        desc = _sr_description(detail)
                        job_url = detail.get("postingUrl") or job_url
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
                # Already ISO 8601 with a Z suffix, straight from the listing —
                # no extra request needed to date these.
                posted_at=item.get("releasedDate", "") or "",
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
    """Keka careers board JSON API (e.g. surveysparrow.keka.com/careers).

    Keka boards are JS-rendered, so this used to drive headless Playwright and
    scrape the visible cards — a browser launch per board, and the cards carry no
    location, no date and only their own label as a description. The page is
    served by a plain JSON route that returns all of that plus a
    years-of-experience field, so the fresher/junior gate can actually act on
    Keka jobs instead of guessing from a title.

    The route is platform-wide rather than tenant-specific. A subdomain that
    isn't a Keka tenant answers with HTML, which fails the JSON parse and yields
    [] like any other dead board.
    """
    url = f"https://{subdomain}.keka.com/careers/api/jobs/default/active"
    try:
        resp = requests.get(
            url, headers={**_headers(), "Accept": "application/json"}, timeout=25,
        )
        if resp.status_code != 200:
            return []
        items = resp.json()
    except Exception:
        return []
    if not isinstance(items, list):
        return []

    jobs = []
    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue

        names = []
        for loc in item.get("jobLocations") or []:
            if isinstance(loc, dict):
                name = loc.get("city") or loc.get("name") or ""
                if name and name not in names:
                    names.append(name)

        desc = _plain(item.get("description") or "") or (item.get("excerpt") or "")
        # Keka keeps required experience in its own numeric field rather than in
        # the JD prose, so append it as text — infer_experience_level reads the
        # description, and it checks year *ranges* before single figures, so a
        # JD that states its own "3-5 years" still takes precedence over this.
        years = str(item.get("experience") or "").strip()
        if years.isdigit():
            desc = f"{desc}\n\nExperience required: {years} years"

        jobs.append(Job(
            title=title,
            company=subdomain,
            location=", ".join(names),
            url=f"https://{subdomain}.keka.com/careers/jobdetails/{item.get('id', '')}",
            description=desc[:6000],
            source="keka",
            posted_at=item.get("publishedOn", "") or "",
        ))
    return jobs


def _plain(raw: str, limit: int = 6000) -> str:
    """Unescape entities and strip tags from an ATS description blob."""
    if not raw:
        return ""
    return re.sub(r"<[^>]+>", " ", html_mod.unescape(raw)).strip()[:limit]


def _loc_str(value) -> str:
    """Flatten the many shapes an ATS uses for a location into one string.

    Seen in live responses: a bare string, {"city": .., "state": .., "country":
    ..} where each leaf is itself either a string or {"name": ..}, and lists of
    either. Anything unrecognised yields "" rather than a repr of a dict.
    """
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_loc_str(v) for v in value]
        return ", ".join(p for p in parts if p)
    if isinstance(value, dict):
        if value.get("name") and not any(k in value for k in ("city", "region", "state")):
            return str(value["name"]).strip()
        parts = [_loc_str(value.get(k)) for k in ("city", "region", "state", "country")]
        return ", ".join(dict.fromkeys(p for p in parts if p))
    return ""


def fetch_recruitee(company: str, max_results: int = 100) -> list[Job]:
    """Recruitee public offers feed.

    Verified shape: GET https://<company>.recruitee.com/api/offers/ returns
    {"offers": [{title, city, country, location, careers_url,
    careers_apply_url, description, requirements, published_at, remote,
    hybrid, status, salary{min,max,currency,period}, company_name}, ...]}.
    """
    try:
        resp = requests.get(
            f"https://{company}.recruitee.com/api/offers/",
            headers=_headers(), timeout=30,
        )
        if resp.status_code != 200:
            return []
        offers = resp.json().get("offers") or []
        time.sleep(DELAY)
    except Exception:
        return []

    jobs = []
    for item in offers[:max_results]:
        title = item.get("title", "")
        if not title:
            continue
        # Recruitee keeps closed roles in the same feed behind a status flag.
        if (item.get("status") or "published").lower() not in ("published", "internal"):
            continue
        location = _loc_str(item.get("location")) or _loc_str(
            {"city": item.get("city"), "country": item.get("country")})
        if item.get("remote"):
            location = f"{location}, Remote".lstrip(", ")
        salary = ""
        sal = item.get("salary") or {}
        if sal.get("min") and sal.get("max"):
            salary = (f"{sal.get('currency', '')} {sal['min']}-{sal['max']}"
                      f"/{sal.get('period', 'yearly')}").strip()
        # The role body is split across two fields; requirements often carries
        # the years-of-experience line the scorer needs.
        desc = _plain(f"{item.get('description', '')} {item.get('requirements', '')}")
        jobs.append(Job(
            title=title,
            company=item.get("company_name") or company,
            location=location,
            url=item.get("careers_url") or item.get("careers_apply_url", ""),
            description=desc,
            source="recruitee",
            posted_at=item.get("published_at", "") or "",
            salary=salary,
        ))
    return jobs


def fetch_personio(company: str, max_results: int = 100) -> list[Job]:
    """Personio XML job feed.

    Verified shape: GET https://<company>.jobs.personio.de/xml returns
    <workzag-jobs> with repeated <position> children carrying <id>,
    <subcompany>, <office>, <department>, <name>, <employmentType>,
    <seniority>, <yearsOfExperience>, and a <jobDescriptions> list whose
    entries are <jobDescription><name>..</name><value><![CDATA[..]]></value>.
    Some tenants serve the same feed from personio.com.
    """
    import xml.etree.ElementTree as ET

    # Kept as bytes on purpose. Personio serves the feed without a charset in
    # the Content-Type header, so requests falls back to latin-1 and resp.text
    # mojibakes every non-ASCII name ("Köpenicker" -> "KÃ¶penicker"). Handing
    # ET the raw body lets the XML declaration pick the codec.
    raw = b""
    for host in ("de", "com"):
        try:
            resp = requests.get(
                f"https://{company}.jobs.personio.{host}/xml",
                headers=_headers(), timeout=30,
            )
        except Exception:
            continue
        if resp.status_code == 200 and b"<position>" in resp.content:
            raw = resp.content
            time.sleep(DELAY)
            break
    if not raw:
        return []

    try:
        root = ET.fromstring(raw)
    except Exception:
        return []

    jobs = []
    for pos in list(root.iter("position"))[:max_results]:
        title = (pos.findtext("name") or "").strip()
        if not title:
            continue
        pid = (pos.findtext("id") or "").strip()
        parts = []
        for block in pos.iter("jobDescription"):
            heading = (block.findtext("name") or "").strip()
            body = (block.findtext("value") or "").strip()
            if body:
                parts.append(f"{heading}: {body}" if heading else body)
        # The seniority/experience fields live outside the description blocks,
        # so append them — the fresher gate reads years out of the text.
        for field in ("seniority", "yearsOfExperience", "employmentType", "schedule"):
            val = (pos.findtext(field) or "").strip()
            if val:
                parts.append(f"{field}: {val}")
        location = (pos.findtext("office") or "").strip()
        jobs.append(Job(
            title=title,
            company=(pos.findtext("subcompany") or "").strip() or company,
            location=location,
            url=f"https://{company}.jobs.personio.de/job/{pid}" if pid else "",
            description=_plain(" ".join(parts)),
            source="personio",
            posted_at=(pos.findtext("createdAt") or "").strip(),
        ))
    return jobs


def fetch_breezy(company: str, max_results: int = 100) -> list[Job]:
    """Breezy HR public JSON feed.

    Verified shape: GET https://<company>.breezy.hr/json returns a bare JSON
    array of {id, friendly_id, name, url, published_date, type{}, department,
    salary, location{country,state,city}}. The feed carries no description and
    the detail pages expose no JSON-LD, so description is left empty for the
    watchlist hydrator to fill in.
    """
    try:
        resp = requests.get(
            f"https://{company}.breezy.hr/json", headers=_headers(), timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        time.sleep(DELAY)
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    jobs = []
    for item in data[:max_results]:
        title = item.get("name", "")
        if not title:
            continue
        slug = item.get("friendly_id") or item.get("id") or ""
        # The department and employment type are the only text this feed gives
        # us; keep them so the keyword gates have something to match on.
        meta = [_loc_str(item.get("department")), _loc_str(item.get("type"))]
        jobs.append(Job(
            title=title,
            company=company,
            location=_loc_str(item.get("location")),
            url=item.get("url") or (f"https://{company}.breezy.hr/p/{slug}" if slug else ""),
            description=" ".join(m for m in meta if m),
            source="breezy",
            posted_at=item.get("published_date", "") or "",
            salary=item.get("salary", "") if isinstance(item.get("salary"), str) else "",
        ))
    return jobs


def fetch_workable(company: str, max_results: int = 100) -> list[Job]:
    """Workable embedded-widget account feed.

    Verified shape: GET
    https://apply.workable.com/api/v1/widget/accounts/<company>?details=true
    returns {name, description, jobs: [{title, shortcode, url,
    application_url, employment_type, telecommuting, department, published_on,
    country, city, state, education, experience, description}, ...]}.

    details=true is what supplies per-job description text, but it also makes
    the response very large on big accounts (one probed board returned 2219
    jobs / 9.6 MB), so the slice is applied right after parsing.
    """
    data = None
    for qs in ("?details=true", ""):
        try:
            resp = requests.get(
                f"https://apply.workable.com/api/v1/widget/accounts/{company}{qs}",
                headers=_headers(), timeout=60,
            )
        except Exception:
            continue
        if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
            try:
                data = resp.json()
            except Exception:
                data = None
            if data:
                time.sleep(DELAY)
                break
    if not isinstance(data, dict):
        return []

    account = data.get("name") or company
    jobs = []
    for item in (data.get("jobs") or [])[:max_results]:
        title = item.get("title", "")
        if not title:
            continue
        location = _loc_str({"city": item.get("city"), "state": item.get("state"),
                             "country": item.get("country")})
        if not location:
            location = _loc_str(item.get("locations"))
        if item.get("telecommuting"):
            location = f"{location}, Remote".lstrip(", ")
        extra = [item.get("experience") or "", item.get("education") or "",
                 item.get("employment_type") or "", item.get("department") or ""]
        desc = _plain(f"{item.get('description', '')} {' '.join(e for e in extra if e)}")
        short = item.get("shortcode", "")
        jobs.append(Job(
            title=title,
            company=account,
            location=location,
            url=item.get("url") or item.get("application_url")
                or (f"https://apply.workable.com/{company}/j/{short}/" if short else ""),
            description=desc,
            source="workable",
            posted_at=item.get("published_on", "") or "",
        ))
    return jobs


def fetch_bamboohr(company: str, max_results: int = 100) -> list[Job]:
    """BambooHR careers list.

    GET https://<company>.bamboohr.com/careers/list returns {"meta": ..,
    "result": [..]}. The envelope is confirmed but the per-record field names
    are NOT: none of ~190 probed subdomains served a non-empty result array,
    so every field below is read through a list of plausible aliases and the
    fetcher degrades to [] rather than raising. Treat any job it returns as
    unvalidated until a live board with open roles turns up.
    """
    try:
        resp = requests.get(
            f"https://{company}.bamboohr.com/careers/list",
            headers=_headers(), timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        time.sleep(DELAY)
    except Exception:
        return []

    records = data.get("result") if isinstance(data, dict) else data
    if not isinstance(records, list):
        return []

    def pick(rec, *names):
        for n in names:
            v = rec.get(n)
            if v:
                return v
        return ""

    jobs = []
    for item in records[:max_results]:
        if not isinstance(item, dict):
            continue
        title = _loc_str(pick(item, "jobOpeningName", "title", "name"))
        if not title:
            continue
        jid = pick(item, "id", "jobOpeningId", "jobId")
        jobs.append(Job(
            title=title,
            company=company,
            location=_loc_str(pick(item, "location", "locationName", "city")),
            url=pick(item, "url", "jobOpeningShareUrl")
                or (f"https://{company}.bamboohr.com/careers/{jid}" if jid else ""),
            description=_plain(_loc_str(pick(item, "description", "jobDescription",
                                             "departmentLabel", "department"))),
            source="bamboohr",
            posted_at=_loc_str(pick(item, "datePosted", "postedDate", "created")),
        ))
    return jobs


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
    elif platform == "recruitee":
        return fetch_recruitee(params.get("company", ""))
    elif platform == "personio":
        return fetch_personio(params.get("company", ""))
    elif platform == "breezy":
        return fetch_breezy(params.get("company", ""))
    elif platform == "workable":
        return fetch_workable(params.get("company", ""))
    elif platform == "bamboohr":
        return fetch_bamboohr(params.get("company", ""))
    return []
