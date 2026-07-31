<!-- Thanks for contributing to JobSonar. Keep one concern per PR. -->

## What this changes

<!-- One or two sentences. Link the issue it closes, e.g. "Closes #12". -->

## Why

<!-- The problem this solves. For a new source: what it covers that nothing
     else does. -->

## How it was verified

<!-- Be specific. Real numbers beat "tested locally" — selectors and API
     assumptions are guesswork until someone runs them against a live board.

     e.g. "Ran `python run.py scrape-report`: zohorecruit returned 41 jobs
     across 3 boards, 12 in Chennai, 4 entry-level." -->

- [ ] `python run.py scrape-report` runs clean
- [ ] `python app.py` starts and a scan completes

## Checklist

- [ ] No personal data or credentials in the diff (`.env*`, `config/profile.yaml`,
      `data/`, `*_auth.json`, real names, emails, absolute home paths)
- [ ] No new hardcoded machine-specific paths — derive from `Path.home()` or config
- [ ] New source (if any) fails soft: returns `[]` instead of raising into the run
- [ ] New source (if any) defaults to `false` in `config/search.yaml` if it needs
      a key or is unverified
- [ ] Any new credential is documented in `.env.example` with a **blank** value
- [ ] Does not auto-submit applications, bypass CAPTCHAs/logins, or defeat bot
      detection
- [ ] `docs/` and `README.md` updated if behavior or configuration changed
- [ ] No unrelated reformatting

## Notes for the reviewer

<!-- Trade-offs, things you're unsure about, follow-ups you deliberately left out. -->
