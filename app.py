"""Local Flask UI for browsing and fetching jobs.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request
from rich.console import Console

from job_agent.llm import available as llm_available
from job_agent.scraper import dedupe_jobs, flatten_jobs, run_scrape
from job_agent.scoring import (ALL_EXPERIENCE_LEVELS, is_experience_match, is_location_match,
                                is_recently_posted, is_relevant_role, keyword_score, llm_score, wants_all)
from job_agent.tracker import Tracker
from job_agent.util import _parse_dt, freshness, load_env, load_profile

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "jobs.db"

app = Flask(__name__, template_folder="templates")
console = Console()

FETCH_LOCK = threading.Lock()
FETCH_STATE = {
    "running": False,
    "mode": "full",
    "started_at": "",
    "finished_at": "",
    "error": "",
    "stage": "",
    "progress_percent": 0,
    "tasks_total": 0,
    "tasks_completed": 0,
    "logs": [],
    "fetched": 0,
    "unique": 0,
    "new": 0,
    "shortlisted": 0,
    "source_counts": {},
    "current_scanned_jobs": [],
}

# Cities the search config targets, used to bucket messy raw location strings.
KNOWN_CITIES = ["chennai", "coimbatore", "madurai", "bengaluru", "bangalore", "remote"]
STATUS_ORDER = ["shortlisted", "new", "tailored", "applied", "archived", "not_interested", "skipped", "stale"]


def _city_bucket(location: str) -> str:
    low = (location or "").lower()
    for city in KNOWN_CITIES:
        if city in low:
            if city in ("bangalore", "bengaluru"):
                return "Bangalore / Bengaluru"
            return city.capitalize()
    return "Other"


def _age_days(posted_at: str, fetched_at: str) -> int | None:
    ts = _parse_dt((posted_at or fetched_at or "").strip())
    if ts is None:
        return None
    return max(0, (datetime.now(timezone.utc) - ts).days)


def _fetched_age_days(fetched_at: str) -> int | None:
    ts = _parse_dt((fetched_at or "").strip())
    if ts is None:
        return None
    return max(0, (datetime.now(timezone.utc) - ts).days)


def _fetch_state() -> dict:
    with FETCH_LOCK:
        return dict(FETCH_STATE)


def _update_fetch_state(**fields) -> None:
    with FETCH_LOCK:
        FETCH_STATE.update(fields)


def _load_cfg() -> tuple[dict, dict]:
    load_env(ROOT)
    profile = load_profile(ROOT)
    cfg = yaml.safe_load((ROOT / "config" / "search.yaml").read_text(encoding="utf-8"))
    cfg["_root"] = ROOT
    cfg["_companies_path"] = ROOT / "config" / "companies.yaml"
    return profile, cfg


def load_jobs(include_applied: bool = True) -> list[dict]:
    """All tracked jobs, newest fetched first.

    Applied jobs get their own dedicated page (`/applied`), so callers
    serving the main Job Explorer pass include_applied=False to keep them
    out of the default mixed grid.
    """
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        where = "" if include_applied else "WHERE status NOT IN ('applied', 'archived', 'not_interested')"
        rows = conn.execute(
            f"""SELECT id, title, company, location, url, source, score,
                      experience_level, status, posted_at, fetched_at,
                      description, salary, score_reason, applied_at, notes,
                      company_careers_url, scan_id, apply_type
               FROM jobs
               {where}
               ORDER BY fetched_at DESC, score DESC"""
        ).fetchall()
    finally:
        conn.close()

    jobs = []
    for row in rows:
        location = row["location"] or ""
        scan_id_val = 0
        try:
            scan_id_val = row["scan_id"] or 0
        except (IndexError, KeyError):
            scan_id_val = 0

        jobs.append({
            "id": row["id"],
            "title": row["title"] or "",
            "company": row["company"] or "",
            "location": location,
            "city": _city_bucket(location),
            "url": row["url"] or "",
            "source": row["source"] or "",
            "score": row["score"] or 0,
            "experience_level": row["experience_level"] or "",
            "status": row["status"] or "",
            "posted": freshness(row["posted_at"] or "", row["fetched_at"] or ""),
            "age_days": _age_days(row["posted_at"] or "", row["fetched_at"] or ""),
            "fetched_at": row["fetched_at"] or "",
            "fetched_display": freshness("", row["fetched_at"] or ""),
            "fetched_age_days": _fetched_age_days(row["fetched_at"] or ""),
            "description": (row["description"] or "").strip(),
            "salary": row["salary"] or "",
            "score_reason": row["score_reason"] or "",
            "applied_at": row["applied_at"] or "",
            "notes": row["notes"] or "",
            "company_careers_url": row["company_careers_url"] or "",
            "scan_id": scan_id_val,
            "apply_type": row["apply_type"] or "apply_now",
        })
    return jobs


def _run_fetch_pipeline(use_llm: bool = False, mode: str = "full", selected_sources: list[str] | None = None,
                         scan_id: int = 0, posted_freshness_days: int = 3,
                         locations: list[str] | None = None, queries: list[str] | None = None,
                         experience_levels: list[str] | None = None) -> None:
    try:
        profile, cfg = _load_cfg()

        # Scan-time overrides. None means "not passed" -> keep config defaults
        # (existing behavior). An explicit ["all"]/[] means "no restriction,
        # fetch everything". Specific values narrow both what gets *searched*
        # (queries/locations dispatched to sources) and what gets *kept*
        # after fetch (via is_relevant_role/is_location_match/is_experience_match).
        if queries and not wants_all(queries):
            cfg["queries"] = [str(q).strip() for q in queries if str(q).strip()]
        if locations and not wants_all(locations):
            cfg["locations"] = [str(l).strip() for l in locations if str(l).strip()]
        # If the override is present but explicitly "all"/[], leave cfg's
        # configured queries/locations alone (still used to dispatch board
        # searches) — the post-fetch is_location_match gate is what actually
        # widens the *kept* locations to "everything".
        #
        # Role relevance is NOT widened the same way: "all" queries only
        # means "search using every configured query," not "skip the
        # relevance gate." Passing the raw `queries` override straight into
        # is_relevant_role() as `roles` would bypass its keyword check
        # entirely whenever queries=["all"] (the web UI's default), letting
        # any unrelated posting (Data Scientist, BIM Modeller, Assistant
        # Professor, ...) through. So: "all"/None -> fall back to the
        # built-in ROLE_KEYWORDS/GENERIC_TITLE_KEYWORDS gate (roles=None);
        # specific queries still narrow further as free-text role terms.
        role_filter = None if (queries is None or wants_all(queries)) else queries

        # Same "all" != "bypass the gate" rule applies to experience level:
        # the web UI's default payload sends experience_levels=["all"], and
        # passing that straight into is_experience_match() as `levels` would
        # trip its _wants_all() branch and remove the fresher/junior gate
        # entirely for every default/daily scan. "all"/None -> fall back to
        # the built-in fresher+junior (entry-level, ~1yr exp) gate
        # (levels=None); a specific override still narrows further.
        level_filter = None if (experience_levels is None or wants_all(experience_levels)) else experience_levels

        if mode == "fast":
            cfg["_stages"] = ["api", "web"]
            cfg["_query_limit"] = 2
            cfg["_location_limit"] = 1
        elif mode == "watchlist":
            cfg["_stages"] = ["final"]
            for k in list(cfg.get("sources", {}).keys()):
                if not k.startswith("watchlist_"):
                    cfg["sources"][k] = False
            cfg["sources"]["watchlist"] = True
            cfg["sources"]["watchlist_extract_jobs"] = True
        elif mode == "apis":
            cfg["_stages"] = ["api"]

        if selected_sources and "all" not in [s.lower() for s in selected_sources]:
            sel_set = {s.lower() for s in selected_sources}
            if mode == "watchlist":
                sel_set.add("watchlist")

            for k in list(cfg.get("sources", {}).keys()):
                if k.startswith("watchlist_"):
                    cfg["sources"][k] = ("watchlist" in sel_set) or (mode == "watchlist")
                else:
                    cfg["sources"][k] = k.lower() in sel_set

            if any(s in sel_set for s in ("naukri", "keka")):
                stages = cfg.get("_stages") or ["api", "web", "browser", "final"]
                if "browser" not in stages:
                    stages.append("browser")
                cfg["_stages"] = stages
            if "watchlist" in sel_set or mode == "watchlist":
                stages = cfg.get("_stages") or ["api", "web", "browser", "final"]
                if "final" not in stages:
                    stages.append("final")
                cfg["_stages"] = stages

        tracker = Tracker(DB_PATH)

        log_dir = ROOT / "data" / "run_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        run_log_file = log_dir / f"run_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"

        def _on_progress(stage, completed, total, task_name, result):
            with FETCH_LOCK:
                FETCH_STATE["stage"] = stage
                FETCH_STATE["tasks_completed"] = completed
                FETCH_STATE["tasks_total"] = total
                FETCH_STATE["progress_percent"] = int((completed / max(1, total)) * 100) if total else 0

                time_str = datetime.now().strftime("%H:%M:%S")
                if task_name.startswith("Starting stage"):
                    FETCH_STATE["logs"].append({
                        "time": time_str,
                        "msg": task_name,
                        "level": "stage"
                    })
                    msg = task_name
                else:
                    count = result.count if result else 0
                    err = result.error if result else ""
                    if err:
                        msg = f"{task_name} error: {err[:80]}"
                        level = "error"
                    elif count > 0:
                        msg = f"{task_name} completed in {result.duration_s:.1f}s — found {count} jobs"
                        level = "success"
                    else:
                        msg = f"{task_name} checked — 0 new items"
                        level = "info"
                    FETCH_STATE["logs"].append({"time": time_str, "msg": msg, "level": level})
                    if len(FETCH_STATE["logs"]) > 300:
                        FETCH_STATE["logs"] = FETCH_STATE["logs"][-300:]
                
                with run_log_file.open("a", encoding="utf-8") as f:
                    f.write(f"[{time_str}] {msg}\n")

                    if result and result.jobs:
                        for j in result.jobs:
                            if not (is_relevant_role(j, role_filter) and is_experience_match(j, level_filter)
                                    and is_location_match(j, locations) and is_recently_posted(j, max_days=posted_freshness_days)):
                                continue
                            if tracker.is_tracked(j):
                                continue
                            if any(existing["url"] == j.url for existing in FETCH_STATE["current_scanned_jobs"] if existing.get("url") and j.url):
                                continue
                            FETCH_STATE["current_scanned_jobs"].append({
                                "id": j.id,
                                "title": j.title,
                                "company": j.company,
                                "location": j.location,
                                "city": _city_bucket(j.location),
                                "url": j.url,
                                "source": j.source,
                                "score": j.score,
                                "experience_level": j.experience_level,
                                "posted": j.posted_at or "",
                                "apply_type": getattr(j, "apply_type", "apply_now") or "apply_now",
                            })

        source_results = run_scrape(cfg, console, progress_callback=_on_progress)

        with FETCH_LOCK:
            FETCH_STATE["stage"] = "Deduplicating & scoring discovered jobs..."
            FETCH_STATE["logs"].append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "msg": "Scrape complete. Deduplicating and saving to local database...",
                "level": "info"
            })

        raw_jobs = flatten_jobs(source_results)
        jobs = dedupe_jobs(raw_jobs)
        jobs = [j for j in jobs if is_relevant_role(j, role_filter) and is_experience_match(j, level_filter)
                and is_location_match(j, locations) and is_recently_posted(j, max_days=posted_freshness_days)]

        new_count = 0
        new_job_ids = []
        new_jobs = []
        min_score = cfg.get("min_score", 40)
        llm_cfg = cfg.get("llm", {}) or {}
        use_llm_scoring = bool(use_llm and llm_cfg.get("scoring") and llm_available(llm_cfg))

        for idx, job in enumerate(jobs):
            job.score, job.score_reason = keyword_score(job, profile)
            if job.score >= min_score:
                job.status = "shortlisted"
                if use_llm_scoring:
                    if idx % 5 == 0:
                        with FETCH_LOCK:
                            FETCH_STATE["stage"] = f"AI LLM Scoring ({idx+1}/{len(jobs)} jobs)..."
                    refined = llm_score(job, profile, llm_cfg)
                    if refined:
                        job.score, job.score_reason = refined
                        job.status = "shortlisted" if job.score >= min_score else "new"
            if tracker.upsert(job, scan_id=scan_id):
                new_count += 1
                new_job_ids.append(job.id)
                new_jobs.append(job)

        final_scanned_jobs = []
        for j in new_jobs:
            final_scanned_jobs.append({
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "city": _city_bucket(j.location),
                "url": j.url,
                "source": j.source,
                "score": j.score,
                "experience_level": j.experience_level,
                "posted": j.posted_at or "",
                "apply_type": getattr(j, "apply_type", "apply_now") or "apply_now",
            })

        source_counts = {
            result.name: result.count
            for result in sorted(source_results, key=lambda item: item.name)
        }
        shortlisted_cnt = len(tracker.by_status("shortlisted"))
        _update_fetch_state(
            running=False,
            stage="Scan Complete",
            progress_percent=100,
            finished_at=datetime.now(timezone.utc).isoformat(),
            fetched=len(raw_jobs),
            unique=len(jobs),
            new=new_count,
            shortlisted=shortlisted_cnt,
            source_counts=source_counts,
            current_scanned_jobs=final_scanned_jobs,
        )
        if scan_id > 0:
            tracker.update_scan(
                scan_id=scan_id,
                status="completed",
                fetched_count=len(raw_jobs),
                unique_count=len(jobs),
                new_count=new_count,
                shortlisted_count=shortlisted_cnt,
                new_job_ids=new_job_ids
            )
            
        md_file_msg = ""
        if new_jobs:
            try:
                md = "# Newly Fetched Jobs\n\n"
                md += "Here are the most recently discovered jobs from the latest scan:\n\n"
                md += "| Title | Company | Location | Source | Score | Link |\n"
                md += "|-------|---------|----------|--------|-------|------|\n"
                for j in new_jobs:
                    title = (j.title or "").replace("|", "-")
                    company = (j.company or "").replace("|", "-")
                    loc = (j.location or "").replace("|", "-")
                    source = j.source or ""
                    score = j.score or 0
                    url = j.url or ""
                    md += f"| {title} | {company} | {loc} | {source} | {score} | [Apply]({url}) |\n"
                
                out_dir = ROOT / "data" / "fetched_jobs"
                out_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                out_file = out_dir / f"fetched_jobs_{ts}.md"
                out_file.write_text(md, encoding="utf-8")
                md_file_msg = f" Saved {len(new_jobs)} jobs to {out_file.name}."
            except Exception as e:
                md_file_msg = f" (Failed to save MD: {e})"
                
        with FETCH_LOCK:
            FETCH_STATE["logs"].append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "msg": f"Completed! Found {len(raw_jobs)} total, {len(jobs)} unique, {new_count} newly stored.{md_file_msg}",
                "level": "success"
            })
    except Exception as exc:
        _update_fetch_state(
            running=False,
            stage="Failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error=str(exc),
        )
        if scan_id > 0:
            try:
                tracker = Tracker(DB_PATH)
                tracker.update_scan(scan_id=scan_id, status="failed", error=str(exc))
            except Exception:
                pass
        with FETCH_LOCK:
            FETCH_STATE["logs"].append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "msg": f"Pipeline Error: {exc}",
                "level": "error"
            })


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan")
def scan_page():
    return render_template("scan.html")


@app.route("/applied")
def applied_page():
    return render_template("applied.html")


@app.route("/api/jobs/applied")
def api_jobs_applied():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT id, title, company, location, url, source, score,
                      experience_level, status, posted_at, fetched_at,
                      description, salary, score_reason, applied_at, notes,
                      company_careers_url
               FROM jobs
               WHERE status = 'applied'
               ORDER BY applied_at DESC"""
        ).fetchall()
    finally:
        conn.close()

    jobs = []
    for row in rows:
        location = row["location"] or ""
        jobs.append({
            "id": row["id"],
            "title": row["title"] or "",
            "company": row["company"] or "",
            "location": location,
            "city": _city_bucket(location),
            "url": row["url"] or "",
            "source": row["source"] or "",
            "score": row["score"] or 0,
            "experience_level": row["experience_level"] or "",
            "status": row["status"] or "",
            "posted": freshness(row["posted_at"] or "", row["fetched_at"] or ""),
            "age_days": _age_days(row["posted_at"] or "", row["fetched_at"] or ""),
            "fetched_at": row["fetched_at"] or "",
            "fetched_display": freshness("", row["fetched_at"] or ""),
            "fetched_age_days": _fetched_age_days(row["fetched_at"] or ""),
            "description": (row["description"] or "").strip(),
            "salary": row["salary"] or "",
            "score_reason": row["score_reason"] or "",
            "applied_at": row["applied_at"] or "",
            "notes": row["notes"] or "",
            "company_careers_url": row["company_careers_url"] or "",
        })

    search = request.args.get("search", "").strip().lower()
    source = request.args.get("source", "all").strip().lower()
    location = request.args.get("location", "all").strip().lower()

    filtered = []
    for job in jobs:
        job_source = (job.get("source") or "").lower()
        job_city = (job.get("city") or "").lower()
        job_loc = (job.get("location") or "").lower()
        if source != "all" and job_source != source:
            continue
        if location != "all" and job_city != location and location not in job_city and location not in job_loc:
            continue
        if search:
            haystack = f"{job['title']} {job['company']} {job['location']}".lower()
            if search not in haystack:
                continue
        filtered.append(job)

    sources = sorted({(j.get("source") or "").lower() for j in jobs if j.get("source")})
    cities = sorted({(j.get("city") or "").strip() for j in jobs if j.get("city")})
    return jsonify({"jobs": filtered, "total": len(jobs), "filtered": len(filtered), "sources": sources, "cities": cities})


