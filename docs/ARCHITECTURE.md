# Architecture

JobSonar is a single-process Python application with two front ends over one
shared core. There is no server component, no queue, no external service. A scan
is a function call that fans out over thread pools and writes to a local SQLite
file.

```
                    ┌──────────────┐     ┌─────────────┐
front ends          │   app.py     │     │   run.py    │
                    │ Flask web UI │     │     CLI     │
                    └──────┬───────┘     └──────┬──────┘
                           └────────┬───────────┘
                                    ▼
core                        job_agent/scraper.py          orchestration
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
                 sources/        scoring.py      tracker.py
              fetch & scrape    filter & rank    SQLite + Excel
                                    │
                                    ▼
                                 llm.py          optional refinement
                                 tailor.py       optional generation
```

## Module map

| Module | Responsibility |
|---|---|
| [`app.py`](../app.py) | Flask app: pages, JSON API, background scan thread, live progress |
| [`run.py`](../run.py) | Thin entry point → `job_agent/cli.py` |
| [`job_agent/cli.py`](../job_agent/cli.py) | Commands: `scrape-report`, `scan`, `tailor`, `export`, `linkedin-login`, … |
| [`job_agent/scraper.py`](../job_agent/scraper.py) | Stage orchestration, parallel fan-out, dedupe, report |
| [`job_agent/sources/`](../job_agent/sources/) | One module per family of source. See [SOURCES.md](SOURCES.md) |
| [`job_agent/scoring.py`](../job_agent/scoring.py) | Filter gates + keyword score |
| [`job_agent/models.py`](../job_agent/models.py) | The `Job` dataclass and its identity keys |
| [`job_agent/tracker.py`](../job_agent/tracker.py) | SQLite persistence, status transitions, Excel export |
| [`job_agent/llm.py`](../job_agent/llm.py) | Optional LLM scoring (Anthropic or a self-hosted gateway) |
| [`job_agent/tailor.py`](../job_agent/tailor.py) | Optional resume-bullet / cover-letter generation |
| [`job_agent/autofill.py`](../job_agent/autofill.py) | Pre-fills an application form. **Never submits.** |
| [`job_agent/util.py`](../job_agent/util.py) | Env/profile loading, platform path defaults, freshness, URL liveness |

## A scan, end to end

### 1. Config load

`load_env(root)` reads `.env` then `.env.local` with `override=True`, so
`.env.local` always wins. `load_profile(root)` reads `config/profile.yaml` and
falls back to `config/profile.example.yaml` — a fresh clone runs without any
copy step. Both live in `util.py` so the web UI, the CLI and the standalone
scripts can't drift apart on how config is discovered.

### 2. Staged fan-out

`run_scrape()` builds a task list — one callable per (source × query × location)
combination — and groups it into four stages:

| Stage | Contents | Concurrency |
|---|---|---|
| `api` | ATS APIs, Adzuna, JSearch, keyless remote APIs | `api_workers` (12) |
| `web` | LinkedIn / SimplyHired / TimesJobs HTML | `web_workers` (8) |
| `browser` | Playwright-driven sources | sequential |
| `final` | Company watchlist | `watchlist_workers` (15) |

`api` and `web` run on `ThreadPoolExecutor`; `browser` and `final` run
sequentially, because a browser source contends for a single Chrome instance and
the watchlist manages its own internal pool.

Callers can restrict stages with `cfg["_stages"]` — that's how the web UI's
"quick scan" skips `browser` and `final` and finishes in seconds instead of
minutes.

Each task is wrapped by `_run_task()`, which catches **every** exception and
returns a `SourceResult(name, jobs=[], duration_s, error)`. This is the fail-soft
contract: a broken source costs you its jobs and nothing else. Timings and
per-source counts are what `print_report()` shows.

A `progress_callback` fires as each task completes. That's the mechanism behind
the live scan view — the Flask route pushes those events into an in-memory
status dict that the Alpine.js front end polls.

### 3. Deduplication

`Job` exposes two identity keys, both in [`models.py`](../job_agent/models.py):

- **`id`** — SHA-1 of `title|company|url`. Exact identity; the SQLite primary key.
- **`fuzzy_key`** — SHA-1 of title+company with all non-alphanumerics stripped.

