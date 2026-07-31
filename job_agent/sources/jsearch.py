"""JSearch (RapidAPI) — aggregates Google for Jobs: LinkedIn, Indeed, Naukri, etc."""
import math
import os
import requests

from ..models import Job

API_URL = "https://jsearch.p.rapidapi.com/search"


def fetch_jsearch(query: str, location: str, max_results: int = 20,
                  posted_within_days: int = 7) -> list[Job]:
    key = os.getenv("JSEARCH_API_KEY")
    if not key:
        return []
    date_filter = "week" if posted_within_days <= 7 else "month"
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    # JSearch returns roughly ten jobs per page. Ask for enough pages to honor
    # max_results instead of stopping after the first page.
    params = {
        "query": f"{query} in {location}",
        "num_pages": max(1, min(20, math.ceil(max_results / 10))),
        "date_posted": date_filter,
    }
    resp = requests.get(API_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    # RapidAPI/JSearch sometimes answers with HTTP 200 but an error body
    # (quota exceeded, invalid key, etc.) and an empty "data" list — that
    # used to look identical to "no jobs found" in the run log. Surface it
    # as a real error instead so quota/key problems are visible, not silent.
    status = str(payload.get("status", "")).upper()
    if status and status != "OK":
        raise RuntimeError(f"jsearch API error: {payload.get('message') or payload}")
    jobs = []
    for item in payload.get("data", [])[:max_results]:
        jobs.append(Job(
            title=item.get("job_title", ""),
            company=item.get("employer_name", ""),
            location=", ".join(filter(None, [item.get("job_city"), item.get("job_country")])),
            url=item.get("job_apply_link") or item.get("job_google_link", ""),
            description=(item.get("job_description") or "")[:6000],
            source="jsearch",
            posted_at=item.get("job_posted_at_datetime_utc") or "",
            salary=_salary(item),
        ))
    return jobs


def _salary(item: dict) -> str:
    lo, hi = item.get("job_min_salary"), item.get("job_max_salary")
    if lo or hi:
        cur = item.get("job_salary_currency") or ""
        return f"{cur} {lo or '?'}-{hi or '?'}".strip()
    return ""
