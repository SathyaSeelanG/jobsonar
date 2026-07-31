"""Standalone staged job scraping orchestration."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import csv
import json
from time import perf_counter
from pathlib import Path
import sqlite3

from rich.table import Table

from .models import Job
from .util import default_chrome_binary, default_chrome_user_data_dir


@dataclass
class SourceResult:
    name: str
    jobs: list[Job]
    duration_s: float
    error: str = ""

    @property
    def count(self) -> int:
        return len(self.jobs)


def run_scrape(cfg: dict, console, progress_callback=None) -> list[SourceResult]:
    from .sources import (
        fetch_adzuna,
        fetch_arbeitnow,
        fetch_ashby,
        fetch_bamboohr,
        fetch_breezy,
        fetch_greenhouse,
        fetch_jobicy,
        fetch_jsearch,
        fetch_jsonld,
        fetch_keka,
        fetch_lever,
        fetch_nextdata,
        fetch_personio,
        fetch_recruitee,
        fetch_remotive,
        fetch_remoteok,
        fetch_rippling,
        fetch_smartrecruiters,
        fetch_workable,
        fetch_workday,
        scan_watchlist,
        scrape_linkedin,
        scrape_simplyhired,
        scrape_timesjobs,
    )

    src = dict(cfg.get("sources", {}))
    # Keyed sources return [] the moment they see a missing credential, so
    # leaving them on costs one no-op task per query x location — 24 rows of
    # "0 jobs, no error" in scrape-report, which is exactly what a genuinely
    # broken source looks like. Turn them off up front and say why once.
    import os as _os
    for _name, _env in (("adzuna", ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")),
                        ("jsearch", ("JSEARCH_API_KEY",))):
        if src.get(_name) and not all(_os.getenv(v) for v in _env):
            src[_name] = False
            if console:
                console.print(
                    f"[dim]{_name}: skipped, set {' + '.join(_env)} in .env.local to enable[/dim]")

    n = cfg.get("max_results_per_query", 20)
    days = cfg.get("posted_within_days", 3)
    country = cfg.get("adzuna_country", "in")
    allowed_stages = set(cfg.get("_stages") or ["api", "web", "browser", "final"])
    query_limit = cfg.get("_query_limit", 0) or 0
    location_limit = cfg.get("_location_limit", 0) or 0
    results: list[SourceResult] = []

    api_tasks: list[tuple[str, callable]] = []
    web_tasks: list[tuple[str, callable]] = []
    browser_tasks: list[tuple[str, callable]] = []
    final_tasks: list[tuple[str, callable]] = []

    queries = cfg.get("queries", [])
    locations = cfg.get("locations", [])
    if query_limit > 0:
        queries = queries[:query_limit]
    if location_limit > 0:
        locations = locations[:location_limit]

    for query in queries:
        for location in locations:
            if src.get("adzuna"):
                api_tasks.append((
                    f"adzuna[{query}|{location}]",
                    lambda query=query, location=location: fetch_adzuna(query, location, country, n, days),
                ))
            if src.get("jsearch"):
                api_tasks.append((
                    f"jsearch[{query}|{location}]",
                    lambda query=query, location=location: fetch_jsearch(query, location, n, days),
                ))
            if src.get("simplyhired"):
                web_tasks.append((
                    f"simplyhired[{query}|{location}]",
                    lambda query=query, location=location: scrape_simplyhired(query, location, n),
                ))
            if src.get("linkedin"):
                web_tasks.append((
                    f"linkedin[{query}|{location}]",
                    lambda query=query, location=location: scrape_linkedin(query, location, n),
                ))
            if src.get("timesjobs"):
                web_tasks.append((
                    f"timesjobs[{query}|{location}]",
                    lambda query=query, location=location: scrape_timesjobs(query, location, n),
                ))
            if location.lower() == "remote":
                if src.get("arbeitnow"):
                    api_tasks.append((f"arbeitnow[{query}]", lambda query=query: fetch_arbeitnow(query, n)))
                if src.get("remotive"):
                    api_tasks.append((f"remotive[{query}]", lambda query=query: fetch_remotive(query, n)))
                if src.get("remoteok"):
                    api_tasks.append((f"remoteok[{query}]", lambda query=query: fetch_remoteok(query, n)))
                if src.get("jobicy"):
                    api_tasks.append((f"jobicy[{query}]", lambda query=query: fetch_jobicy(query, n)))


    for token in cfg.get("greenhouse_boards") or []:
        if src.get("greenhouse"):
            api_tasks.append((f"greenhouse:{token}", lambda token=token: fetch_greenhouse(token)))
    for token in cfg.get("lever_boards") or []:
        if src.get("lever"):
            api_tasks.append((f"lever:{token}", lambda token=token: fetch_lever(token)))
    for token in cfg.get("ashby_boards") or []:
        if src.get("ashby"):
            api_tasks.append((f"ashby:{token}", lambda token=token: fetch_ashby(token)))
    for token in cfg.get("smartrecruiters_companies") or []:
        if src.get("smartrecruiters"):
            api_tasks.append((f"smartrecruiters:{token}", lambda token=token: fetch_smartrecruiters(token)))
    for token in cfg.get("rippling_boards") or []:
        if src.get("rippling"):
            api_tasks.append((f"rippling:{token}", lambda token=token: fetch_rippling(token)))
    for token in cfg.get("recruitee_boards") or []:
        if src.get("recruitee"):
            api_tasks.append((f"recruitee:{token}", lambda token=token: fetch_recruitee(token, n)))
    for token in cfg.get("personio_boards") or []:
        if src.get("personio"):
            api_tasks.append((f"personio:{token}", lambda token=token: fetch_personio(token, n)))
    for token in cfg.get("breezy_boards") or []:
        if src.get("breezy"):
            api_tasks.append((f"breezy:{token}", lambda token=token: fetch_breezy(token, n)))
    for token in cfg.get("workable_boards") or []:
        if src.get("workable"):
            api_tasks.append((f"workable:{token}", lambda token=token: fetch_workable(token, n)))
    for token in cfg.get("bamboohr_boards") or []:
        if src.get("bamboohr"):
            api_tasks.append((f"bamboohr:{token}", lambda token=token: fetch_bamboohr(token, n)))
    # Workday needs three parts, so entries are "tenant/dc/site" strings —
    # e.g. "zoho/wd3/Zoho_Careers". Anything malformed is skipped rather than
    # sent to fetch_workday with empty components.
    for entry in cfg.get("workday_tenants") or []:
        if not src.get("workday"):
            continue
        parts = [p for p in str(entry).split("/") if p]
        if len(parts) != 3:
            continue
        tenant, dc, site = parts
        api_tasks.append((
            f"workday:{tenant}/{site}",
            lambda tenant=tenant, dc=dc, site=site: fetch_workday(tenant, dc, site),
        ))
    for url in cfg.get("jsonld_urls") or []:
        if src.get("jsonld"):
            api_tasks.append((f"jsonld:{url}", lambda url=url: fetch_jsonld(url)))
    for url in cfg.get("nextdata_urls") or []:
        if src.get("nextdata"):
            api_tasks.append((f"nextdata:{url}", lambda url=url: fetch_nextdata(url)))
    for token in cfg.get("keka_boards") or []:
        if src.get("keka"):
            # Was a browser task while fetch_keka drove Playwright; it's a plain
            # JSON call now, so it belongs in the pooled API stage.
            api_tasks.append((f"keka:{token}", lambda token=token: fetch_keka(token, n)))

    if src.get("watchlist"):
        final_tasks.append((
            "watchlist",
            lambda: scan_watchlist(
                cfg["_companies_path"],
                extract_jobs=src.get("watchlist_extract_jobs", True),
                company_limit=cfg.get("watchlist_company_limit", 0),
                max_workers=cfg.get("watchlist_workers", 8),
            ),
        ))

    na_cfg = cfg.get("naukri_auth") or {}
    if na_cfg.get("enabled"):
        from .sources.naukri_auth import SessionExpired, search_naukri_auth

        locations = cfg.get("locations", [])
        naukri_location = locations[0] if locations else "Chennai"

        def _naukri_auth_scan():
            try:
                return search_naukri_auth(
                    cdp_port=na_cfg.get("cdp_port", 9222),
                    queries=cfg.get("queries", []),
                    location=naukri_location,
                    max_results=na_cfg.get("max_results", 20),
                    chrome_path=na_cfg.get("chrome_path") or default_chrome_binary(),
                    user_data_dir=na_cfg.get("user_data_dir") or default_chrome_user_data_dir(),
                    profile_directory=na_cfg.get("profile_directory", "Default"),
                )
            except SessionExpired as exc:
                raise RuntimeError(str(exc)) from exc

        final_tasks.append(("naukri_auth", _naukri_auth_scan))

    lf_cfg = cfg.get("linkedin_feed") or {}
    if lf_cfg.get("enabled"):
        from .sources.linkedin_feed import SessionExpired, scan_linkedin_feed

        def _feed_scan():
            try:
                return scan_linkedin_feed(
                    cfg["_root"] / lf_cfg.get("state_path", "data/linkedin_auth.json"),
                    lf_cfg.get("queries") or [],
                    lf_cfg.get("max_posts", 15),
                )
            except SessionExpired as exc:
                raise RuntimeError(str(exc)) from exc

        final_tasks.append(("linkedin_feed", _feed_scan))

    total_tasks = 0
    if "api" in allowed_stages:
        total_tasks += len(api_tasks)
    if "web" in allowed_stages:
        total_tasks += len(web_tasks)
    if "browser" in allowed_stages:
        total_tasks += len(browser_tasks)
    if "final" in allowed_stages:
        total_tasks += len(final_tasks)

    completed_tasks = [0]

    def _notify(stage_label: str, task_name: str, res: SourceResult):
        if not task_name.startswith("Starting stage"):
            completed_tasks[0] += 1
        if progress_callback:
            try:
                progress_callback(
                    stage=stage_label,
                    completed=completed_tasks[0],
                    total=total_tasks,
                    task_name=task_name,
                    result=res,
                )
            except Exception:
                pass

    for stage_name, tasks, workers in (
        ("api", api_tasks, cfg.get("api_workers", 8)),
        ("web", web_tasks, cfg.get("web_workers", 6)),
    ):
        if stage_name in allowed_stages:
            results.extend(_run_parallel_stage(stage_name, tasks, workers, console, _notify))

    for stage_name, tasks in (
        ("browser", browser_tasks),
        ("final", final_tasks),
    ):
        if stage_name in allowed_stages:
            results.extend(_run_sequential_stage(stage_name, tasks, _notify))

    return results


def _run_parallel_stage(stage_name: str, tasks: list[tuple[str, callable]], workers: int, console, on_complete=None) -> list[SourceResult]:
    if not tasks:
        return []
    out: list[SourceResult] = []
    max_workers = min(max(1, workers), len(tasks))
    console.print(f"[dim]Stage {stage_name}: {len(tasks)} task(s), {max_workers} worker(s)[/dim]")
    if on_complete:
        on_complete(f"Stage {stage_name}", f"Starting stage {stage_name} ({len(tasks)} tasks)...", SourceResult(name=stage_name, jobs=[], duration_s=0))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_task, name, fn): name for name, fn in tasks}
        for future in as_completed(futures):
            res = future.result()
            out.append(res)
            if on_complete:
                on_complete(f"Stage {stage_name}", futures[future], res)
    return out


def _run_sequential_stage(stage_name: str, tasks: list[tuple[str, callable]], on_complete=None) -> list[SourceResult]:
    if not tasks:
        return []
    out: list[SourceResult] = []
    if on_complete:
        on_complete(f"Stage {stage_name}", f"Starting stage {stage_name} ({len(tasks)} tasks)...", SourceResult(name=stage_name, jobs=[], duration_s=0))
    for name, fn in tasks:
        res = _run_task(f"{stage_name}:{name}", fn)
        out.append(res)
        if on_complete:
            on_complete(f"Stage {stage_name}", name, res)
    return out


def _run_task(name: str, fn) -> SourceResult:
    start = perf_counter()
    try:
        jobs = fn() or []
        return SourceResult(name=name, jobs=jobs, duration_s=perf_counter() - start)
    except Exception as exc:
        return SourceResult(name=name, jobs=[], duration_s=perf_counter() - start, error=str(exc))


def print_report(console, results: list[SourceResult]) -> None:
    table = Table(title="Source Report")
    table.add_column("Source")
    table.add_column("Jobs", justify="right")
    table.add_column("Seconds", justify="right")
    table.add_column("Status")
    for result in sorted(results, key=lambda item: item.name):
        status = result.error or ("ok" if result.count else "empty")
        table.add_row(result.name, str(result.count), f"{result.duration_s:.1f}", status[:60])
    console.print(table)


def flatten_jobs(results: list[SourceResult]) -> list[Job]:
    jobs: list[Job] = []
    for result in results:
        jobs.extend(result.jobs)
    return jobs


def dedupe_jobs(jobs: list[Job]) -> list[Job]:
    seen_ids = set()
    seen_fuzzy = set()
    out: list[Job] = []
    for job in jobs:
        if job.id in seen_ids or (job.fuzzy_key and job.fuzzy_key in seen_fuzzy):
            continue
        seen_ids.add(job.id)
        if job.fuzzy_key:
            seen_fuzzy.add(job.fuzzy_key)
        out.append(job)
    return out


def save_jobs_json(path: Path, jobs: list[Job]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [job.to_dict() for job in jobs]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_jobs_csv(path: Path, jobs: list[Job]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id", "title", "company", "location", "url", "source", "posted_at",
        "salary", "status", "score", "score_reason", "fetched_at",
        "experience_level", "company_careers_url", "description",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs:
            row = job.to_dict()
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def save_jobs_sqlite(path: Path, jobs: list[Job]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scraped_jobs (
                id TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                location TEXT,
                url TEXT,
                description TEXT,
                source TEXT,
                posted_at TEXT,
                salary TEXT,
                status TEXT,
                score INTEGER,
                score_reason TEXT,
                fetched_at TEXT,
                experience_level TEXT,
                company_careers_url TEXT,
                fuzzy_key TEXT
            );
            DELETE FROM scraped_jobs;
            """
        )
        conn.executemany(
            """
            INSERT INTO scraped_jobs (
                id, title, company, location, url, description, source,
                posted_at, salary, status, score, score_reason, fetched_at,
                experience_level, company_careers_url, fuzzy_key
            ) VALUES (
                :id, :title, :company, :location, :url, :description, :source,
                :posted_at, :salary, :status, :score, :score_reason, :fetched_at,
                :experience_level, :company_careers_url, :fuzzy_key
            )
            """,
            [job.to_dict() for job in jobs],
        )
        conn.commit()
    finally:
        conn.close()


def save_run_report_json(path: Path, results: list[SourceResult], jobs: list[Job]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "total_sources": len(results),
        "total_jobs": len(jobs),
        "sources": [
            {
                "name": result.name,
                "jobs": result.count,
                "duration_s": round(result.duration_s, 3),
                "error": result.error,
            }
            for result in sorted(results, key=lambda item: item.name)
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
