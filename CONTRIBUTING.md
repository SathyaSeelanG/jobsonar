# Contributing to JobSonar

Thanks for looking. JobSonar is a personal-scale tool, so the bar for
contributions is "does this help someone else's job hunt without making the
codebase harder to reason about."

## Ground rules

**Never commit personal data.** `.env.local`, `config/profile.yaml`, everything
under `data/`, and any `*_auth.json` are git-ignored for a reason. Before you
push, check:

```bash
git status --porcelain --ignored | grep -E '\.env|profile\.yaml|\.db|_auth\.json'
```

Every match should be prefixed `!!`. If not, stop. See [SECURITY.md](SECURITY.md).

**Never add auto-submit.** JobSonar pre-fills forms and hands over the browser.
Bulk auto-apply violates platform terms of service and gets real people's
accounts restricted. PRs that submit applications without a human click will be
closed.

**Scrape politely.** New sources must fail soft (return `[]`, never raise into
the run), respect delays and backoff, and not attempt to defeat CAPTCHAs, bot
detection, logins, or paywalls.

## Setup

```bash
git clone https://github.com/SathyaSeelanG/jobsonar.git
cd jobsonar
python -m venv .venv && . .venv/Scripts/activate   # Linux/macOS: . .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env.local
cp config/profile.example.yaml config/profile.yaml
```

Sanity check without touching your database:

```bash
python run.py scrape-report
```

## The highest-value contributions

In rough order of usefulness:

1. **New ATS adapters.** A single public ATS API covers every company on that
   platform. Notable gaps: Zoho Recruit, Darwinbox, Freshteam, Workable, Oracle
   Fusion, SuccessFactors, Taleo, PeopleStrong — all common outside the US and
   none currently detected.
2. **ATS detection signatures.** `job_agent/sources/ats_detect.py` recognizes 11
   platforms by URL pattern. Anything not on that list falls back to generic HTML
   heuristics and yields much less.
3. **Better experience-level and location inference.** `job_agent/scoring.py` is
   where good postings get wrongly dropped or bad ones let through.
4. **Career-page parsers** for boards that are neither a known ATS nor JSON-LD.

### Adding a source

1. Write `fetch_<name>(...) -> list[Job]` in `job_agent/sources/`. Return `[]`
   on any failure — never let an exception escape into the run.
2. Export it from `job_agent/sources/__init__.py`.
3. Register it in the right stage in `job_agent/scraper.py` (`api`, `web`,
   `browser`, or `final`).
4. Add a `sources:` toggle in `config/search.yaml`, defaulting to `false` if it
   needs a key or is unverified.
5. Document it in `docs/SOURCES.md`.
6. If it needs a credential, add the key name to `.env.example` with a blank
   value and a comment linking to where to get it.

New sources should be **off by default** unless they work with no key and no
setup.

## Code style

Match the file you're editing. Broadly:

- Standard library first, third-party next, local last.
- Type hints on new function signatures.
- Comments explain *why*, not *what*. The existing comments in `scoring.py` are
  the house style: they record the reasoning and the failure mode that motivated
  the code. Keep that.
- No new runtime dependencies without a reason in the PR description.
- Don't reformat code you aren't otherwise changing — it buries the real diff.

## Pull requests

- One concern per PR.
- Say what you actually ran to verify it. "Ran `python run.py scrape-report`,
  greenhouse returned 394 jobs across 8 boards" beats "tested locally."
- If you touched a scraper or ATS adapter, include the real counts you observed.
  Selectors are guesswork until someone runs them against a live board.
- Update `docs/` and `README.md` when behavior or configuration changes.

## Reporting bugs

Use the issue templates. For a scraper returning nothing, please include the
source name, the query and location, and the relevant lines from
`data/run_logs/` — **with any personal details removed**.

## Code of Conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
