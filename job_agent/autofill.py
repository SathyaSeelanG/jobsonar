"""Semi-auto apply: open the job page in a real browser, pre-fill what we can,
then WAIT — you review and click Submit yourself. Never auto-submits."""
import re
from pathlib import Path

FIELD_MAP = {
    r"first.?name": lambda p: p.get("name", "").split()[0] if p.get("name") else "",
    r"last.?name": lambda p: p.get("name", "").split()[-1] if p.get("name") else "",
    r"full.?name|^name$": lambda p: p.get("name", ""),
    r"e-?mail": lambda p: p.get("email", ""),
    r"phone|mobile": lambda p: p.get("phone", ""),
    r"linkedin": lambda p: p.get("linkedin_url", ""),
    r"github": lambda p: p.get("github_url", ""),
    r"portfolio|website": lambda p: p.get("portfolio_url", ""),
    r"location|city": lambda p: p.get("location", ""),
    r"notice": lambda p: p.get("form_answers", {}).get("notice_period", ""),
    r"salary|compensation|ctc": lambda p: p.get("form_answers", {}).get("expected_salary", ""),
}


def apply_semi_auto(url: str, profile: dict):
    """Open URL in Chromium, pre-fill recognizable fields, upload resume, pause."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        filled = _fill_fields(page, profile)
        uploaded = _upload_resume(page, profile)

        print(f"\n  Pre-filled {filled} field(s)." + (" Resume attached." if uploaded else ""))
        print("  >> Review the form in the browser, complete anything missing,")
        print("  >> and click SUBMIT yourself. Press Enter here when done...")
        input()
        browser.close()


def _fill_fields(page, profile: dict) -> int:
    filled = 0
    for inp in page.query_selector_all("input[type=text], input[type=email], input[type=tel], input:not([type]), textarea"):
        try:
            label = " ".join(filter(None, [
                inp.get_attribute("name") or "",
                inp.get_attribute("id") or "",
                inp.get_attribute("placeholder") or "",
                inp.get_attribute("aria-label") or "",
            ])).lower()
            if not label or inp.input_value():
                continue
            for pattern, getter in FIELD_MAP.items():
                if re.search(pattern, label):
                    value = getter(profile)
                    if value:
                        inp.fill(value)
                        filled += 1
                    break
        except Exception:
            continue
    return filled


def _upload_resume(page, profile: dict) -> bool:
    resume = profile.get("resume_path", "")
    if not resume or not Path(resume).exists():
        return False
    for inp in page.query_selector_all("input[type=file]"):
        try:
            inp.set_input_files(resume)
            return True
        except Exception:
            continue
    return False
