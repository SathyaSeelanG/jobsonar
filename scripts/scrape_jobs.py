"""Standalone job scraper entrypoint."""
from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from job_agent.cli import ROOT
from job_agent.util import load_env
from job_agent.scraper import (
    dedupe_jobs,
    flatten_jobs,
    print_report,
    run_scrape,
    save_jobs_csv,
    save_jobs_json,
    save_jobs_sqlite,
    save_run_report_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone job scraper")
    parser.add_argument("--fast", action="store_true", help="Limit to a smaller fast run")
    parser.add_argument("--apis-only", action="store_true", help="Run only API-backed sources")
    parser.add_argument("--web-only", action="store_true", help="Run only direct web scrapers")
    parser.add_argument("--watchlist-only", action="store_true", help="Run only the company watchlist")
    parser.add_argument("--query-limit", type=int, default=0, help="Limit query count")
    parser.add_argument("--location-limit", type=int, default=0, help="Limit location count")
    parser.add_argument("--company-limit", type=int, default=0, help="Limit company watchlist count")
    parser.add_argument("--json-out", default="data/standalone_jobs.json", help="JSON output path")
    parser.add_argument("--csv-out", default="data/standalone_jobs.csv", help="CSV output path")
    parser.add_argument("--sqlite-out", default="data/standalone_jobs.db", help="SQLite output path")
    parser.add_argument("--report-out", default="data/standalone_report.json", help="Run report output path")
    parser.add_argument("--no-save", action="store_true", help="Do not write output files")
    return parser


def load_cfg() -> dict:
    import yaml

    load_env(ROOT)
    cfg = yaml.safe_load((ROOT / "config" / "search.yaml").read_text(encoding="utf-8"))
    cfg["_root"] = ROOT
    cfg["_companies_path"] = ROOT / "config" / "companies.yaml"
    return cfg


def apply_flags(cfg: dict, args: argparse.Namespace) -> None:
    if args.fast:
        cfg["_stages"] = ["api", "web"]
        cfg["_query_limit"] = args.query_limit or 2
        cfg["_location_limit"] = args.location_limit or 1
    if args.apis_only:
        cfg["_stages"] = ["api"]
    if args.web_only:
        cfg["_stages"] = ["web"]
    if args.watchlist_only:
        cfg["_stages"] = ["final"]
        cfg["sources"]["watchlist"] = True
    if args.query_limit:
        cfg["_query_limit"] = args.query_limit
    if args.location_limit:
        cfg["_location_limit"] = args.location_limit
    if args.company_limit:
        cfg["watchlist_company_limit"] = args.company_limit


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    console = Console()
    cfg = load_cfg()
    apply_flags(cfg, args)

    results = run_scrape(cfg, console)
    jobs = dedupe_jobs(flatten_jobs(results))

    print_report(console, results)
    console.print(f"[green]Collected {len(jobs)} unique job(s).[/green]")

    if not args.no_save:
        json_path = Path(args.json_out)
        csv_path = Path(args.csv_out)
        sqlite_path = Path(args.sqlite_out)
        report_path = Path(args.report_out)
        save_jobs_json(json_path, jobs)
        save_jobs_csv(csv_path, jobs)
        save_jobs_sqlite(sqlite_path, jobs)
        save_run_report_json(report_path, results, jobs)
        console.print(f"[green]Saved JSON to {json_path}[/green]")
        console.print(f"[green]Saved CSV to {csv_path}[/green]")
        console.print(f"[green]Saved SQLite to {sqlite_path}[/green]")
        console.print(f"[green]Saved run report to {report_path}[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