@app.route("/api/jobs")
def api_jobs():
    jobs = load_jobs(include_applied=True)
    search = request.args.get("search", "").strip().lower()
    level = request.args.get("level", "all").strip().lower()
    source = request.args.get("source", "all").strip().lower()
    status = request.args.get("status", "all").strip().lower()
    location = request.args.get("location", "all").strip().lower()
    role = request.args.get("role", "all").strip().lower()
    posted_raw = request.args.get("posted", "all").strip().lower()
    scan_id_raw = request.args.get("scan_id", "all").strip().lower()
    apply_type_filter = request.args.get("apply_type", "all").strip().lower()

    try:
        max_age_days = int(posted_raw) if posted_raw != "all" else None
    except ValueError:
        max_age_days = None
    fetched_raw = request.args.get("fetched", "all").strip().lower()
    try:
        max_fetched_age_days = int(fetched_raw) if fetched_raw != "all" else None
    except ValueError:
        max_fetched_age_days = None
    min_score_raw = request.args.get("min_score", "0").strip()
    try:
        min_score = max(0, min(100, int(min_score_raw or "0")))
    except ValueError:
        min_score = 0

    scan_target_job_ids = set()
    if scan_id_raw != "all":
        try:
            s_id = int(scan_id_raw)
            tracker = Tracker(DB_PATH)
            s_jobs = tracker.get_scan_jobs(s_id)
            scan_target_job_ids = {r["id"] for r in s_jobs}
        except Exception:
            pass

    filtered = []
    for job in jobs:
        job_level = (job.get("experience_level") or "").lower()
        job_source = (job.get("source") or "").lower()
        job_status = (job.get("status") or "").lower()
        job_city = (job.get("city") or "").lower()
        job_loc = (job.get("location") or "").lower()
        title_low = (job.get("title") or "").lower()
        job_apply_type = (job.get("apply_type") or "apply_now").lower()

        if apply_type_filter != "all" and job_apply_type != apply_type_filter:
            continue

        if scan_id_raw != "all":
            job_scan_id = str(job.get("scan_id") or 0)
            if job_scan_id != scan_id_raw and job.get("id") not in scan_target_job_ids:
                continue

        if level != "all" and job_level != level:
            continue
        if source != "all" and job_source != source:
            continue
        if status != "all":
            if status in ("not_applied", "active"):
                if job_status in ("applied", "archived", "not_interested", "skipped", "stale"):
                    continue
            elif job_status != status:
                continue
        if location != "all" and job_city != location and location not in job_city and location not in job_loc:
            continue
        if role != "all":
            if role == "python" and not any(k in title_low for k in ["python", "django", "flask", "fastapi"]):
                continue
            elif role == "react" and not any(k in title_low for k in ["react", "frontend", "front-end", "ui", "vue", "angular"]):
                continue
            elif role == "node" and not any(k in title_low for k in ["node", "express", "backend", "back-end"]):
                continue
            elif role == "fullstack" and not any(k in title_low for k in ["full stack", "full-stack", "fullstack", "mern", "mean"]):
                continue
            elif role == "engineer" and not any(k in title_low for k in ["software engineer", "sde", "developer", "programmer", "associate"]):
                continue
            elif role == "web" and not any(k in title_low for k in ["web developer", "web engineer", "html", "css", "javascript"]):
                continue
            elif role not in ("python", "react", "node", "fullstack", "engineer", "web") and role not in title_low:
                continue
        if max_age_days is not None:
            job_age = job.get("age_days")
            if job_age is None or job_age > max_age_days:
                continue
        if max_fetched_age_days is not None:
            fetched_age = job.get("fetched_age_days")
            if fetched_age is None or fetched_age > max_fetched_age_days:
                continue
        if job.get("score", 0) < min_score:
            continue
        if search:
            haystack = f"{job['title']} {job['company']} {job['location']}".lower()
            if search not in haystack:
                continue
        filtered.append(job)

    sources = sorted({(j.get("source") or "").lower() for j in jobs if j.get("source")})
    cities = sorted({(j.get("city") or "").strip() for j in jobs if j.get("city")})
    seen_statuses = {j.get("status") or "" for j in jobs if j.get("status")}
    statuses = [s for s in STATUS_ORDER if s in seen_statuses]
    statuses += sorted(seen_statuses - set(statuses))

    tracker = Tracker(DB_PATH)
    scans_rows = tracker.get_scan_history(limit=50)
    scans_list = []
    for s in scans_rows:
        scans_list.append({
            "id": s["id"],
            "mode": s["mode"] or "full",
            "started_at": s["started_at"] or "",
            "started_display": freshness("", s["started_at"] or "") if s["started_at"] else "",
            "new_count": s["new_count"] or 0,
            "fetched_count": s["fetched_count"] or 0,
        })

    return jsonify({
        "jobs": filtered,
        "total": len(jobs),
        "filtered": len(filtered),
        "sources": sources,
        "cities": cities,
        "statuses": statuses,
        "scans": scans_list,
        "fetch": _fetch_state(),
    })


