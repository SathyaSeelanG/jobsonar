"""job-agent CLI.

  python run.py search           # fetch + score + store new jobs
  python run.py scrape-report    # run standalone scraper and print per-source results
  python run.py list             # show shortlisted jobs
  python run.py list fresher      # only fresher-level jobs, newest first
  python run.py list junior       # only junior/1-2yr jobs, newest first
  python run.py companies        # list all tracked companies and their ATS platform
  python run.py tailor           # generate resume bullets + cover letters for shortlist
  python run.py apply ID         # open job in browser, pre-fill form (you submit)
  python run.py mark ID applied|skipped [note]
  python run.py rescore          # re-score all stored jobs
  python run.py export           # tracker.xlsx
  python run.py linkedin-login   # one-time: save a LinkedIn session for feed scanning
  python run.py naukri-login     # print Naukri CDP setup instructions
  python run.py naukri-search    # run ONLY Naukri auth search (auto-launches Chrome)
"""
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from .models import Job
from .scraper import print_report, run_scrape
from .scoring import keyword_score, llm_score
from .tracker import Tracker
from .util import default_chrome_binary, default_chrome_user_data_dir, load_env, load_profile

ROOT = Path(__file__).resolve().parent.parent
console = Console()


def load_cfg():
    load_env(ROOT)
    profile = load_profile(ROOT)
    search = yaml.safe_load((ROOT / "config" / "search.yaml").read_text(encoding="utf-8"))
    return profile, search


def get_tracker() -> Tracker:
    return Tracker(ROOT / "data" / "jobs.db")


def cmd_search():
    profile, cfg = load_cfg()
    tracker = get_tracker()
    cfg["_root"] = ROOT
    cfg["_companies_path"] = ROOT / "config" / "companies.yaml"
    with console.status("Fetching jobs..."):
        source_results = run_scrape(cfg, console)
    jobs = [job for result in source_results for job in result.jobs]

    new, min_score = 0, cfg.get("min_score", 40)
    llm_cfg = cfg.get("llm", {}) or {}
    from .llm import available as llm_available
    use_llm = llm_cfg.get("scoring") and llm_available(llm_cfg)

    for job in jobs:
        job.score, job.score_reason = keyword_score(job, profile)
        if job.score >= min_score:
            job.status = "shortlisted"
            if use_llm:
                refined = llm_score(job, profile, llm_cfg)
                if refined:
                    job.score, job.score_reason = refined
                    job.status = "shortlisted" if job.score >= min_score else "new"
        if tracker.upsert(job):
            new += 1

    short = len(tracker.by_status("shortlisted"))
    console.print(f"\n[green]Fetched {len(jobs)} jobs, {new} new. {short} total shortlisted.[/green]")
    if source_results:
        print_report(console, source_results)
        summary = ", ".join(f"{result.name}={result.count}" for result in source_results if result.count)
        if summary:
            console.print(f"[dim]Source counts: {summary}[/dim]")
    console.print("Run [bold]python run.py list[/bold] to review.")


def cmd_scrape_report(*args):
    _, cfg = load_cfg()
    cfg["_root"] = ROOT
    cfg["_companies_path"] = ROOT / "config" / "companies.yaml"
    extra = list(args) or sys.argv[2:]
    if "--fast" in extra:
        cfg["_stages"] = ["api", "web"]
        cfg["_query_limit"] = 2
        cfg["_location_limit"] = 1
    if "--apis-only" in extra:
        cfg["_stages"] = ["api"]
    if "--web-only" in extra:
        cfg["_stages"] = ["web"]
    if "--watchlist-only" in extra:
        cfg["_stages"] = ["final"]
        cfg["sources"]["watchlist"] = True
    results = run_scrape(cfg, console)
    total = sum(result.count for result in results)
    print_report(console, results)
    console.print(f"[green]Standalone scraper collected {total} job(s).[/green]")


def cmd_list(*args):
    """python run.py list                 — all shortlisted, best score first
    python run.py list fresher           — only fresher-level jobs, newest first
    python run.py list junior|mid|senior — same, filtered to that level
    """
    from .util import freshness

    level = (args[0].lower() if args else "").strip()
    valid_levels = {"fresher", "junior", "mid", "senior", "lead"}
    if level not in valid_levels:
        level = ""

    tracker = get_tracker()
    title = f"Shortlisted jobs — {level}" if level else "Shortlisted jobs"
    table = Table(title=title)
    for col in ("ID", "Score", "Level", "Posted", "Title", "Company", "Location", "Status", "Source"):
        table.add_column(col)

    rows = [r for s in ("shortlisted", "tailored", "applied")
            for r in tracker.by_status(s, experience_level=level)]

    if level:
        # Freshness matters most when hunting fresher/junior openings —
        # newest postings first instead of score-first.
        rows.sort(key=lambda r: r["posted_at"] or r["fetched_at"] or "", reverse=True)

    for r in rows[:40]:
        exp = r["experience_level"] or ""
        age = freshness(r["posted_at"] or "", r["fetched_at"] or "")
        table.add_row(r["id"][:8], str(r["score"]), exp, age, r["title"][:40], r["company"][:22],
                      r["location"][:20], r["status"], r["source"])
    console.print(table)
    if not rows:
        console.print("[yellow]No matches. Run `python run.py rescore` if you added jobs before "
                       "the level-detection fix, then try again.[/yellow]")
    console.print("[dim]apply: python run.py apply <ID>   details: python run.py show <ID>   "
                  "filter: python run.py list fresher[/dim]")


