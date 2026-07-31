<h1 align="center">JobSonar</h1>

<p align="center">
  <em>Ping every job source at once. Keep only the ones worth your time.</em>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg">
  <a href="https://github.com/SathyaSeelanG/jobsonar/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/SathyaSeelanG/jobsonar/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Self-hosted" src="https://img.shields.io/badge/hosting-self--hosted-green.svg">
</p>

---

JobSonar is a self-hosted job-search agent. One scan sweeps job boards, public
ATS APIs and a watchlist of company career pages in parallel, scores every
posting against your own profile, drops the stale and the mis-levelled, and
leaves you a ranked shortlist in a local web UI.

It never auto-submits an application. It fills the form and hands you the
browser — so there is no ToS violation and no account-ban risk.

**Everything stays on your machine.** No account, no server, no telemetry. Your
job history lives in a local SQLite file; your credentials live in a git-ignored
`.env.local`.

## Why

Job boards each show you a slice, and the good postings — especially entry-level
ones — often never reach an aggregator at all. They sit on a company's own
Greenhouse/Lever/Ashby board for a few days and get filled. Checking 250 career
pages by hand every morning is not a plan. JobSonar does that sweep in a couple
of minutes and tells you only what's new.

## What a scan actually does

```
      ┌── job boards ────────── SimplyHired · LinkedIn · TimesJobs · Naukri
      ├── aggregator APIs ───── JSearch · Adzuna
scan ─┼── public ATS feeds ──── Greenhouse · Lever · Ashby · SmartRecruiters · Rippling · Keka
      ├── remote-only APIs ──── Arbeitnow · Remotive · RemoteOK · Jobicy
      └── company watchlist ─── ~250 career pages, ATS-detected then parsed
                │
                ▼
        dedupe (URL + normalized title/company)
                │
                ▼
        filter   role · experience level · location · posting age
                │
                ▼
        score    keyword match vs. your skills, then optional LLM pass
                │
                ▼
        track    new-only, in SQLite  ──►  web UI / CLI / Excel export
                │
                ▼
        apply    browser opens, form pre-filled, YOU click submit
```

## Features

- **Parallel multi-source scan** — four stages (`api`, `web`, `browser`,
  `final`) run on thread pools; a slow or blocked source fails soft instead of
  sinking the run.
- **Public ATS APIs, not scraping** — Greenhouse, Lever and Ashby expose clean
  JSON job feeds. Add a company's board token and you get its postings
  first-hand, usually before any aggregator indexes them.
- **Company watchlist** — point it at a list of companies; it resolves each
  homepage to its careers page, detects which ATS is behind it, and extracts
  individual jobs (falling back to JSON-LD, `__NEXT_DATA__`, then page
  heuristics).
- **Experience-level inference** — reads titles *and* descriptions for year
  ranges ("1–2 years", "5+ years") so senior roles stop drowning out
  entry-level ones. Defaults to fresher + junior; configurable per scan.
- **Freshness gate** — defaults to postings from the last 3 days, because a
  three-week-old listing is usually already filled.
- **Only-new tracking** — deduped against everything you've already seen, so a
  daily scan shows you the delta, not the same 400 jobs again.
- **Live web UI** — start a scan from the browser and watch per-source progress
  stream in; filter, shortlist, and mark applied/skipped.
- **Optional LLM scoring & tailoring** — refine scores and generate tailored
  resume bullets + cover letters per job. Works with the Anthropic API or a
  self-hosted OmniRoute gateway. Tailoring rephrases only what's in your
  profile; it never invents experience.
- **Assisted apply, never auto-apply** — a real browser opens with the form
  pre-filled. You review and submit.

## Quick start

Requires **Python 3.10+**.

```bash
git clone https://github.com/SathyaSeelanG/jobsonar.git
cd jobsonar
pip install -r requirements.txt
playwright install chromium
```

Set up your two config files:

```bash
cp .env.example .env.local
cp config/profile.example.yaml config/profile.yaml
```

- `.env.local` — API keys. **Every one is optional**; JobSonar runs with none
  set, using the keyless scrapers, the public ATS feeds and the watchlist.
- `config/profile.yaml` — your skills, contact details and default form
  answers. This is what postings get scored against, so fill in `skills.core`
  honestly.
- `config/search.yaml` — the roles, cities and sources to scan. Edit `queries`
  and `locations` first; the shipped values are an example, not a default you
  should keep.

Both `.env.local` and `config/profile.yaml` are git-ignored — see
[SECURITY.md](SECURITY.md).

Then run it:

```bash
python app.py
```

Open <http://localhost:5000>, hit **Scan**, and watch the sources report in.

## CLI

```bash
python run.py search          # fetch + score + store new jobs
python run.py list            # review the shortlist
python run.py show <ID>       # full detail for one job
python run.py tailor          # write resume bullets + cover letter per shortlisted job
python run.py apply <ID>      # open browser with the form pre-filled — you submit
python run.py mark <ID> skipped "not remote"
python run.py export          # tracker.xlsx
python run.py scrape-report   # per-source coverage report, no state changes
```

Run `search` on a schedule (cron / Task Scheduler) to catch postings on their
first day.

## Configuration

| File | Tracked in git? | What it holds |
|---|---|---|
| `.env.example` | ✅ | Documented list of every supported key, no values |
| `.env.local` | ❌ | **Your real API keys.** Loaded last, overrides `.env` |
| `config/search.yaml` | ✅ | Queries, locations, source toggles, ATS board tokens, thresholds |
| `config/profile.example.yaml` | ✅ | Template profile with placeholders |
| `config/profile.yaml` | ❌ | **Your** name, contact, skills, form answers |
| `config/companies.yaml` | ✅ | Career-page watchlist (company name + homepage) |
| `data/jobs.db` | ❌ | Your scan history and application state |

Full reference: **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.
Source-by-source detail: **[docs/SOURCES.md](docs/SOURCES.md)**.
Internals: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

### Retargeting it to you

JobSonar ships configured for entry-level JavaScript/Python roles in Chennai,
India — that's the author's search, and it's there so you can see a real working
config. To make it yours, three edits:

1. `config/search.yaml` → `queries` and `locations`.
2. `config/profile.yaml` → `skills.core` and `skills.secondary`.
3. `config/companies.yaml` → the companies you'd actually work for.

Nothing about the pipeline is city- or stack-specific.

## Adding an ATS board

The highest-leverage thing you can do. One board token typically yields tens of
jobs straight from the source:

```yaml
# config/search.yaml
greenhouse_boards: [tekion, appian, fourkites]   # boards.greenhouse.io/<token>
lever_boards:      [dozee, nium]                 # jobs.lever.co/<token>
ashby_boards:      [netgear]                     # jobs.ashbyhq.com/<name>
```

Find the token by opening a company's "Careers" page and looking at where the
job links point.

## Legal & etiquette

- Scrapers use polite delays, rotate user-agents, and back off on 403/429.
  Keep scan frequency reasonable — this is built for one person's job hunt, not
  for bulk data collection.
- JobSonar reads public listings only. It does not bypass paywalls, logins,
  CAPTCHAs, or bot detection.
- The LinkedIn feed scanner is read-only and off by default. It never posts or
  comments. Bulk auto-apply is deliberately not implemented: it violates
  platform terms and gets accounts restricted.
- Site markup changes. Scrapers fail soft (return 0 results) rather than
  crashing a run; the ATS APIs are the stable path.

## Contributing

Issues and PRs welcome — especially new ATS adapters and career-page parsers.
See **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## License

[MIT](LICENSE)