@app.route("/api/jobs/recheck_apply_types", methods=["POST"])
def api_recheck_apply_types():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, title, company, description, source, url FROM jobs").fetchall()
        updated_quick = 0
        updated_apply_now = 0
        for r in rows:
            desc_low = (r["description"] or "").lower() + " " + (r["title"] or "").lower()
            job_id = r["id"]
            if "quick apply" in desc_low or "quickapply" in desc_low:
                conn.execute("UPDATE jobs SET apply_type = 'quick_apply' WHERE id = ?", (job_id,))
                updated_quick += 1
            else:
                conn.execute("UPDATE jobs SET apply_type = 'apply_now' WHERE id = ?", (job_id,))
                updated_apply_now += 1
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "updated_quick": updated_quick, "updated_apply_now": updated_apply_now})


@app.route("/api/jobs/clear", methods=["POST"])
def api_clear_jobs():
    payload = request.get_json(silent=True) or {}
    try:
        older_than_days = int(payload.get("older_than_days", 30))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid older_than_days"}), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, fetched_at FROM jobs WHERE status NOT IN ('applied', 'archived')").fetchall()
        to_delete = [
            row["id"] for row in rows
            if (_fetched_age_days(row["fetched_at"] or "") or 0) >= older_than_days
        ]
        if to_delete:
            conn.executemany("DELETE FROM jobs WHERE id = ?", [(i,) for i in to_delete])
            conn.commit()
    finally:
        conn.close()
    return jsonify({"deleted": len(to_delete)})


