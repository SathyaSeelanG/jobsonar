"""Free, keyless remote-job aggregator APIs.

These mostly cover remote roles, so they're most useful for the "Remote"
entry in config/search.yaml's locations list — they won't add much for
Chennai on-site roles. Each API returns a broad feed rather than supporting
precise keyword search, so we filter client-side against the query terms.
"""
import requests

from ..models import Job

TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (job-agent; personal use)"}


def _keyword_match(query: str, *texts: str) -> bool:
    terms = [t for t in query.lower().replace("/", " ").split() if len(t) > 2]
    haystack = " ".join(t.lower() for t in texts if t)
    return any(term in haystack for term in terms) if terms else True


# --------------------------------------------------------------- Arbeitnow
def fetch_arbeitnow(query: str, max_results: int = 20) -> list[Job]:
    try:
        resp = requests.get("https://www.arbeitnow.com/api/job-board-api",
                             headers=UA, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return []
    jobs = []
    for item in resp.json().get("data", []):
        title, desc = item.get("title", ""), item.get("description", "")
        if not _keyword_match(query, title, desc):
            continue
        jobs.append(Job(
            title=title,
            company=item.get("company_name", ""),
            location="Remote" if item.get("remote") else item.get("location", ""),
            url=item.get("url", ""),
            description=desc[:6000],
            source="arbeitnow",
            posted_at=str(item.get("created_at", "")),
        ))
        if len(jobs) >= max_results:
            break
    return jobs


# --------------------------------------------------------------- Remotive
def fetch_remotive(query: str, max_results: int = 20) -> list[Job]:
    try:
        resp = requests.get("https://remotive.com/api/remote-jobs",
                             params={"category": "software-dev", "search": query},
                             headers=UA, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return []
    jobs = []
    for item in resp.json().get("jobs", [])[:max_results]:
        jobs.append(Job(
            title=item.get("title", ""),
            company=item.get("company_name", ""),
            location=item.get("candidate_required_location", "Remote"),
            url=item.get("url", ""),
            description=(item.get("description") or "")[:6000],
            source="remotive",
            posted_at=item.get("publication_date", ""),
            salary=item.get("salary", ""),
        ))
    return jobs


# --------------------------------------------------------------- RemoteOK
def fetch_remoteok(query: str, max_results: int = 20) -> list[Job]:
    try:
        resp = requests.get("https://remoteok.com/api", headers=UA, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return []
    jobs = []
    for item in resp.json():
        title = item.get("position") or item.get("title")
        if not title:
            continue  # first element is a metadata/legal blob, not a job
        desc = item.get("description", "")
        if not _keyword_match(query, title, desc, " ".join(item.get("tags") or [])):
            continue
        jobs.append(Job(
            title=title,
            company=item.get("company", ""),
            location=item.get("location") or "Remote",
            url=item.get("url", "") or f"https://remoteok.com/remote-jobs/{item.get('id', '')}",
            description=desc[:6000],
            source="remoteok",
            posted_at=str(item.get("date", "")),
            salary=str(item.get("salary_min", "") or ""),
        ))
        if len(jobs) >= max_results:
            break
    return jobs


# --------------------------------------------------------------- Jobicy
def fetch_jobicy(query: str, max_results: int = 20) -> list[Job]:
    try:
        resp = requests.get("https://jobicy.com/api/v2/remote-jobs",
                             params={"count": max_results, "tag": "dev"},
                             headers=UA, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return []
    jobs = []
    for item in resp.json().get("jobs", []):
        title = item.get("jobTitle", "")
        desc = item.get("jobExcerpt") or item.get("jobDescription", "")
        if not _keyword_match(query, title, desc):
            continue
        jobs.append(Job(
            title=title,
            company=item.get("companyName", ""),
            location=item.get("jobGeo", "Remote"),
            url=item.get("url", ""),
            description=desc[:6000],
            source="jobicy",
            posted_at=item.get("pubDate", ""),
        ))
        if len(jobs) >= max_results:
            break
    return jobs
