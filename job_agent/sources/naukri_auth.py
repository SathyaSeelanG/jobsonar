"""Naukri authenticated search via CDP — auto-launches your Chrome.

Naukri blocks headless scrapers. This connects to your REAL Chrome (via CDP)
where Naukri is logged in. If Chrome isn't running on the debug port, it
auto-launches it using your default profile — no manual steps needed.

Usage:
  Set naukri_auth.enabled: true in config/search.yaml, then:
    python run.py search           # runs all sources including Naukri auth
    python run.py naukri-search    # runs ONLY Naukri auth search
"""
import subprocess
import time
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error

from ..models import Job
from ..util import default_chrome_binary, default_chrome_user_data_dir

# Resolved from the running user's home directory, not hardcoded, so no
# machine-specific path ships in the repo. Override via naukri_auth.chrome_path
# / naukri_auth.user_data_dir in config/search.yaml.
CHROME_DEFAULT = default_chrome_binary()
USER_DATA_DEFAULT = default_chrome_user_data_dir()


class SessionExpired(Exception):
    """Naukri redirected to login — session is stale."""


def _slug(s: str) -> str:
    return urllib.parse.quote(s.replace(" ", "-").lower())


def _chrome_running(cdp_port: int = 9222) -> bool:
    """Check if a Chrome instance is already listening on the CDP port."""
    try:
        urllib.request.urlopen(f"http://localhost:{cdp_port}/json/version", timeout=2)
        return True
    except (urllib.error.URLError, ConnectionResetError, OSError):
        return False


def _launch_chrome(
    chrome_path: str = CHROME_DEFAULT,
    user_data_dir: str = USER_DATA_DEFAULT,
    profile_directory: str = "Default",
    cdp_port: int = 9222,
):
    """Launch Chrome with remote debugging using the specified profile."""
    proc = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            f"--profile-directory={profile_directory}",
            "--no-first-run",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait up to 10s for Chrome to start listening
    for _ in range(20):
        if _chrome_running(cdp_port):
            return
        time.sleep(0.5)

    exit_code = proc.poll()
    if exit_code is not None:
        raise RuntimeError(
            f"Chrome process exited immediately (code {exit_code}). "
            "This usually means Chrome is already running normally. You must COMPLETELY close all Chrome windows "
            "(and background extensions) before running this, or set a separate 'user_data_dir' in config/search.yaml."
        )

    raise RuntimeError(
        f"Chrome didn't start on port {cdp_port}. Check that {chrome_path} exists."
    )


def search_naukri_auth(
    cdp_port: int = 9222,
    queries: list[str] | None = None,
    location: str = "Chennai",
    max_results: int = 20,
    chrome_path: str = CHROME_DEFAULT,
    user_data_dir: str = USER_DATA_DEFAULT,
    profile_directory: str = "Default",
) -> list[Job]:
    """Search Naukri via your real Chrome.

    Auto-launches Chrome with your default profile if it's not already
    running on the CDP port. Closes Chrome after if we launched it.
    """
    from playwright.sync_api import sync_playwright

    launched = False
    if not _chrome_running(cdp_port):
        _launch_chrome(chrome_path, user_data_dir, profile_directory, cdp_port)
        launched = True

    jobs: list[Job] = []
    seen_urls: set[str] = set()
    cdp_url = f"http://localhost:{cdp_port}"

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        try:
            for query in (queries or []):
                url = (
                    f"https://www.naukri.com/{_slug(query)}-jobs-in-{_slug(location)}?sort=r"
                )
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                if "nlogin" in page.url or "login" in page.url.lower():
                    raise SessionExpired(
                        "Naukri not logged in — log into Naukri in the Chrome window "
                        "that opened and try again."
                    )

                page.wait_for_timeout(3000)

                for _ in range(3):
                    page.mouse.wheel(0, 2500)
                    page.wait_for_timeout(1500)

                cards = page.query_selector_all(
                    "div.jobTuple, article.jobTuple, div[class*='jobCard'], "
                    "div[class*='job-tuple'], section[class*='job']"
                )

                count = 0
                for card in cards:
                    if count >= max_results:
                        break

                    title_el = (
                        card.query_selector("a.title, a[class*='title'], "
                                            "a[class*='jobTitle']")
                    )
                    if not title_el:
                        continue
                    title = title_el.inner_text().strip()
                    if not title:
                        continue

                    company_el = card.query_selector(
                        "a[class*='subTitle'], a[class*='company'], "
                        "span[class*='company']"
                    )
                    company = company_el.inner_text().strip() if company_el else ""

                    loc_el = card.query_selector(
                        "span[class*='location'], li[class*='location'], "
                        "span[class*='loc']"
                    )
                    loc = loc_el.inner_text().strip() if loc_el else location

                    job_url = title_el.get_attribute("href") or ""
                    if job_url and not job_url.startswith("http"):
                        job_url = "https://www.naukri.com" + job_url

                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    desc_el = card.query_selector(
                        "span[class*='desc'], div[class*='description'], "
                        "span[class*='jobDescription']"
                    )
                    description = desc_el.inner_text().strip() if desc_el else ""

                    salary_el = card.query_selector(
                        "span[class*='salary'], li[class*='salary']"
                    )
                    salary = salary_el.inner_text().strip() if salary_el else ""

                    date_el = card.query_selector(
                        "span[class*='date'], span[class*='post-day'], span[class*='job-post-day']"
                    )
                    posted_at = date_el.inner_text().strip() if date_el else ""

                    jobs.append(Job(
                        title=title,
                        company=company,
                        location=loc,
                        url=job_url,
                        description=description[:3000],
                        salary=salary,
                        source="naukri_auth",
                        posted_at=posted_at,
                    ))
                    count += 1

        finally:
            page.close()
            if launched:
                browser.close()

    return jobs