@app.route("/api/jobs/<job_id>/delete", methods=["POST"])
def api_delete_job(job_id):
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    if not deleted:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/jobs/<job_id>/apply", methods=["POST"])
def api_mark_applied(job_id):
    tracker = Tracker(DB_PATH)
    job = tracker.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    tracker.set(job["id"], status="applied", applied_at=datetime.now(timezone.utc).isoformat())
    return jsonify({"ok": True})


@app.route("/api/jobs/<job_id>/archive", methods=["POST"])
def api_mark_archived(job_id):
    tracker = Tracker(DB_PATH)
    job = tracker.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    tracker.set(job["id"], status="archived")
    return jsonify({"ok": True})


@app.route("/api/jobs/<job_id>/not_interested", methods=["POST"])
def api_mark_not_interested(job_id):
    tracker = Tracker(DB_PATH)
    job = tracker.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    tracker.set(job["id"], status="not_interested")
    return jsonify({"ok": True})


@app.route("/api/jobs/clear_non_fresher", methods=["POST"])
def api_clear_non_fresher_jobs():
    from job_agent.sources.ats import infer_experience_level

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, title, description FROM jobs WHERE status NOT IN ('applied', 'archived')"
        ).fetchall()
        to_delete = [
            row["id"] for row in rows
            if infer_experience_level(row["title"] or "", row["description"] or "")
            in ("junior", "mid", "senior", "lead")
        ]
        if to_delete:
            conn.executemany("DELETE FROM jobs WHERE id = ?", [(i,) for i in to_delete])
            conn.commit()
    finally:
        conn.close()
    return jsonify({"deleted": len(to_delete)})


