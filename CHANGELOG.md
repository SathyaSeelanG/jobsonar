# Changelog

All notable changes to JobSonar are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Five new ATS fetchers** — Recruitee, Personio, Breezy HR, Workable and
  BambooHR, each with a `*_boards` config key and a source toggle. Four were
  written against live responses; BambooHR's record fields are unverified (see
  Notes) and it ships disabled.
- **`workday_tenants` config key.** `fetch_workday` already worked but was
  reachable only through watchlist auto-detection. Entries are `"tenant/dc/site"`
  strings; malformed ones are skipped.
- **Detection-only ATS signatures** for Zoho Recruit, Darwinbox, Freshteam,
  Oracle Fusion, SuccessFactors, Taleo and PeopleStrong. None expose a guessable
  public feed, so these only attribute a company to its ATS — the watchlist
  cascade still falls through to JSON-LD and HTML extraction. The
  fetchable/detection-only split is now exported as `ats_detect.DETECTION_ONLY`
  so the code and docs can't drift.

### Changed

- **Direct ATS feeds now share the watchlist's 21-day freshness floor.** What an
  ATS reports is not a posted date — Greenhouse sends `updated_at`, Workable
  `published_on`, Recruitee `published_at`, and Lever, Ashby and Workday send
  none at all. Under the board-tuned 3-day window a dateless Lever role was
  always kept while the identical Greenhouse role was dropped on day 4 purely
  for carrying a timestamp.
- **Board tokens in `config/search.yaml` re-probed and re-cut.** Removed two that
  returned zero jobs (`integrate`, and `poshmark` on Greenhouse — it's an Ashby
  board); added eleven measured ones across Greenhouse, Lever and Ashby. Every
  entry now carries its measured yield as a comment.
- **Tokens added from an ATS census of the 239-company watchlist**, which ran the
  detector over each company's real careers HTML rather than guessing slugs:
  `greenhouse/mitsogoinc` (35 jobs, 21 Chennai — the best Chennai ratio measured),
  `greenhouse/devrev`, `smartrecruiters/Freshworks` (100/20), three Keka boards
  and two Workday tenants.
- **`keka` and `smartrecruiters` now ship enabled.** Keka is verified against
  three live boards; being India-only, it is absent from every US-centric source
  list despite being common among Chennai product companies.
- **Keka now uses its board's JSON API instead of headless Playwright,** which
  moves it from the sequential browser stage to the pooled API stage: 0.5 s per
  board instead of a browser launch. The rendered cards exposed no location, no
  date and only their own label as a description; the JSON route returns full
  descriptions, city-level locations, `publishedOn` and a numeric `experience`
  field, which is appended to the description so the fresher/junior gate can read
  it. It also collects more — one board returned 28 jobs against the scraper's 20.
- **Workday's per-request sleep cut from 1.5 s to the shared 0.5 s `DELAY`.** At
  one detail call per posting the old value cost roughly 300 s for a single
  tenant, which made the source unusable at scan scale.
- **`recruitee_boards`, `personio_boards`, `breezy_boards` and `workable_boards`
  documented as intentionally empty.** All four fetchers work, but ~90
  India-relevant slugs were probed across them and every one returned zero open
  roles — these platforms are European-centric. They still contribute through
  watchlist auto-detection.
- **`adzuna` and `jsearch` switch themselves off when their credentials are
  absent**, with one line naming the variable to set. They previously contributed
  a no-op task per query × location, printing rows of "0 jobs, no error" —
  indistinguishable from a broken source.

### Fixed

- **Greenhouse detection missed the current host.** Boards moved to
  `job-boards.greenhouse.io`; only `boards.greenhouse.io` was matched. The
  `embed/job_board?for=<token>` iframe form also captured the literal path
  segment `job_board` as the board token.
- **Lever's EU host wasn't detected.** `fetch_lever` retried against
  `api.eu.lever.co`, but `jobs.eu.lever.co` URLs never matched a signature.
- **Subdomain signatures could match mid-label**, so `apply.workable.com` was
  read as the tenant `pply`. All subdomain patterns now anchor with a lookbehind.
- **A stale explicit ATS token silently dropped a whole company.** Watchlist
  Strategy 1 returned as soon as the configured ATS was called, even on an empty
  result, skipping the five remaining cascade rungs. It now falls through unless
  the fetch actually yielded jobs — matching Strategy 3's existing behaviour.
- **Personio descriptions were mojibaked.** The feed is served without a charset
  header, so `requests` fell back to latin-1 ("Köpenicker" → "KÃ¶penicker"). The
  XML is now parsed from raw bytes.
- **Workday stopped at 40 jobs regardless of tenant size.** The CXS API reports
  `total` on the first page only and sends `0` on every page after, so re-reading
  it each pass made the `offset >= total` exit condition true from page 2. It is
  now captured once. Verified against a tenant with 2000 open roles.
- **Workday jobs were never dated,** so they bypassed the freshness gate
  entirely — the API sends prose (`"Posted 5 Days Ago"`) rather than a timestamp,
  which didn't parse, and an unparseable date means "can't prove it's old, keep
  it". The relative wording is now converted to an ISO date.
- **`fetch_workday` ignored `max_results`** — it was the only fetcher without the
  cap, and raised `TypeError` when the dispatcher passed one. It now bounds both
  the page loop and the per-posting detail calls.
- **Every SmartRecruiters job arrived with an empty description and an API URL.**
  The posting's top-level `description` is always `null`; the text lives in
  `jobAd.sections` as four separate blocks. An empty description zeroes the
  keyword score and hides the years-of-experience wording the fresher gate reads.
  The `url` came from `ref`, which is the API endpoint — clicking it returned
  JSON. Now uses `postingUrl`, and picks up `releasedDate` for free.
- **ATS detection attributed companies to CDN and asset hosts.** A careers page
  linking `files.freshteam.com` for an attachment was read as the Freshteam tenant
  `files`; `cdn.keka.com` masked the correct token sitting in the same page. Any
  such false positive short-circuits the whole signature table for that company,
  because detection returns the first match. All subdomain patterns now exclude a
  list of known non-tenant labels.

### Notes

- **BambooHR's fetcher is unvalidated.** The `{meta, result}` envelope is
  confirmed, but none of ~190 probed subdomains served a non-empty `result`, so
  field names are read through a list of aliases. `bamboohr: false` in the
  shipped config. Confirming the record shape against a live board with open
  roles is a well-scoped PR.
- **Breezy's feed carries no description** and its detail pages expose no
  JSON-LD, so Breezy jobs arrive with only department and employment type as
  text. The watchlist hydrator fills the rest in when the company is also on the
  watchlist.

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
