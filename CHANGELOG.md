# Changelog

All notable changes to JobSonar are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet. Open a [new-source issue](https://github.com/SathyaSeelanG/jobsonar/issues/new?template=new_source.yml)
if there's an ATS you want covered.

## [1.0.0] — 2026-07-31

First public release.

### Added

- **Multi-stage parallel scan pipeline** (`job_agent/scraper.py`) across four
  stages — `api`, `web`, `browser`, `final` — with per-stage worker pools and a
  fail-soft contract: any source that errors returns no jobs instead of aborting
  the run.
- **Public ATS integrations**, no credentials required: Greenhouse, Lever
  (with EU-region fallback), Ashby, SmartRecruiters, Rippling, Keka and Workday.
- **Company career-page watchlist** with a fallback cascade — ATS auto-detection
  → JSON-LD `JobPosting` → Next.js `__NEXT_DATA__` → static HTML → Playwright
  render → page-level keyword signal. Finds companies that never post to a job
  board at all.
- **ATS auto-detection** from 11 URL signatures: Greenhouse, Lever, Ashby,
  SmartRecruiters, Workday, Rippling, Keka, BambooHR, Recruitee, Personio, Breezy.
- **Aggregator APIs**: Adzuna and JSearch (both optional, free tier).
- **Keyless remote-job APIs**: Arbeitnow, Remotive, RemoteOK, Jobicy — queried
  only when a configured location is `Remote`.
- **Job-board scrapers**: LinkedIn (public guest endpoint, no login),
  SimplyHired, TimesJobs, and two opt-in browser-session sources for Naukri and
  the LinkedIn feed.
- **Two-key deduplication** — exact (`title|company|url`) plus a normalised
  fuzzy key, so the same posting arriving from three sources collapses to one row.
- **Profile-based scoring**, 0–100 from your own skill lists, with a title bonus
  and an experience-level adjustment. Optional LLM refinement on top.
- **Four filter gates** — role, experience level, location, freshness — each
  independently overridable per scan, distinguishing "default", "disabled" and
  "narrowed".
- **SQLite tracker** (`data/jobs.db`) with per-job workflow status
  (`new` → `shortlisted` → `tailored` → `applied` / `skipped`) preserved across
  re-scans, full scan history, and Excel export.
- **Flask web UI** with a live scan view streaming per-source progress, plus a
  full CLI (`python run.py …`).
- **Optional LLM features** — job scoring and resume/cover-letter tailoring via
  the Anthropic API or an OpenAI-compatible self-hosted gateway. Both degrade to
  no-ops when no backend is reachable.
- **Application autofill** that pre-fills forms and stops. JobSonar never submits
  an application on your behalf.
- Documentation: [README](README.md),
  [configuration reference](docs/CONFIGURATION.md),
  [source guide](docs/SOURCES.md), [architecture](docs/ARCHITECTURE.md),
  [contributing guide](CONTRIBUTING.md), [security policy](SECURITY.md).
- CI on Python 3.10 / 3.11 / 3.12: byte-compile, error-level lint, YAML config
  validation, and a fresh-clone smoke test that runs with no `.env` and no
  `config/profile.yaml` present.
- A dedicated CI **privacy job** that fails the build if a credential file,
  personal config, database, session-cookie file or hardcoded home path ever
  becomes tracked.

### Security

- Credentials load from `.env` then `.env.local` with `.env.local` overriding.
  Only `.env.example`, with blank values, is tracked.
- Personal identity and skills live in `config/profile.yaml`, which is
  git-ignored; `config/profile.example.yaml` is the tracked template and the
  runtime fallback, so a fresh clone runs without setup.
- Chrome binary and user-profile locations are derived from `Path.home()` and
  `sys.platform` rather than hardcoded, so no machine-specific path ships in the
  repository.
- Browser session state (`data/*_auth.json`) and all scan data are git-ignored.

[Unreleased]: https://github.com/SathyaSeelanG/jobsonar/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/SathyaSeelanG/jobsonar/releases/tag/v1.0.0