@app.route("/api/jobs/clear_all", methods=["POST"])
def api_clear_all_jobs():
    conn = sqlite3.connect(DB_PATH)
    try:
        count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status != 'applied'").fetchone()[0]
        conn.execute("DELETE FROM jobs WHERE status != 'applied'")
        conn.commit()
    finally:
        conn.close()
    return jsonify({"deleted": count})


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    payload = request.get_json(silent=True) or {}
    use_llm = bool(payload.get("use_llm", False))
    mode = str(payload.get("mode", "full")).strip().lower()
    raw_sources = payload.get("sources", None)
    selected_sources = None
    if isinstance(raw_sources, list):
        selected_sources = [str(s).strip() for s in raw_sources if str(s).strip()]
    elif isinstance(raw_sources, str) and raw_sources.strip():
        selected_sources = [raw_sources.strip()]

    posted_freshness_raw = str(payload.get("posted_freshness", "3")).strip().lower()
    try:
        posted_freshness_days = 365 if posted_freshness_raw == "all" else int(posted_freshness_raw)
    except ValueError:
        posted_freshness_days = 3

    def _parse_list_param(name: str) -> list[str] | None:
        """Scan-time filter override: location / role (query) / experience.
        Missing entirely -> None (use tracker defaults, unchanged behavior).
        Present as a list, string, or the literal 'all' -> passed through
        as-is; scoring.py's matchers treat [] / ['all'] as 'no filter'."""
        raw = payload.get(name, None)
        if raw is None:
            return None
        if isinstance(raw, list):
            return [str(v).strip() for v in raw if str(v).strip()] or ["all"]
        raw = str(raw).strip()
        if not raw:
            return None
        return [raw]

    locations = _parse_list_param("locations")
    queries = _parse_list_param("queries") or _parse_list_param("roles")
    experience_levels = _parse_list_param("experience_levels") or _parse_list_param("experience")

    if mode not in ("full", "fast", "watchlist", "apis"):
        mode = "full"

    tracker = Tracker(DB_PATH)
    src_label = ", ".join(selected_sources) if (selected_sources and "all" not in [s.lower() for s in selected_sources]) else "All Active Sources"
    freshness_label = f" (Past {posted_freshness_days}d)" if posted_freshness_days < 365 else " (Any Time)"
    loc_label = f" | Location: {', '.join(locations)}" if locations else ""
    role_label = f" | Role: {', '.join(queries)}" if queries else ""
    exp_label = f" | Level: {', '.join(experience_levels)}" if experience_levels else ""
    scan_id = tracker.create_scan(mode=mode, sources=src_label + freshness_label + loc_label + role_label + exp_label)

    with FETCH_LOCK:
        if FETCH_STATE["running"]:
            return jsonify({"ok": False, "fetch": dict(FETCH_STATE)}), 409
        FETCH_STATE["running"] = True
        FETCH_STATE["mode"] = mode
        FETCH_STATE["scan_id"] = scan_id
        FETCH_STATE["started_at"] = datetime.now(timezone.utc).isoformat()
        FETCH_STATE["finished_at"] = ""
        FETCH_STATE["error"] = ""
        FETCH_STATE["stage"] = f"Initializing {mode.upper()} scan..."
        FETCH_STATE["progress_percent"] = 0
        FETCH_STATE["tasks_total"] = 0
        FETCH_STATE["tasks_completed"] = 0
        FETCH_STATE["logs"] = [{
            "time": datetime.now().strftime("%H:%M:%S"),
            "msg": f"Started {mode.upper()} scan (# {scan_id}) for: {src_label}{freshness_label}...",
            "level": "info"
        }]
        FETCH_STATE["fetched"] = 0
        FETCH_STATE["unique"] = 0
        FETCH_STATE["new"] = 0
        FETCH_STATE["shortlisted"] = 0
        FETCH_STATE["source_counts"] = {}
        FETCH_STATE["current_scanned_jobs"] = []

    thread = threading.Thread(
        target=_run_fetch_pipeline,
        args=(use_llm, mode, selected_sources, scan_id, posted_freshness_days, locations, queries, experience_levels),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "scan_id": scan_id, "fetch": _fetch_state()})


