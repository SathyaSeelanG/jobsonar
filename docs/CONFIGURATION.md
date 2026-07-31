# Configuration reference

JobSonar has three config files and one credential file. Two of the four never
enter git.

| File | Tracked | Purpose |
|---|---|---|
| `.env.example` | ✅ | Documents every supported key. All values blank. |
| `.env.local` | ❌ | **Your real credentials.** Loaded last, overrides `.env`. |
| `config/search.yaml` | ✅ | What to search for, where, from which sources. |
| `config/profile.example.yaml` | ✅ | Profile template with placeholders. |
| `config/profile.yaml` | ❌ | **Your** identity, skills, form answers. |
| `config/companies.yaml` | ✅ | Career-page watchlist. |

First-run setup:

```bash
cp .env.example .env.local
cp config/profile.example.yaml config/profile.yaml
```

If `config/profile.yaml` is missing, JobSonar falls back to
`profile.example.yaml` so a fresh clone still runs — but scores are meaningless
until you put your own skills in.

---

## `.env.local` — credentials

Every key is optional. With none set, JobSonar still runs the keyless scrapers,
the public ATS feeds, the free remote-job APIs and the whole company watchlist.

| Key | Unlocks | Cost |
|---|---|---|
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | Adzuna aggregator API | Free tier |
| `JSEARCH_API_KEY` | JSearch (RapidAPI) aggregator | Free tier |
| `ANTHROPIC_API_KEY` | LLM scoring, resume/cover-letter tailoring | Pay-per-use |
| `OMNIROUTE_API_KEY` + `OMNIROUTE_BASE_URL` | Self-hosted LLM gateway instead of Anthropic | Free, self-hosted |

Leave a key blank rather than putting a placeholder in it. A blank key makes
JobSonar skip the source; a bogus one burns a request per query on a `401`.

**Load order:** `.env` first, then `.env.local` on top. Keep secrets in
`.env.local` only — see [SECURITY.md](../SECURITY.md).

---

## `config/profile.yaml` — you

```yaml
name: Your Name
email: you@example.com
phone: ""
location: ""                # e.g. "Chennai, India"
linkedin_url: ""
github_url: ""
portfolio_url: ""
resume_path: ""             # absolute path to your resume PDF, for uploads
years_experience: 0

skills:
  core: [React, Node.js, Express, MongoDB, JavaScript, TypeScript]
  secondary: [Next.js, Redux, PostgreSQL, Docker, AWS, Git, Tailwind]

summary: >
  Two or three sentences in your own voice. Used when tailoring cover letters.

form_answers:
  notice_period: "Immediate"
  willing_to_relocate: "Yes"
  work_authorization: "Yes"
  expected_salary: ""
```

### How `skills` becomes a score

The keyword score is 0–100:

- **up to 70 points** — the fraction of your `core` skills found in the posting
- **up to 30 points** — the fraction of your `secondary` skills found
- **+15 title bonus** if the title contains a strong role match (`mern`,
  `full stack`, `node`, `react`), with a floor of 45 for postings whose
  description is under 400 characters (some boards return title-only cards)
- **experience adjustment** — `fresher` +20, `junior` +10, `mid` 0,
  `senior` −10, `lead` −20

Skills are matched on word boundaries, so `Go` will not match `Golang`'s
neighbours or the word "going".

Practical consequences:

- A **long** `core` list dilutes the score — each skill is worth less, and no
  single posting will match all of them. Six to eight is a good size.
- Put must-haves in `core` and nice-to-haves in `secondary`.
- Listing skills you don't have surfaces jobs you can't do.

`min_score` in `search.yaml` is the shortlist cutoff. Jobs below it are still
stored — they just don't appear in the shortlist.

---

## `config/search.yaml` — the scan

### Scope

```yaml
queries:                    # role titles, one per line
  - "React developer"
  - "Full stack developer fresher"

locations:                  # cities; add "Remote" to hit the remote-only APIs
  - "Chennai"
```

