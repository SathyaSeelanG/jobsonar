# Sources

JobSonar reads from four kinds of place. They're listed here roughly in order of
signal-to-noise: the further down you go, the more jobs you get and the more
duplicates and stale postings come with them.

Every source **fails soft** — it returns `[]` on any error rather than raising.
One dead board never takes down a scan. That also means a source returning
nothing looks identical to a source that's broken, so check
`python run.py scrape-report` for per-source counts when tuning.

---

## 1. Public ATS APIs — best signal

These are the company's own hiring system, read through its documented public
job-board endpoint. No key, no scraping, no rate-limit games, and the data is
first-hand: a posting appears here the moment recruiting publishes it, often
days before any aggregator indexes it.

| Platform | Endpoint | Config key | Token looks like |
|---|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/<token>/jobs` | `greenhouse_boards` | `boards.greenhouse.io/`**`acme`** |
| Lever | `api.lever.co/v0/postings/<token>` (EU fallback: `api.eu.lever.co`) | `lever_boards` | `jobs.lever.co/`**`acme`** |
| Ashby | `api.ashbyhq.com/posting-api/job-board/<name>` | `ashby_boards` | `jobs.ashbyhq.com/`**`acme`** |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/<id>/postings` | `smartrecruiters_companies` | `careers.smartrecruiters.com/`**`Acme`** |
| Rippling | `api.rippling.com/platform/api/ats/v1/board/<slug>/jobs` | `rippling_boards` | `ats.rippling.com/`**`acme`**`/jobs` |
| Keka | `<subdomain>.keka.com/careers` | `keka_boards` | **`acme`**`.keka.com/careers` |
| Workday | `<tenant>.<dc>.myworkdayjobs.com` CXS API | *(auto-detect only)* | `acme.wd3.myworkdayjobs.com/External` |

**Lever's EU fallback** exists because Lever splits tenants across regions — a
`404` on the US host isn't proof the board doesn't exist, so the fetcher retries
against `api.eu.lever.co` before giving up.

**Keka** ships with `keka: false`. Its selectors were written against one board
and never verified across others; treat it as unproven. Keka matters
disproportionately for Indian startups, so verifying it is a genuinely useful
contribution.

**Workday** has a working fetcher but no config list — it's reachable only when
the watchlist auto-detects a Workday careers page. Adding a `workday_tenants:`
key to `config/search.yaml` and dispatching it alongside the others is a small,
well-scoped first PR.

### Adding a board

Find one job link on a company's careers page and read the host:

```
boards.greenhouse.io/tekion/jobs/4287341    →  greenhouse_boards: [tekion]
jobs.lever.co/dozee/8fa1...                 →  lever_boards: [dozee]
jobs.ashbyhq.com/netgear/...                →  ashby_boards: [netgear]
```

One good token is worth more than a whole extra scraper. Verify it returns jobs
before adding it — dead tokens cost a request per scan and return silently
empty.

---

## 2. Company watchlist — best coverage of local employers

`config/companies.yaml` is a list of `{name, homepage}`. For each entry the
watchlist ([`job_agent/sources/watchlist.py`](../job_agent/sources/watchlist.py))
walks a cascade and stops at the first rung that yields jobs:

```
homepage
  └─ find the careers link (anchor text / href heuristics)
       └─ detect the ATS behind it  ──► call that ATS's public API   ★ best
            └─ parse JSON-LD  JobPosting  blocks                     ★ good
                 └─ parse Next.js __NEXT_DATA__ payload              ★ good
                      └─ static HTML card extraction                 ~ ok
                           └─ Playwright render, then extract        ~ slow
                                └─ page-level keyword signal          fallback
```

The last rung doesn't produce individual jobs — it reports "this company's
careers page mentions fresher hiring" so you can look yourself. Set
`watchlist_extract_jobs: true` (the default) to prefer real jobs over signals.

This is the only source that finds companies who never post to a job board at
all — common among mid-size Indian firms who hire entirely through their own
site plus referrals.

**Freshness is handled differently here.** Career pages rarely carry a reliable
posted date and a genuinely open role can sit unchanged for weeks, so watchlist
jobs get a 21-day floor instead of the global `posted_within_days: 3`. Location
is also lenient: the company list is hand-vetted, so a blank or generic location
("India", "Hybrid") doesn't disqualify a job — only a different named metro
does.