@app.route("/api/fetch")
def api_fetch_status():
    return jsonify({"fetch": _fetch_state()})


@app.route("/api/scan_options")
def api_scan_options():
    """Options for the scan screen's location/role/experience selectors.

    Locations/queries come straight from config/search.yaml so the UI always
    reflects whatever's actually configured; experience levels are the fixed
    set the scorer understands. Everything defaults to "All" client-side —
    picking a specific value narrows the scan, leaving it at "All" fetches
    without that restriction (see is_location_match/is_relevant_role/
    is_experience_match in job_agent/scoring.py)."""
    _, cfg = _load_cfg()
    configured = cfg.get("locations", []) or []
    extra = [c.capitalize() for c in KNOWN_CITIES if c != "remote"] + ["Remote"]
    seen = {loc.strip().lower() for loc in configured}
    locations = list(configured) + [c for c in extra if c.lower() not in seen and not seen.add(c.lower())]
    return jsonify({
        "locations": locations,
        "queries": cfg.get("queries", []) or [],
        "experience_levels": list(ALL_EXPERIENCE_LEVELS),
    })


@app.route("/api/scans")
def api_scans():
    mode = request.args.get("mode", "all").strip().lower()
    status = request.args.get("status", "all").strip().lower()
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        limit = 100

    tracker = Tracker(DB_PATH)
    rows = tracker.get_scan_history(limit=limit, mode=mode)

    scans = []
    for r in rows:
        scan_status = r["status"] or ""
        if status != "all" and scan_status != status:
            continue

        started = r["started_at"] or ""
        finished = r["finished_at"] or ""

        duration = 0
        if started and finished:
            t1 = _parse_dt(started)
            t2 = _parse_dt(finished)
            if t1 and t2:
                duration = int(max(0, (t2 - t1).total_seconds()))

        new_ids = []
        if r["new_job_ids"]:
            try:
                new_ids = json.loads(r["new_job_ids"])
            except Exception:
                pass

        scans.append({
            "id": r["id"],
            "mode": r["mode"] or "full",
            "sources": r["sources"] or "",
            "started_at": started,
            "finished_at": finished,
            "started_display": freshness("", started) if started else "",
            "duration_seconds": duration,
            "status": scan_status,
            "fetched_count": r["fetched_count"] or 0,
            "unique_count": r["unique_count"] or 0,
            "new_count": r["new_count"] or 0,
            "shortlisted_count": r["shortlisted_count"] or 0,
            "error": r["error"] or "",
            "new_job_ids": new_ids,
        })

    return jsonify({"scans": scans, "total": len(scans)})