Every query runs against every enabled source and every location. 24 queries ×
1 location is already several hundred HTTP requests per scan, so widen
deliberately.

### Thresholds

| Key | Default | Meaning |
|---|---|---|
| `posted_within_days` | `3` | Drop postings older than this. Watchlist **and direct-ATS** jobs get a 21-day floor — career pages rarely carry a precise date, and what an ATS reports is an update timestamp rather than a posted date (several send none at all). |
| `min_score` | `35` | Shortlist cutoff. Lower-scoring jobs are stored but not shortlisted. |
| `max_results_per_query` | `50` | Per-source cap per query. |
| `adzuna_country` | `in` | Adzuna country code (`in`, `us`, `gb`, …). |

### Concurrency

| Key | Default | Meaning |
|---|---|---|
| `api_workers` | `12` | Parallel API/ATS fetches. |
| `web_workers` | `8` | Parallel HTML scrapes. Raising this gets you rate-limited faster. |
| `watchlist_workers` | `15` | Parallel career-page fetches. |
| `watchlist_company_limit` | `0` | `0` = all companies. Set a small number while tuning. |

### ATS board tokens

The highest-yield setting in the file. One token typically returns tens of jobs
straight from the company, often before any aggregator indexes them.

```yaml
greenhouse_boards: [tekion, appian, fourkites]   # job-boards.greenhouse.io/<token>
lever_boards:      [dozee, nium]                 # jobs.lever.co/<token>
ashby_boards:      [netgear]                      # jobs.ashbyhq.com/<name>
smartrecruiters_companies: [Freshworks]           # SmartRecruiters company IDs
rippling_boards:   []                             # ats.rippling.com/<slug>/jobs
recruitee_boards:  []                             # <slug>.recruitee.com
personio_boards:   []                             # <slug>.jobs.personio.de
breezy_boards:     []                             # <slug>.breezy.hr
workable_boards:   []                             # apply.workable.com/<slug>
bamboohr_boards:   []                             # <slug>.bamboohr.com/careers
keka_boards:       [disprz, sisainfosec]          # <subdomain>.keka.com/careers
workday_tenants:   [uniphore/wd503/Uniphore]      # "tenant/dc/site", see below

jsonld_urls:   []    # career pages exposing JSON-LD JobPosting
nextdata_urls: []    # Next.js career pages exposing __NEXT_DATA__
```

**Finding a token:** open a company's Careers page and look at where a job link
points. `boards.greenhouse.io/acme/jobs/123` → the token is `acme`.

**Workday is the exception** — it needs three components, so each entry is one
`"tenant/dc/site"` string read off the board URL:
`cognizant.wd1.myworkdayjobs.com/CognizantCareers` → `"cognizant/wd1/CognizantCareers"`.
Entries that don't split into exactly three parts are skipped. Site names are
arbitrary per company and not worth guessing — get the URL from the real careers
page. See [SOURCES.md](SOURCES.md) for the error codes that tell you which of the
three parts is wrong.

**Four of these ship empty on purpose.** `recruitee_boards`, `personio_boards`,
`breezy_boards` and `workable_boards` all have working fetchers, but ~90
India-relevant slugs were probed across the four and none had open roles — those
platforms are European-centric. They still contribute via watchlist
auto-detection.

**Verify a token before adding it.** A dead token costs a request per scan and
returns silently empty, which is indistinguishable from a live board with nothing
open. The tokens shipped in `config/search.yaml` each carry a comment with their
measured yield; `python run.py scrape-report` gives you the same numbers for
yours.

**Note:** the `jsonld` and `nextdata` source toggles do nothing unless you also
populate `jsonld_urls` / `nextdata_urls`. Detection during a *watchlist* crawl
is separate and always active.

### Source toggles

