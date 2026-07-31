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
| Recruitee | `<slug>.recruitee.com/api/offers/` | `recruitee_boards` | **`acme`**`.recruitee.com` |
| Personio | `<slug>.jobs.personio.de/xml` | `personio_boards` | **`acme`**`.jobs.personio.de` |
| Breezy HR | `<slug>.breezy.hr/json` | `breezy_boards` | **`acme`**`.breezy.hr` |
| Workable | `apply.workable.com/api/v1/widget/accounts/<slug>?details=true` | `workable_boards` | `apply.workable.com/`**`acme`** |
| Keka | `<subdomain>.keka.com/careers/api/jobs/default/active` | `keka_boards` | **`acme`**`.keka.com/careers` |
| BambooHR | `<slug>.bamboohr.com/careers/list` | `bamboohr_boards` | **`acme`**`.bamboohr.com/careers` |
| Workday | `<tenant>.<dc>.myworkdayjobs.com` CXS API | `workday_tenants` | `acme.wd3.myworkdayjobs.com/External` |

**Greenhouse serves two hosts.** Boards moved to `job-boards.greenhouse.io`, but
the old `boards.greenhouse.io` still resolves, so detection accepts either — plus
the `embed/job_board?for=<token>` iframe form, where the token is in the query
string rather than the path.

**Lever's EU fallback** exists because Lever splits tenants across regions — a
`404` on the US host isn't proof the board doesn't exist, so the fetcher retries
against `api.eu.lever.co` before giving up.

**Personio's feed is XML, not JSON**, and it's served without a charset header —
the fetcher parses the raw bytes so the XML declaration picks the codec, because
letting `requests` guess mojibakes every non-ASCII office name.

**Workable's `details=true`** is what supplies description text, and it makes the
response large: one probed account returned 2219 jobs / 9.6 MB. All fetchers take
a `max_results` cap, wired to `max_results_per_query`.

**SmartRecruiters hides its description.** The posting object's top-level
`description` is always `null`; the text lives in `jobAd.sections` as four
separate blocks (`jobDescription`, `qualifications`, `additionalInformation`,
`companyDescription`), which the fetcher concatenates in that order so the
6000-char cap truncates boilerplate rather than requirements. Its `ref` field is
the API endpoint, not a page — the human-readable link is `postingUrl` on the
detail response.

**Keka** is enabled and verified against three live boards. It matters
disproportionately for Indian startups: it is India-only, so it never shows up in
a US-centric source list even though it is common among Chennai and Bangalore
product companies. Its boards are JS-rendered, but the page is backed by a plain
JSON route that returns more than the rendered cards do — including a numeric
`experience` field, which the fetcher appends to the description text so the
fresher/junior gate can read it. **BambooHR** still ships `false` — no probed board had open
roles, so its field mapping is unverified. See the auto-detection section below.

**Recruitee, Personio, Breezy and Workable are European-centric.** All four
fetchers work, but ~90 India-relevant slugs were probed across them and every one
returned zero open roles, so their `*_boards` keys ship empty on purpose. They
still pay for themselves through watchlist auto-detection, which is how a
non-Indian company on one of these platforms gets picked up.

**Workday takes three parts**, so `workday_tenants` entries are `"tenant/dc/site"`
strings read straight off a board URL:
`cognizant.wd1.myworkdayjobs.com/CognizantCareers` → `"cognizant/wd1/CognizantCareers"`.
Malformed entries are skipped rather than sent to the fetcher as empty strings.
Don't try to guess them. The CXS API answers `422` for an unknown tenant and
`404` for a real tenant with the wrong site name, so you can confirm a tenant
exists without knowing its site — but site names are arbitrary per company
(`External`, `2`, `IjpExternal`, `CognizantCareers`) and a 400-probe sweep of 50
plausible tenants resolved only one site name. Read the real careers URL instead;
`python run.py scrape-report` and the watchlist auto-detector both surface it.