@app.route("/api/scans/<int:scan_id>")
def api_scan_detail(scan_id):
    tracker = Tracker(DB_PATH)
    r = tracker.get_scan(scan_id)
    if not r:
        return jsonify({"error": "Scan history not found"}), 404

    started = r["started_at"] or ""
    finished = r["finished_at"] or ""
    duration = 0
    if started and finished:
        t1 = _parse_dt(started)
        t2 = _parse_dt(finished)
        if t1 and t2:
            duration = int(max(0, (t2 - t1).total_seconds()))

    job_rows = tracker.get_scan_jobs(scan_id)
    jobs = []
    for row in job_rows:
        loc = row["location"] or ""
        jobs.append({
            "id": row["id"],
            "title": row["title"] or "",
            "company": row["company"] or "",
            "location": loc,
            "city": _city_bucket(loc),
            "url": row["url"] or "",
            "source": row["source"] or "",
            "score": row["score"] or 0,
            "experience_level": row["experience_level"] or "",
            "status": row["status"] or "",
            "posted": freshness(row["posted_at"] or "", row["fetched_at"] or ""),
            "fetched_at": row["fetched_at"] or "",
            "description": (row["description"] or "").strip(),
            "salary": row["salary"] or "",
            "score_reason": row["score_reason"] or "",
            "applied_at": row["applied_at"] or "",
            "company_careers_url": row["company_careers_url"] or "",
            "scan_id": row["scan_id"] or 0,
        })

    return jsonify({
        "scan": {
            "id": r["id"],
            "mode": r["mode"] or "full",
            "sources": r["sources"] or "",
            "started_at": started,
            "finished_at": finished,
            "started_display": freshness("", started) if started else "",
            "duration_seconds": duration,
            "status": r["status"] or "",
            "fetched_count": r["fetched_count"] or 0,
            "unique_count": r["unique_count"] or 0,
            "new_count": r["new_count"] or 0,
            "shortlisted_count": r["shortlisted_count"] or 0,
            "error": r["error"] or "",
        },
        "jobs": jobs,
        "total_jobs": len(jobs)
    })