def cmd_companies():
    """List all tracked companies and their detected ATS platform."""
    config_path = ROOT / "config" / "companies.yaml"
    if not config_path.exists():
        console.print("[red]No companies.yaml found[/red]")
        return
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    companies = cfg.get("companies", [])

    table = Table(title=f"Company Watchlist ({len(companies)} companies)")
    for col in ("Company", "ATS", "Board Token", "Careers URL", "JS Rendered"):
        table.add_column(col)

    for entry in companies:
        ats = entry.get("ats", "")
        token = entry.get("board_token", "")
        careers = entry.get("careers_url_override", "")
        js = "yes" if entry.get("js_rendered") else ""
        table.add_row(
            entry["name"],
            ats or "(auto-detect)",
            token or "-",
            careers or "-",
            js,
        )
    console.print(table)


def cmd_show(job_id: str):
    from .util import freshness

    r = get_tracker().get(job_id)
    if not r:
        console.print("[red]Not found[/red]")
        return
    exp = r["experience_level"] or ""
    age = freshness(r["posted_at"] or "", r["fetched_at"] or "")
    console.print(f"[bold]{r['title']}[/bold] — {r['company']} ({r['location']})")
    console.print(f"Score {r['score']}: {r['score_reason']}")
    if exp:
        console.print(f"Level: {exp}")
    if age:
        console.print(f"Posted: {age}")
    console.print(f"URL: {r['url']}")
    if r["company_careers_url"]:
        console.print(f"Careers: {r['company_careers_url']}")
    console.print()
    console.print(r["description"][:2000])


def cmd_tailor():
    from .tailor import tailor
    from .util import check_url_live
    profile, cfg = load_cfg()
    tracker = get_tracker()
    llm_cfg = cfg.get("llm", {}) or {}
    out_dir = ROOT / "applications"
    rows = tracker.by_status("shortlisted", cfg.get("min_score", 40))
    if not rows:
        console.print("Nothing shortlisted. Run search first.")
        return
    for r in rows:
        if not check_url_live(r["url"]):
            tracker.set(r["id"], status="stale", notes="posting no longer live (404/410)")
            console.print(f"  [yellow]Stale, skipping: {r['title']} @ {r['company']}[/yellow]")
            continue
        job = Job(title=r["title"], company=r["company"], location=r["location"],
                  url=r["url"], description=r["description"], score=r["score"])
        console.print(f"Tailoring: {job.title} @ {job.company}...")
        path = tailor(job, profile, llm_cfg, out_dir)
        if path:
            tracker.set(r["id"], status="tailored", tailored_path=str(path))
            console.print(f"  [green]-> {path.name}[/green]")
        else:
            console.print("  [yellow]Skipped — configure OmniRoute in search.yaml[/yellow]")
            break


def cmd_apply(job_id: str):
    from .autofill import apply_semi_auto
    from .util import check_url_live
    profile, _ = load_cfg()
    tracker = get_tracker()
    r = tracker.get(job_id)
    if not r:
        console.print("[red]Not found[/red]")
        return
    if not check_url_live(r["url"]):
        tracker.set(r["id"], status="stale", notes="posting no longer live (404/410)")
        console.print("[yellow]This posting looks dead (404/410) — marked stale.[/yellow]")
        if input("Open anyway? [y/N] ").strip().lower() != "y":
            return
    console.print(f"Opening: {r['title']} @ {r['company']}")
    apply_semi_auto(r["url"], profile)
    if input("Mark as applied? [y/N] ").strip().lower() == "y":
        from datetime import datetime, timezone
        tracker.set(r["id"], status="applied", applied_at=datetime.now(timezone.utc).isoformat())
        console.print("[green]Marked applied.[/green]")


def cmd_mark(job_id: str, status: str, note: str = ""):
    tracker = get_tracker()
    r = tracker.get(job_id)
    if not r:
        console.print("[red]Not found[/red]")
        return
    tracker.set(r["id"], status=status, notes=note)
    console.print(f"{r['title']} -> {status}")


