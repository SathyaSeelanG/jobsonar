"""Job scoring — fast keyword pass for all jobs, optional LLM pass for shortlist.

Experience-level weighting:
  fresher/intern  → +20 bonus
  junior/1-3yr    → +10 bonus
  mid/3-5yr       → no change
  senior/5+yr     → -10 penalty
  staff/lead      → -20 penalty
"""
import json
import os
import re


# Roles outside this list (e.g. "Supply Chain & Operations Consultant")
# should never be fetched/stored at all, regardless of source.
ROLE_KEYWORDS = (
    "mern", "react", "javascript", "typescript", "js developer", "js engineer",
    "frontend", "front-end", "front end",
    "backend", "back-end", "back end",
    "node", "nodejs", "node.js",
    "python", "django", "flask", "fastapi",
    "full stack", "fullstack", "full-stack",
)

# Broader terms that match several of our own search.yaml queries
# ("Software engineer fresher", "Web developer", "Associate software
# engineer") but whose card/snippet text may not repeat a specific stack
# keyword like "react" or "node". These are common enough in unrelated
# boilerplate JD text (e.g. "...automation and software engineering..." in a
# civil/controls engineering posting) that they must only count when they
# appear in the TITLE — matching them anywhere in the description produces
# false positives on non-dev roles.
GENERIC_TITLE_KEYWORDS = (
    "software engineer", "software developer", "web developer",
    "web development", "programmer", "software engineering",
)


def _wants_all(values) -> bool:
    """True if an override list *explicitly* means 'no filter, take
    everything' — an empty list or one containing the literal 'all'.

    This is distinct from `values is None`: `None` means the caller didn't
    pass an override at all, so each matcher below falls back to its own
    tracker-default scope. An override that's present but empty/["all"]
    means the user actively chose "no restriction" at scan time.
    """
    if values is None:
        return False
    if not values:
        return True
    return any(str(v).strip().lower() == "all" for v in values)


# Public alias — other modules (e.g. app.py) use this to decide whether a
# scan-time override list should replace config defaults (e.g. cfg["queries"])
# or be left alone because the user picked "All".
wants_all = _wants_all


def is_relevant_role(job, roles: list[str] | None = None) -> bool:
    """True if the job's title/description matches the role scope.

    With no `roles` override (the default) this checks the built-in
    MERN/React/Node/Python ROLE_KEYWORDS allow-list. When the caller passes
    explicit `roles` (a scan-time "role" filter typed/selected by the user),
    those free-text terms are matched instead — so a user asking for "Java
    developer" isn't silently dropped by the default MERN-only gate.
    Passing roles=["all"] (or []) removes the role gate entirely.
    """
    title = job.title.lower()
    text = f"{title} {job.description}".lower()
    if roles is None:
        return any(kw in text for kw in ROLE_KEYWORDS) or any(
            kw in title for kw in GENERIC_TITLE_KEYWORDS
        )
    if _wants_all(roles):
        return True
    return any(str(r).strip().lower() in text for r in roles if str(r).strip())


# Explicit non-entry-level seniority — postings that clearly ask for a
# mid/senior/lead title (multi-year experience) are excluded. "junior" is
# treated as entry-level alongside "fresher" (~1 year experience roles are
# the default scope now, not just 0-year fresher roles). Postings that don't
# mention experience at all are kept (silently dropping every unlabeled
# posting would leave almost nothing, since most boards don't state a level).
_NON_FRESHER_LEVELS = ("mid", "senior", "lead")
ALL_EXPERIENCE_LEVELS = ("fresher", "junior", "mid", "senior", "lead")


def is_fresher_friendly(job) -> bool:
    """True unless the job is explicitly labeled mid/senior/lead.

    "fresher" and "junior" (~1 year experience) both count as entry-level and
    pass this gate; only mid+ seniority is excluded.

    Always re-infers from the job's CURRENT title/description rather than
    trusting a cached experience_level — some sources (e.g. watchlist) set
    experience_level from a short card snippet before the full JD is fetched,
    so a stale "fresher" label can survive even after the hydrated description
    reveals a "5+ years experience" requirement."""
    level = _infer_experience_level(job.title, job.description)
    return level not in _NON_FRESHER_LEVELS


def is_experience_match(job, levels: list[str] | None = None) -> bool:
    """True if the job's inferred experience level is one of `levels`.

    With no `levels` override (the default) this falls back to the tracker's
    default entry-level gate (`is_fresher_friendly` — fresher + junior/~1yr
    exp) so existing behavior is unchanged when nobody asks for something
    different. Passing levels=["all"] (or []) removes the level gate
    entirely — the scan-time "get all" override. An unrecognized/unlabeled
    level is always kept when a specific override is given — most boards
    don't state one, and we can't prove it doesn't match.
    """
    if levels is None:
        return is_fresher_friendly(job)
    if _wants_all(levels):
        return True
    allowed = {str(l).strip().lower() for l in levels if str(l).strip()}
    level = _infer_experience_level(job.title, job.description)
    if not level:
        return True
    return level in allowed


_OTHER_METRO_CITIES = (
    "bangalore", "bengaluru", "mumbai", "delhi", "gurgaon", "gurugram",
    "noida", "pune", "hyderabad", "kolkata", "ahmedabad", "jaipur",
    "kochi", "coimbatore", "trivandrum", "thiruvananthapuram",
)


ALL_KNOWN_METROS = _OTHER_METRO_CITIES + ("chennai", "remote")