@app.route("/api/scans/<int:scan_id>/jobs")
def api_scan_jobs(scan_id):
    tracker = Tracker(DB_PATH)
    r = tracker.get_scan(scan_id)
    if not r:
        return jsonify({"error": "Scan history not found"}), 404

    job_rows = tracker.get_scan_jobs(scan_id)
    jobs = []
    for row in job_rows:
        loc = row["location"] or ""
        jobs.append({
            "id": row["id"],
            "title": row["title"] or "",
            "company": row["company"] or "",
            "location": loc,
            "city": _city_bucket(loc),
            "url": row["url"] or "",
            "source": row["source"] or "",
            "score": row["score"] or 0,
            "experience_level": row["experience_level"] or "",
            "status": row["status"] or "",
            "posted": freshness(row["posted_at"] or "", row["fetched_at"] or ""),
            "fetched_at": row["fetched_at"] or "",
            "description": (row["description"] or "").strip(),
            "salary": row["salary"] or "",
            "score_reason": row["score_reason"] or "",
            "applied_at": row["applied_at"] or "",
            "company_careers_url": row["company_careers_url"] or "",
            "scan_id": row["scan_id"] or 0,
        })
    return jsonify({"scan_id": scan_id, "jobs": jobs, "total": len(jobs)})


@app.route("/api/scans/<int:scan_id>/delete", methods=["POST", "DELETE"])
def api_delete_scan(scan_id):
    tracker = Tracker(DB_PATH)
    ok = tracker.delete_scan(scan_id)
    if not ok:
        return jsonify({"error": "Scan history not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/scans/clear_history", methods=["POST"])
def api_clear_scan_history():
    tracker = Tracker(DB_PATH)
    count = tracker.clear_scan_history()
    return jsonify({"deleted": count})


if __name__ == "__main__":
    print("Visit: http://localhost:5000")
    # use_reloader=False: the stat/watchdog reloader was picking up file-touch
    # events from unrelated stdlib/site-packages files (asyncio, fastmcp, etc.)
    # and restarting the whole process mid-scan, killing the in-process
    # background scan thread every time. Debug error pages still work fine
    # without the reloader — just restart manually after editing app.py.
    app.run(debug=True, port=5000, use_reloader=False)
