import urllib.parse
from bs4 import BeautifulSoup
import time
import random

# Delay to mimic human reading and avoid overloading the browser
DELAY = 1.0

def _q(s: str) -> str:
    return urllib.parse.quote_plus(s)

def fetch_naukri(context, query: str, location: str, count: int = 10) -> list[dict]:
    """Scrapes Naukri using the active browser context."""
    slug = lambda s: ''.join(c if c.isalnum() else '-' for c in s.lower()).strip('-')
    url = f"https://www.naukri.com/{slug(query)}-jobs-in-{slug(location)}"
    
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector(".srp-jobtuple-wrapper, article.jobTuple", timeout=10000)
    
    jobs = []
    cards = page.query_selector_all(".srp-jobtuple-wrapper, article.jobTuple")
    
    for card in cards[:count]:
        title_el = card.query_selector("a.title")
        if not title_el:
            continue
        comp_el = card.query_selector(".comp-name, a.comp-name, a.subTitle")
        loc_el = card.query_selector(".locWdth, .loc span, .location span")
        
        job_url = title_el.get_attribute("href") or ""
        
        jobs.append({
            "title": title_el.inner_text().strip(),
            "company": comp_el.inner_text().strip() if comp_el else "",
            "location": loc_el.inner_text().strip() if loc_el else location,
            "url": job_url,
            "description": card.inner_text()[:1000],
            "source": "naukri"
        })
    
    # Try to hydrate top 3 with full JD
    for job in jobs[:3]:
        if not job["url"]: continue
        time.sleep(DELAY + random.uniform(0, 1))
        try:
            page.goto(job["url"], wait_until="domcontentloaded", timeout=15000)
            el = page.query_selector(".styles_JDC__dang-inner-html__h0K4t, .job-desc, section.job-desc")
            if el:
                job["description"] = el.inner_text().strip()[:6000]
        except Exception:
            pass
            
    page.close()
    return jobs

def fetch_linkedin(context, query: str, location: str, count: int = 10) -> list[dict]:
    """Scrapes LinkedIn using the active browser context."""
    url = f"https://www.linkedin.com/jobs/search/?keywords={_q(query)}&location={_q(location)}"
    
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    
    # Wait for the job list to load
    page.wait_for_selector(".jobs-search-results__list-item, .job-card-container", timeout=15000)
    
    jobs = []
    cards = page.query_selector_all(".jobs-search-results__list-item, .job-card-container")
    
    for card in cards[:count]:
        # Click the card to load it in the right pane
        try:
            card.scroll_into_view_if_needed()
            card.click()
            time.sleep(DELAY + random.uniform(0.5, 1.5))
        except Exception:
            continue
            
        # Parse the right pane
        try:
            detail_pane = page.query_selector(".jobs-search__job-details--container, .job-view-layout")
            if not detail_pane:
                continue
                
            title_el = detail_pane.query_selector("h2, .t-24")
            comp_el = detail_pane.query_selector(".jobs-unified-top-card__company-name, .job-details-jobs-unified-top-card__company-name")
            loc_el = detail_pane.query_selector(".jobs-unified-top-card__bullet, .job-details-jobs-unified-top-card__primary-description")
            desc_el = detail_pane.query_selector(".jobs-description__container, #job-details")
            
            # The URL changes when you click a job, we can grab it from the page URL
            job_url = page.url
            
            jobs.append({
                "title": title_el.inner_text().strip() if title_el else "Unknown Title",
                "company": comp_el.inner_text().strip() if comp_el else "",
                "location": loc_el.inner_text().strip() if loc_el else location,
                "url": job_url.split("?")[0], # clean url
                "description": desc_el.inner_text().strip()[:6000] if desc_el else "",
                "source": "linkedin"
            })
        except Exception:
            continue
            
    page.close()
    return jobs

def fetch_glassdoor(context, query: str, location: str, count: int = 10) -> list[dict]:
    """Scrapes Glassdoor using the active browser context."""
    url = f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={_q(query)}&locT=&locId=&locKeyword={_q(location)}"
    
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    
    # Wait for the job cards
    page.wait_for_selector("[data-test='job-listing'], .react-job-listing", timeout=15000)
    
    jobs = []
    cards = page.query_selector_all("[data-test='job-listing'], .react-job-listing")
    
    for card in cards[:count]:
        try:
            card.scroll_into_view_if_needed()
            card.click(force=True)
            time.sleep(DELAY + random.uniform(0.5, 1.5))
        except Exception:
            continue
            
        try:
            # Details load in the right pane usually
            desc_el = page.query_selector(".JobDetails_jobDescriptionWrapper__9htqj, #JobDescriptionContainer")
            title_el = page.query_selector("[data-test='job-title']") or card.query_selector("[data-test='job-link']")
            comp_el = page.query_selector("[data-test='employer-name']")
            loc_el = page.query_selector("[data-test='location']")
            
            job_url = page.url
            
            jobs.append({
                "title": title_el.inner_text().strip() if title_el else "Unknown Title",
                "company": comp_el.inner_text().strip() if comp_el else "",
                "location": loc_el.inner_text().strip() if loc_el else location,
                "url": job_url,
                "description": desc_el.inner_text().strip()[:6000] if desc_el else card.inner_text()[:1000],
                "source": "glassdoor"
            })
        except Exception:
            continue
            
    page.close()
    return jobs