def is_location_match(job, locations: list[str] | None = None) -> bool:
    """True if the job's location plausibly matches one of `locations`.

    With no `locations` override (the default) this checks the tracker's
    built-in Chennai scope for backward compatibility (see
    `is_chennai_location`). Passing locations=["all"] (or []) removes the
    location gate entirely — the scan-time "get all" override. Passing
    specific city names filters/rescans against just those.

    Watchlist jobs come from a hand-vetted company list already scoped to the
    target city/companies, so a blank/generic location field — very common
    on ATS APIs and career pages ("India", "Hybrid", no field at all) —
    shouldn't disqualify them on its own; only an explicit *other* named
    metro (one not in `locations`) should. Non-watchlist sources (job boards
    covering all of India) keep the stricter literal match since they were
    never pre-vetted by city.
    """
    if locations is None:
        locations = ["chennai"]
    elif _wants_all(locations):
        return True
    targets = [str(l).strip().lower() for l in locations if str(l).strip()]
    if not targets:
        return True
    loc = (job.location or "").lower()
    if any(t in loc for t in targets):
        return True
    source = (getattr(job, "source", "") or "").lower()
    if source.startswith("watchlist"):
        other_metros = [m for m in ALL_KNOWN_METROS if not any(t in m or m in t for t in targets)]
        return not any(city in loc for city in other_metros)
    return False


def is_chennai_location(job) -> bool:
    """Back-compat wrapper: the tracker's default Chennai-only scope."""
    return is_location_match(job, ["chennai"])


MAX_POSTED_AGE_DAYS = 3


# Career-page/ATS listings (watchlist) tend to sit unchanged for longer than
# job-board postings and often lack a precise "posted X days ago" signal, so
# they get a wider freshness window rather than the board-tuned max_days.
WATCHLIST_MAX_AGE_DAYS = 21


def is_recently_posted(job, max_days: int = MAX_POSTED_AGE_DAYS) -> bool:
    """True unless the job's own posted_at date is older than max_days.
    Jobs with no parseable posted date are kept — we can't prove they're old."""
    from datetime import datetime, timezone
    from .util import _parse_dt

    source = (getattr(job, "source", "") or "").lower()
    if source.startswith("watchlist"):
        max_days = max(max_days, WATCHLIST_MAX_AGE_DAYS)

    raw = getattr(job, "posted_at", "") or ""
    if not raw:
        return True
    ts = _parse_dt(raw)
    if ts is None:
        return True
    age_days = (datetime.now(timezone.utc) - ts).days
    return age_days <= max_days


def keyword_score(job, profile: dict) -> tuple[int, str]:
    """0-100 based on skill matches in title + description, plus experience weighting."""
    text = f"{job.title} {job.description}".lower()
    skills = profile.get("skills", {})
    core = skills.get("core", [])
    secondary = skills.get("secondary", [])

    core_hits = [s for s in core if _found(s, text)]
    sec_hits = [s for s in secondary if _found(s, text)]

    score = 0
    if core:
        score += int(70 * len(core_hits) / len(core))
    if secondary:
        score += int(30 * len(sec_hits) / len(secondary))

    # Title bonus for direct role match. Listings from some boards (e.g.
    # LinkedIn cards) have almost no description text, so a strong title
    # match also sets a floor score to keep them shortlistable.
    title = job.title.lower()
    for kw in ("mern", "full stack", "fullstack", "full-stack", "node", "react"):
        if kw in title:
            score = min(100, score + 15)
            if len(job.description) < 400:
                score = max(score, 45)
            break

    # Experience-level weighting. Infer once and persist it onto the job so
    # `list`/`show`/exports display it — previously this was computed here
    # and thrown away, leaving the Level column blank for every job that
    # didn't already have experience_level set by its source.
    exp_level = getattr(job, "experience_level", "") or ""
    if not exp_level:
        exp_level = _infer_experience_level(job.title, job.description)
        job.experience_level = exp_level
    if exp_level:
        score = max(0, min(100, score + _EXP_BONUS.get(exp_level, 0)))

    reason = f"core: {', '.join(core_hits) or 'none'}; secondary: {', '.join(sec_hits) or 'none'}"
    if exp_level:
        reason += f"; exp: {exp_level}"
    return min(score, 100), reason


# Experience level bonus/penalty mapping
_EXP_BONUS = {
    "fresher": 20,
    "junior": 10,
    "mid": 0,
    "senior": -10,
    "lead": -20,
}


def _infer_experience_level(title: str, description: str) -> str:
    """Infer experience level from job title + description.

    Delegates to the shared, more accurate implementation in sources/ats.py
    (handles year ranges like "1-2 years", not just a single number) so
    watchlist jobs and API/scraper jobs are classified the same way.
    """
    from .sources.ats import infer_experience_level
    return infer_experience_level(title, description)


def _found(skill: str, text: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(skill.lower())}(?![a-z])", text) is not None


def llm_score(job, profile: dict, llm_cfg: dict) -> tuple[int, str] | None:
    """Refine score with an LLM via OmniRoute (see llm.py).
    Returns None if no backend is available or the call/parse fails,
    so callers just keep the keyword score."""
    from .llm import chat

    prompt = (
        "Score this job 0-100 for fit against the candidate. "
        'Reply ONLY with JSON: {"score": <int>, "reason": "<one sentence>"}\n\n'
        f"CANDIDATE: {json.dumps({k: profile.get(k) for k in ('summary', 'skills', 'years_experience')})}\n\n"
        f"JOB: {job.title} at {job.company}\n{job.description[:3000]}"
    )
    raw = chat(prompt, 200, llm_cfg)
    if not raw:
        return None
    try:
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group())
        return int(data["score"]), str(data["reason"])
    except Exception:
        return None