```yaml
sources:
  adzuna: true          # needs ADZUNA_APP_ID + ADZUNA_APP_KEY
  jsearch: true         # needs JSEARCH_API_KEY
  greenhouse: true      # public API, no key
  lever: true           # public API, no key
  ashby: true           # public API, no key
  smartrecruiters: true # public API, no key (needs company IDs)
  rippling: false
  recruitee: true       # public API, no key
  personio: true        # public XML feed, no key
  breezy: true          # public API, no key (feed carries no description)
  workable: true        # public widget API, no key
  workday: true         # only acts on workday_tenants
  keka: true            # public careers page, no key (India-only ATS)
  bamboohr: false       # record fields unverified — see docs/SOURCES.md
  jsonld: true          # only acts on jsonld_urls
  nextdata: true        # only acts on nextdata_urls
  linkedin: true        # public jobs-guest endpoint, no login
  simplyhired: true
  timesjobs: true
  naukri: false         # headless Playwright, slow and often blocked
  arbeitnow: true       # keyless; only queried when a location is "Remote"
  remotive: true
  remoteok: true
  jobicy: true
  watchlist: true               # config/companies.yaml career pages
  watchlist_extract_jobs: true  # individual jobs, not page-level alerts
```

Turning a source off skips it entirely — no requests, no wasted wall-clock.

`adzuna` and `jsearch` are also turned off automatically when their credentials
are absent, with one dim line saying which variable to set. They would otherwise
contribute one no-op task per query × location — rows of "0 jobs, no error" in
`scrape-report`, which is exactly what a broken source looks like.

### LLM

```yaml
llm:
  scoring: true         # refine keyword scores for shortlisted jobs
  tailoring: true       # generate resume bullets + cover letters
  provider: omniroute   # or: anthropic
  omniroute_base_url: http://localhost:20128/v1
  omniroute_model: auto
```

Both flags degrade gracefully: with no reachable backend, `scoring` keeps the
keyword score and `tailoring` is skipped. Nothing crashes.

### Optional browser sources

```yaml
naukri_auth:
  enabled: false
  cdp_port: 9222
  max_results: 20
  profile_directory: "Default"    # or "Profile 1", "Profile 2", …
  # chrome_path and user_data_dir default to the standard Chrome location for
  # your OS and the current user. Uncomment only for a custom install.

linkedin_feed:
  enabled: false
  state_path: data/linkedin_auth.json
  max_posts: 15
  queries:
    - "React developer hiring Chennai"
```

`naukri_auth` connects to your real Chrome over CDP, reusing your logged-in
session. `linkedin_feed` needs a one-time `python run.py linkedin-login`. Both
save live session cookies under `data/` — treat those files like passwords and
never commit them.

---

## `config/companies.yaml` — the watchlist

```yaml
companies:
  - name: Example Corp
    homepage: https://example.com
```

For each entry the watchlist resolves the homepage to a careers page, detects
which ATS is behind it, and pulls individual jobs — falling back to JSON-LD,
`__NEXT_DATA__`, and then page-level heuristics.

Only `name` and `homepage` are needed; the ATS is detected, not declared. The
shipped list is Chennai-focused because that's the author's search — replace it
with companies you'd actually work for.

---

## Filters, and how to override them per scan

Four gates run after fetching and before scoring
([`job_agent/scoring.py`](../job_agent/scoring.py)):

| Gate | Default |
|---|---|
| Role | Built-in JavaScript/Python keyword allow-list |
| Experience | `fresher` + `junior` (entry level, ~1 year) |
| Location | Must literally contain a configured city |
| Freshness | `posted_within_days` (default 3) |

Each gate distinguishes three states, which matters when calling the API:

- **omitted / `None`** → use the built-in default
- **`["all"]` or `[]`** → disable this gate entirely
- **a specific list** → narrow to exactly those values

The web UI's filter dropdowns map onto this. Note that `["all"]` on the
experience or role filter means *no gate*, not *the default gate* — that is a
real behavioural difference, and passing the wrong one silently changes what a
scan returns.

Watchlist jobs are treated more leniently on location: they come from a
hand-vetted company list, so a blank or generic location field ("India",
"Hybrid", or nothing) does not disqualify them. Only an explicitly *different*
named metro does. Board sources, which cover the whole country, keep the strict
literal match.
