# Security Policy

## The short version

JobSonar is self-hosted and has no backend. Nothing you configure or scan leaves
your machine. There is no account, no telemetry, and no outbound reporting — the
only network traffic is to the job sources you enabled and, if you turned on LLM
scoring, to your chosen LLM endpoint.

## Where secrets live

| Path | Tracked | Contents |
|---|---|---|
| `.env.example` | ✅ tracked | Key *names* only, all values blank |
| `.env.local` | ❌ git-ignored | **Your real API keys.** Loaded last, wins over `.env` |
| `.env` | ❌ git-ignored | Optional fallback; prefer `.env.local` |
| `config/profile.yaml` | ❌ git-ignored | Your name, contact details, salary expectations |
| `data/jobs.db` | ❌ git-ignored | Your scan and application history |
| `data/*_auth.json` | ❌ git-ignored | Live browser session cookies |

`.gitignore` blocks `.env*` (excepting `.env.example`), `config/profile.yaml`,
everything under `data/`, all `*.db`, all `*_auth.json`, and all `*.xlsx`
exports. Before your first push, confirm it holds:

```bash
git status --porcelain --ignored | grep -E '\.env|profile\.yaml|\.db'
```

Every line should be prefixed `!!` (ignored). If any is prefixed `A` or `??`,
stop and fix `.gitignore` before committing.

### Browser session files

`python run.py linkedin-login` and the Naukri CDP flow save real, live session
cookies under `data/`. Treat those files exactly like a password: never commit
them, never paste them into an issue, never share the directory. Anyone holding
one is logged in as you.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private reporting flow instead:
[Security → Report a vulnerability](https://github.com/SathyaSeelanG/jobsonar/security/advisories/new)

Include what you can — affected version or commit, reproduction steps, and the
impact you believe it has. Expect an acknowledgement within about a week. Since
this is a personal project maintained in spare time, please allow reasonable
time for a fix before disclosing publicly.

### In scope

- Credential or session-token leakage (into logs, exports, the DB, or git)
- Anything that would cause a secret to be committed despite `.gitignore`
- Code execution via untrusted scraped content (job titles, descriptions, HTML)
- SQL injection or path traversal in the tracker or export paths
- XSS in the local web UI via scraped job fields

### Out of scope

- Rate limiting or blocking by third-party job boards
- Scraper selectors breaking when a site changes its markup
- Any issue that requires an attacker to already have local access to your
  machine or your `.env.local`
- Vulnerabilities in third-party job sites themselves

## Hardening notes

- **Bind address.** `python app.py` serves on localhost. Do not expose it to a
  network or the internet — there is no authentication layer, and the UI can
  read and modify your entire job database.
- **Scraped content is untrusted input.** Job titles and descriptions come from
  arbitrary third-party HTML. If you add a new sink for that text (a template, a
  shell call, a SQL string), escape or parameterize it.
- **Rotate on exposure.** If you ever commit a key by accident, revoke and
  reissue it at the provider immediately. Deleting the commit is not enough —
  assume anything pushed to a public repository is permanently compromised.