**Cost:** this is the slowest part of a scan. Each company is one to several
HTTP requests, sometimes a browser render. Use `watchlist_company_limit` to cap
it while you're tuning other things.

### ATS auto-detection

[`ats_detect.py`](../job_agent/sources/ats_detect.py) matches 11 URL patterns
against the careers page HTML: Greenhouse, Lever, Ashby, SmartRecruiters,
Workday, Rippling, Keka, BambooHR, Recruitee, Personio, Breezy.

Two known gaps, both worth PRs:

- **Detected but not fetchable** — BambooHR, Recruitee, Personio and Breezy are
  recognised, but `fetch_ats_jobs()` has no branch for them, so detection
  succeeds and then returns `[]`. Each needs a fetcher.
- **Not detected at all** — the signature list is entirely Western platforms.
  Zoho Recruit, Darwinbox, Freshteam, Workable, Oracle Fusion (`.oraclecloud.com`),
  SuccessFactors, Taleo and PeopleStrong are missing, and several of those are
  the *default* choice for Indian employers. This is the single highest-value
  contribution to the project.

---

## 3. Aggregator APIs — broad but noisy

| Source | Key | Notes |
|---|---|---|
| Adzuna | `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | Free tier is generous. Good India coverage. `adzuna_country: in`. |
| JSearch (RapidAPI) | `JSEARCH_API_KEY` | Aggregates Google for Jobs. Broadest reach, most duplicates. |

Both re-publish postings that originated on a company ATS, so expect overlap
with section 1. Deduplication happens after fetch (see
[ARCHITECTURE.md](ARCHITECTURE.md)).

**If you leave `JSEARCH_API_KEY` blank, set `jsearch: false`** — otherwise
JobSonar spends one round-trip per query getting nothing back.

### Keyless remote-job APIs

Arbeitnow, Remotive, RemoteOK and Jobicy need no key at all. They're only
queried when one of your `locations` is `"Remote"` — searching them for
"Chennai" is wasted work, since they only carry remote listings.

---

## 4. Job-board scrapers — last resort

| Source | Approach | Reliability |
|---|---|---|
| LinkedIn | Public `jobs-guest/jobs/api/seeMoreJobPostings` endpoint — no login | Decent. Rate-limits if pushed. |
| SimplyHired | `simplyhired.co.in` HTML | Decent. |
| TimesJobs | `timesjobs.com` HTML | Decent India coverage. |
| Naukri (`naukri`) | Headless Playwright | Poor — heavily bot-protected, usually blocked. Off by default. |
| Naukri (`naukri_auth`) | Your real Chrome over CDP | Works, but needs a live logged-in browser. Off by default. |
| LinkedIn feed | Playwright, saved session | Finds "we're hiring" *posts*, not job listings. Off by default. |

HTML scrapers break when a site redesigns. That's normal and expected — the
fail-soft contract means a broken scraper produces zero jobs, not a crash, and
`scrape-report` is how you notice.

Both `naukri_auth` and `linkedin_feed` reuse a real logged-in session. Their
state files under `data/` contain **live session cookies** — anyone with that
file is logged in as you. They're git-ignored; keep them that way. See
[SECURITY.md](../SECURITY.md).

### On scraping politely

The scrapers send a real User-Agent, sleep between requests, and cap results per
query. Don't remove any of that to go faster. JobSonar reads public pages at
roughly human pace; the moment it stops doing that it becomes something these
sites are right to block. It also never logs in on your behalf, never solves a
CAPTCHA, and never submits an application — see
[CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Which sources should I actually enable?

**Zero keys, want results today:** Greenhouse + Lever + Ashby boards for
companies you care about, plus the watchlist. That's the highest-quality half of
the pipeline and it costs nothing.

**Add one free key:** Adzuna. Best coverage-per-request of the aggregators.

**Searching remote:** put `"Remote"` in `locations` and leave the four keyless
remote APIs on.

**Casting the widest possible net:** everything above plus JSearch and the three
HTML scrapers. Expect more duplicates, more stale postings, and a slower scan.
