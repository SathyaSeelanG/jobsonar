# JobSonar — rules for AI coding agents

Conventions for any AI agent working in this repository. Human contributors
should read [CONTRIBUTING.md](../CONTRIBUTING.md) first — this file is the same
guidance compressed, plus the constraints agents most often get wrong.

## 1. What this project is

- **Description:** a self-hosted job search agent. It sweeps job boards, public
  ATS APIs and company career pages, deduplicates, scores every posting against
  the user's profile, and pre-fills applications the user submits themselves.
- **Stack:** Python 3.10+, Flask, Playwright (JS-rendered pages), BeautifulSoup
  (static parsing), SQLite, Tailwind via PostCSS.
- **Search scope is configuration, not code.** Queries, cities, board tokens and
  the company watchlist all live in `config/`. Never hardcode a role, city,
  company or skill in a `.py` file — if a change only makes sense for one user's
  search, it belongs in their `config/`, not in the repo.

Full internals: [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
Source-by-source detail: [docs/SOURCES.md](../docs/SOURCES.md).

## 2. Hard boundaries — do not cross

### 2.1 No personal data in tracked files

Private detail lives in exactly two places: **`.env.local`** (credentials) and
**`data/`** (job history, session cookies, exports). Both are git-ignored.

Never write a real name, email, phone number, API key, or absolute home path
(`C:\Users\…`, `/home/…`, `/Users/…`) into a tracked file. Platform-specific
paths come from `Path.home()` / `sys.platform` via `job_agent/util.py`. CI fails
the build if any of this appears in `git ls-files` — see
[SECURITY.md](../SECURITY.md).

### 2.2 Never auto-submit an application

`job_agent/autofill.py` fills fields and stops. The user reviews and clicks
submit. This is a product boundary, not a missing feature. Do not add
auto-submit, CAPTCHA solving, login bypassing, or bot-detection evasion, and do
not "helpfully" suggest them.

### 2.3 Scrape politely

Real User-Agent, delays between requests, per-query result caps. Do not remove
any of that to go faster, and do not raise `web_workers` defaults. Aggressive
scraping gets the user's IP banned and makes these sites right to block tooling
like this for everyone.

## 3. Coding rules

### 3.1 Sources must fail soft

Every fetcher returns `[]` on any error — never raises into the run. A dozen
third-party endpoints means something is broken at any given moment; one dead
selector must not abort a scan. `scraper._run_task()` is the safety net, but
handle errors in the source too so the report shows a useful message.

When parsing HTML, assume every tag is missing. Use `.get()`, `getattr`, or a
narrow `try/except`. One malformed listing must not take down a 250-company
batch.

### 3.2 Playwright and concurrency

Never spawn concurrent Chromium instances carelessly. For the large company
watchlist, reuse a single browser or run JS hydration sequentially — that's why
the `browser` and `final` stages are sequential while `api` and `web` are pooled.
Parallelising them will exhaust memory on a normal laptop.

Scans are slow by nature. Weigh any change against wall-clock and memory.

### 3.3 New sources default to off

A source that needs a credential, or whose selectors haven't been verified
against a live board, ships as `false` in `config/search.yaml`. Document any new
credential in `.env.example` with a **blank** value.

### 3.4 Filter overrides have three states

`job_agent/scoring.py` distinguishes `None` (use the default gate), `["all"]`/`[]`
(no gate), and a specific list (narrow). Collapsing `["all"]` into `None`
silently reapplies the default and looks like a filter that quietly doesn't work.
Preserve all three states through any layer you touch.

### 3.5 LLM features are optional

`llm.scoring` and `llm.tailoring` must degrade to no-ops when no backend is
reachable — keyword scoring stands, tailoring is skipped, nothing raises. Support
both providers (`anthropic` and an OpenAI-compatible self-hosted gateway); don't
hardcode either.

### 3.6 Keep the root clean

| Kind of file | Goes in |
|---|---|
| Standalone helper scripts | `scripts/` |
| Logs, debug HTML/PNG | `logs/`, `logs/debug/` |
| JSON dumps | `data/json_dumps/` |
| Excel exports | `data/exports/` |
| Run logs | `data/run_logs/` |
| Documentation | `docs/` (except the top-level markdown files) |

Never drop a temporary file in the repository root.

### 3.7 Frontend

`templates/` uses Tailwind (built via `npm run build:css`). Build every new
component or view **responsive from the start** — check ~320–375px as well as
desktop before calling it done. Keep the existing visual language: dark, modern,
generous spacing, restrained motion. No unstyled browser defaults.

### 3.8 Match the surrounding code

No repo-wide reformatting, no import reordering, no renaming for taste. Comments
explain *why*, not *what* — `job_agent/scoring.py` is the house style. Style is
not enforced by CI; consistency with the file you're editing is.

## 4. Before you say it works

```bash
python -m compileall -q app.py run.py job_agent scripts
python run.py scrape-report
```

Report real numbers, not "tested locally" — selectors and API assumptions are
guesswork until they run against a live board. If a source returned zero jobs,
say so; zero and broken look identical under the fail-soft contract.
