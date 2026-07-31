"""LinkedIn feed-post scanner — pure Python (Playwright), no browser-extension
tool involved. Everything here runs from `python run.py`.

Your manual research found that LinkedIn *feed posts* (people/recruiters
posting "we're hiring") surface leads that never reach the Jobs tab or any
aggregator. There's no public API for this, and the feed is login-gated, so
this uses a one-time interactive login (`python run.py linkedin-login`) that
saves the authenticated session to a local JSON file, then reuses that
session headlessly on later `search` runs to scan for hiring posts.

Caveats (read before enabling):
- LinkedIn's DOM for feed/search-results is not verified live in this
  environment (sandboxed, no internet during development). Selectors below
  are a best guess — if this returns 0 posts, inspect the page yourself
  (devtools on a logged-in search-results/content page) and update the
  selectors in `scan_linkedin_feed`.
- This reads content only; it never posts, comments, or connects. Still,
  scanning too often / too many queries risks tripping LinkedIn's bot
  detection on your account. Keep `max_posts` and query count modest and
  don't run this more than once or twice a day.
- The saved session file (`data/linkedin_auth.json` by default) contains
  your live LinkedIn cookies — treat it like a password and don't commit
  it or share it.
"""
import hashlib
import urllib.parse
from pathlib import Path

from ..models import Job


class SessionExpired(Exception):
    """LinkedIn redirected to a login/authwall page — saved session is stale."""


def _q(s: str) -> str:
    return urllib.parse.quote_plus(s)


def save_linkedin_session(state_path: Path) -> None:
    """One-time interactive login: opens a real (headed) browser window,
    you log into LinkedIn manually, then press Enter here — the session
    (cookies) gets saved to `state_path` for headless reuse."""
    from playwright.sync_api import sync_playwright
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        print("Log into LinkedIn in the browser window that just opened.")
        input("Once you can see your feed, come back here and press Enter... ")
        context.storage_state(path=str(state_path))
        browser.close()
    print(f"Session saved to {state_path}")


def scan_linkedin_feed(state_path: Path, queries: list[str], max_posts: int = 15) -> list[Job]:
    """Headlessly reuse the saved session to search LinkedIn's content/post
    search for each query and extract hiring-post text. Raises SessionExpired
    if the saved cookies no longer work (caller should prompt a re-login)."""
    if not state_path.exists():
        return []
    from playwright.sync_api import sync_playwright

    jobs, seen_hashes = [], set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()
        try:
            for q in queries:
                url = f"https://www.linkedin.com/search/results/content/?keywords={_q(q)}"
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if "/login" in page.url or "authwall" in page.url:
                    raise SessionExpired(
                        "LinkedIn session expired — run `python run.py linkedin-login` again.")
                for _ in range(3):  # a few scrolls to lazy-load more posts
                    page.mouse.wheel(0, 2200)
                    page.wait_for_timeout(1500)
                cards = page.query_selector_all(
                    "div.feed-shared-update-v2, div.update-components-text, "
                    "div.search-results-container [data-urn]")
                for card in cards[:max_posts]:
                    text = card.inner_text().strip()
                    if len(text) < 60:
                        continue
                    h = hashlib.sha1(text[:200].encode()).hexdigest()
                    if h in seen_hashes:
                        continue
                    seen_hashes.add(h)
                    link_el = card.query_selector("a[href*='/feed/update/'], a[href*='/posts/']")
                    post_url = link_el.get_attribute("href") if link_el else url
                    jobs.append(Job(
                        title=f"LinkedIn feed post — matched '{q}'",
                        company="",
                        location="",
                        url=post_url,
                        description=text[:3000],
                        source="linkedin_feed",
                    ))
        finally:
            browser.close()
    return jobs