def cmd_rescore():
    """Re-run keyword scoring on every stored job (e.g. after scoring changes)."""
    from .sources.ats import infer_experience_level

    profile, cfg = load_cfg()
    tracker = get_tracker()
    min_score = cfg.get("min_score", 40)
    promoted = 0
    for r in tracker.all():
        # Recompute experience_level from scratch rather than trusting the stored
        # value — a stale/misclassified level (e.g. from a bug later fixed in
        # infer_experience_level) would otherwise survive every rescore forever,
        # since keyword_score() only infers when experience_level is blank.
        exp_level = infer_experience_level(r["title"], r["description"] or "")
        job = Job(title=r["title"], company=r["company"], description=r["description"] or "",
                  experience_level=exp_level)
        score, reason = keyword_score(job, profile)
        status = r["status"]
        if status in ("new", "shortlisted"):
            status = "shortlisted" if score >= min_score else "new"
            if status == "shortlisted" and r["status"] == "new":
                promoted += 1
        tracker.set(r["id"], score=score, score_reason=reason, status=status,
                    experience_level=job.experience_level)
    console.print(f"[green]Rescored {len(tracker.all())} jobs, {promoted} newly shortlisted.[/green]")


def cmd_export():
    path = ROOT / "tracker.xlsx"
    get_tracker().export_xlsx(path)
    console.print(f"[green]Exported {path}[/green]")


def cmd_linkedin_login():
    """One-time interactive login — opens a real browser window for you to
    log into LinkedIn, then saves the session for headless feed scanning."""
    from .sources.linkedin_feed import save_linkedin_session
    _, cfg = load_cfg()
    state_path = ROOT / (cfg.get("linkedin_feed") or {}).get("state_path", "data/linkedin_auth.json")
    save_linkedin_session(state_path)
    console.print("[green]Done. Set linkedin_feed.enabled: true in search.yaml to use it in `search`.[/green]")


def cmd_naukri_login():
    """Print setup instructions for Naukri CDP (Chrome Debugging Protocol) auth."""
    console.print("""[bold]Naukri CDP Setup[/bold]

This connects to your [u]already-running[/u] Chrome where Naukri is logged in.

[bold]1.[/bold] Close all Chrome windows.
[bold]2.[/bold] Launch Chrome with remote debugging:
      [dim]"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222[/dim]
[bold]3.[/bold] In that window, go to [cyan]https://www.naukri.com[/cyan] and log in.
[bold]4.[/bold] Keep Chrome running.
[bold]5.[/bold] Set [green]naukri_auth.enabled: true[/green] in [cyan]config/search.yaml[/cyan].
[bold]6.[/bold] Run [bold]python run.py search[/bold].

The agent will connect to your Chrome via CDP and search Naukri as you.
No manual re-login needed on subsequent runs — just keep Chrome running.""")


def cmd_naukri_search():
    """Run ONLY Naukri authenticated search (auto-launches Chrome)."""
    from .sources.naukri_auth import search_naukri_auth

    profile, cfg = load_cfg()
    na_cfg = cfg.get("naukri_auth") or {}
    locations = cfg.get("locations", [])
    naukri_location = locations[0] if locations else "Chennai"

    with console.status("Launching Chrome + searching Naukri..."):
        jobs = search_naukri_auth(
            cdp_port=na_cfg.get("cdp_port", 9222),
            queries=cfg.get("queries", []),
            location=naukri_location,
            max_results=na_cfg.get("max_results", 20),
            chrome_path=na_cfg.get("chrome_path") or default_chrome_binary(),
            user_data_dir=na_cfg.get("user_data_dir") or default_chrome_user_data_dir(),
            profile_directory=na_cfg.get("profile_directory", "Default"),
        )

    if not jobs:
        console.print("[yellow]No jobs found from Naukri.[/yellow]")
        return

    from .scoring import keyword_score
    from .tracker import Tracker

    tracker = Tracker(ROOT / "data" / "jobs.db")
    min_score = cfg.get("min_score", 40)
    new = 0

    for job in jobs:
        job.score, job.score_reason = keyword_score(job, profile)
        if job.score >= min_score:
            job.status = "shortlisted"
        if tracker.upsert(job):
            new += 1

    console.print(f"[green]Naukri: {len(jobs)} jobs found, {new} new ({sum(1 for j in jobs if j.score >= min_score)} shortlisted).[/green]")
    console.print("Run [bold]python run.py list[/bold] to review.")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    commands = {
        "search": cmd_search, "scrape-report": cmd_scrape_report,
        "list": cmd_list, "companies": cmd_companies,
        "tailor": cmd_tailor, "export": cmd_export, "rescore": cmd_rescore,
        "show": cmd_show, "apply": cmd_apply, "mark": cmd_mark,
        "linkedin-login": cmd_linkedin_login,
        "naukri-login": cmd_naukri_login,
        "naukri-search": cmd_naukri_search,
    }
    if cmd in commands:
        commands[cmd](*rest)
    else:
        print(__doc__)
