"""Adzuna — free job aggregator API (developer.adzuna.com)."""
import os
import requests

from ..models import Job

PAGE_SIZE = 50  # Adzuna's max results_per_page


def fetch_adzuna(query: str, location: str, country: str = "in",
                 max_results: int = 20, posted_within_days: int = 7) -> list[Job]:
    """Fetch up to `max_results` jobs, paginating in blocks of 50 (Adzuna's
    per-page cap) rather than capping at whatever fits on page 1."""
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []

    jobs: list[Job] = []
    per_page = min(PAGE_SIZE, max_results) or PAGE_SIZE
    pages = max(1, (max_results + per_page - 1) // per_page)

    for page in range(1, pages + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": query,
            "results_per_page": per_page,
            "max_days_old": posted_within_days,
            "content-type": "application/json",
        }
        if location.lower() not in ("remote", "", country):
            params["where"] = location
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException:
            break

        results = resp.json().get("results", [])
        if not results:
            break

        for item in results:
            jobs.append(Job(
                title=item.get("title", "").replace("<strong>", "").replace("</strong>", ""),
                company=(item.get("company") or {}).get("display_name", ""),
                location=(item.get("location") or {}).get("display_name", ""),
                url=item.get("redirect_url", ""),
                description=(item.get("description") or "")[:6000],
                source="adzuna",
                posted_at=item.get("created", ""),
                salary=_salary(item),
            ))
            if len(jobs) >= max_results:
                return jobs

        if len(results) < per_page:
            break  # last page

    return jobs


def _salary(item: dict) -> str:
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if lo or hi:
        return f"{int(lo or 0)}-{int(hi or 0)}"
    return ""