Workday is also the most expensive fetcher here — one detail request per posting
on top of the 20-per-page listing calls — so `max_results_per_query` matters more
for Workday tenants than for any other source.

### Adding a board

Find one job link on a company's careers page and read the host:

```
boards.greenhouse.io/tekion/jobs/4287341    →  greenhouse_boards: [tekion]
jobs.lever.co/dozee/8fa1...                 →  lever_boards: [dozee]
jobs.ashbyhq.com/netgear/...                →  ashby_boards: [netgear]
apply.workable.com/acme/j/A1B2C3/           →  workable_boards: [acme]
```

One good token is worth more than a whole extra scraper. Verify it returns jobs
before adding it — dead tokens cost a request per scan and return silently
empty.

The tokens shipped in `config/search.yaml` were each probed live, and the
trailing comment on every entry is its measured yield (total postings / how many
in Chennai). Boards with a strong India presence but zero Chennai postings are
kept deliberately: India-wide hiring rotates through Chennai, so an empty week
is not a dead board. Boards that returned zero jobs on any platform were
dropped.

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
jobs get a 21-day floor instead of the global `posted_within_days: 3`. Direct ATS
feeds get the same floor, for the same reason plus one more: what they report is
not a posted date. Greenhouse sends `updated_at`, Workable `published_on`,
Recruitee `published_at`, SmartRecruiters `releasedDate`; Workday sends only
relative prose ("Posted 5 Days Ago"), which the fetcher converts to a date so the
gate can act on it; Lever and Ashby send nothing at all. Under the
board-tuned 3-day window that produced a perverse split — a dateless Lever role
was always kept, while the identical role on a Greenhouse board was dropped on
day 4 purely because it happened to carry a timestamp. Location
is also lenient: the company list is hand-vetted, so a blank or generic location
("India", "Hybrid") doesn't disqualify a job — only a different named metro
does.

**Cost:** this is the slowest part of a scan. Each company is one to several
HTTP requests, sometimes a browser render. Use `watchlist_company_limit` to cap
it while you're tuning other things.

### ATS auto-detection

[`ats_detect.py`](../job_agent/sources/ats_detect.py) matches URL patterns
against the careers page HTML and returns the first hit, so platforms with a
working fetcher are listed ahead of detection-only ones.

**Fetchable** (detection resolves to a real API call): Greenhouse, Lever, Ashby,
SmartRecruiters, Workday, Rippling, Recruitee, Personio, Breezy, Workable, Keka,
BambooHR.

**Detection-only** — recognised so a company can be attributed to its ATS, but
`fetch_ats_jobs()` returns `[]` and the cascade falls through to JSON-LD and
HTML extraction: Zoho Recruit, Darwinbox, Freshteam, Oracle Fusion
(`.oraclecloud.com`), SuccessFactors, Taleo, PeopleStrong. This is not an
oversight — each was probed and has no guessable public feed:

| Platform | Endpoint tried | Result |
|---|---|---|
| Freshteam | `/api/job_postings` | 404 / 503 |
| Darwinbox | `/ms/candidate/careers/getJobs` | 404 |
| PeopleStrong | `/api/jobs` | 403 |
| Zoho Recruit | careers portal | HTML only, no JSON |

The canonical list lives in `ats_detect.DETECTION_ONLY`; read that rather than
this table if you're writing code.

**BambooHR is the one unverified fetcher.** The `{meta, result}` envelope is
confirmed, but no probed subdomain (~190 of them) served a non-empty `result`,
so the per-record field names are guesses read through a list of aliases.
`bamboohr` is therefore `false` in the shipped config. If you have access to a
live BambooHR board with open roles, confirming the record shape is a genuinely
useful PR.

Breezy's feed carries no description and its detail pages expose no JSON-LD, so
Breezy jobs arrive with only department and employment type as text. When the
same company is also on the watchlist the hydrator fills the description in.

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