The fuzzy key is what makes the multi-source design tolerable. The same posting
reaches you from Greenhouse, LinkedIn and SimplyHired with three different URLs
and three different `id`s; normalising away punctuation and case collapses them
to one row. `dedupe_jobs()` keeps the first occurrence, and because stages run in
order, the first occurrence is the one from the highest-quality source.

### 4. Filter, then score

Four gates run before scoring ([`scoring.py`](../job_agent/scoring.py)): role,
experience level, location, freshness. Filtering first matters — scoring is the
expensive part once the LLM is involved, and there's no point scoring a job
that's already disqualified.

Each gate reads its override the same way:

```python
None        → use the built-in default
["all"]/[]  → gate disabled
["a","b"]   → narrow to exactly these
```

`_wants_all()` (public alias `wants_all`) is the single place that distinction is
decided. Keeping all three states distinct is deliberate: a caller that can only
say "default or narrow" has no way to express *"show me everything"*, and
collapsing `["all"]` into `None` would silently reapply the default gate — a bug
that looks like a filter quietly not working. Front ends must translate their own
"all" sentinel to `None` when they mean the default and pass `["all"]` through
when they mean no gate.

Then `score_job()` produces 0–100 from your profile's skills, with a title bonus
and an experience-level adjustment. The formula is documented in
[CONFIGURATION.md](CONFIGURATION.md#how-skills-becomes-a-score).

### 5. Persist

`Tracker` opens `data/jobs.db` and applies `SCHEMA` idempotently
(`CREATE TABLE IF NOT EXISTS`) plus indexes on `fuzzy_key`, `scan_id` and
`apply_type`. Two tables:

- **`jobs`** — one row per unique posting, plus your workflow state:
  `status` (`new` → `shortlisted` → `tailored` → `applied` / `skipped`),
  `applied_at`, `notes`, `tailored_path`.
- **`scan_history`** — one row per scan: mode, sources, timings, status, the
  fetched/unique/new/shortlisted counts, and `new_job_ids` as a JSON array.

Re-scanning is safe. An existing `id` updates the posting's fields but never
resets your status, so a job you already marked applied stays applied.

`scan_history.new_job_ids` is what lets the UI answer *"what changed since last
time"* without diffing the whole table.

### 6. Optional LLM

If `llm.scoring` is on and a backend is reachable, shortlisted jobs get a refined
score and a short reason. If `llm.tailoring` is on, `tailor.py` drafts resume
bullets and a cover letter into `applications/`. Both degrade to no-ops when the
backend is absent — the keyword score stands and nothing raises. The provider is
either Anthropic's API or an OpenAI-compatible self-hosted gateway.

## Design decisions worth knowing

**Everything is local.** SQLite file, local Flask process, no telemetry, no
account. Your search history is a file you can delete.

**Nothing is ever auto-submitted.** `autofill.py` fills fields and stops; you
review and click submit. This is a hard product boundary, not a missing feature —
PRs adding auto-submit are closed. Employers are entitled to a real application
from a real person, and mass-submission is how these sites justify blocking
tooling like this for everyone.

**Sources fail soft, always.** Roughly a dozen HTML scrapers and third-party APIs
means something is broken at any given moment. The alternative — one dead
selector aborting the run — makes the tool useless in exactly the situation it's
needed.

**No machine-specific paths in source.** Chrome binary and profile locations come
from `Path.home()` / `sys.platform` via `util.py`, overridable in config. CI
fails the build if a literal home directory appears in a tracked file.

**Private data lives in exactly two places:** `.env.local` (credentials) and
`data/` (your job history, session cookies, exports). Both are git-ignored, and a
dedicated CI job fails the build if either becomes tracked. See
[SECURITY.md](../SECURITY.md).

## Where to make changes

| Goal | Touch |
|---|---|
| Add an ATS or job board | `job_agent/sources/`, then wire it in `scraper.py` |
| Teach ATS auto-detection a new platform | `ats_detect.py` → `ATS_SIGNATURES` |
| Change what qualifies as a match | `scoring.py` |
| Add a stored field | `models.py` (`Job`) + `tracker.py` (`SCHEMA`) |
| Add a UI view | `templates/` + a route in `app.py` |
| Add a CLI command | `job_agent/cli.py` |

The step-by-step recipe for a new source is in
[CONTRIBUTING.md](../CONTRIBUTING.md).
