"""Small shared helpers."""
from datetime import datetime, timezone
from pathlib import Path

import requests


def load_env(root: Path) -> None:
    """Load environment variables from `.env`, then `.env.local` on top.

    Real credentials belong in `.env.local` only — it is git-ignored, so
    nothing secret can reach the repository. `.env` is read first so a
    shared/default file can exist, and `.env.local` overrides it per
    machine. `.env.example` documents every supported key.
    """
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    load_dotenv(root / ".env.local", override=True)


def load_profile(root: Path) -> dict:
    """Read `config/profile.yaml`, falling back to `config/profile.example.yaml`.

    The real profile holds personal details (name, contact, salary
    expectations) and is git-ignored, so a fresh clone has only the example.
    Falling back keeps the app runnable immediately after cloning instead of
    crashing on a missing file; the example's placeholder skills simply score
    everything low until the user copies and fills it in.
    """
    import yaml

    for name in ("profile.yaml", "profile.example.yaml"):
        path = root / "config" / name
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raise FileNotFoundError(
        "No config/profile.yaml found. Copy config/profile.example.yaml to "
        "config/profile.yaml and fill in your details."
    )


def default_chrome_user_data_dir() -> str:
    """Best-guess path to the current user's Chrome profile directory.

    Derived from the running user's home directory rather than hardcoded, so
    the repo carries no machine-specific paths. Override explicitly with
    `naukri_auth.user_data_dir` in config/search.yaml when Chrome lives
    somewhere non-standard.
    """
    import sys

    home = Path.home()
    if sys.platform == "win32":
        return str(home / "AppData" / "Local" / "Google" / "Chrome" / "User Data")
    if sys.platform == "darwin":
        return str(home / "Library" / "Application Support" / "Google" / "Chrome")
    return str(home / ".config" / "google-chrome")


def default_chrome_binary() -> str:
    """Best-guess path to the Chrome executable for the current platform.

    Override with `naukri_auth.chrome_path` in config/search.yaml if needed.
    """
    import shutil
    import sys

    if sys.platform == "win32":
        return r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if sys.platform == "darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"


def freshness(posted_at: str, fetched_at: str = "") -> str:
    """Human-readable age of a posting, e.g. 'Today', '2d ago', '3w ago'.

    Prefers the source's own posted_at (when a scraper/API supplied one);
    falls back to when *we* first fetched it if the posting itself has no
    date. Unparseable/missing dates return '' rather than guessing.
    """
    raw = posted_at or fetched_at
    if not raw:
        return ""
    ts = _parse_dt(raw)
    if ts is None:
        return ""
    now = datetime.now(timezone.utc)
    delta = now - ts
    days = delta.days
    if delta.total_seconds() < 0:
        return "Today"
    if days <= 0:
        return "Today"
    if days == 1:
        return "1d ago"
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        return f"{days // 7}w ago"
    months = days // 30
    return f"{months}mo ago"


def _parse_dt(raw: str):
    raw = raw.strip()
    # Common ISO 8601 variants (with/without 'Z', with/without microseconds).
    candidates = [raw, raw.replace("Z", "+00:00")]
    for cand in candidates:
        try:
            ts = datetime.fromisoformat(cand)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except ValueError:
            continue
    return None


def check_url_live(url: str, timeout: int = 15) -> bool:
    """Best-effort liveness check for a job posting URL.

    Only returns False on a clear dead signal (404/410). Network errors,
    timeouts, or sites that block HEAD requests return True — we'd rather
    occasionally tailor a stale posting than hide a live one because of a
    flaky check.
    """
    if not url:
        return True
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout, headers=headers)
        if resp.status_code == 405:  # some sites don't support HEAD
            resp = requests.get(url, allow_redirects=True, timeout=timeout, headers=headers)
        return resp.status_code not in (404, 410)
    except Exception:
        return True
