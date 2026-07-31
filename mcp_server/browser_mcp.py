import json
from mcp.server.fastmcp import FastMCP
from playwright.sync_api import sync_playwright

from scrapers import fetch_naukri, fetch_linkedin, fetch_glassdoor

# Initialize FastMCP Server
mcp = FastMCP("Browser Job Scraper")

def get_browser_context():
    """Connects to the local Chrome instance with remote debugging enabled."""
    playwright = sync_playwright().start()
    try:
        # Note: You MUST start Chrome with:
        # chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome_dev_profile"
        browser = playwright.chromium.connect_over_cdp("http://localhost:9222")
        # Reuse the first context, which contains the active user session
        context = browser.contexts[0]
        return playwright, browser, context
    except Exception as e:
        playwright.stop()
        raise RuntimeError(f"Failed to connect to browser on port 9222. Ensure Chrome is running with remote debugging enabled. Error: {e}")

@mcp.tool()
def search_jobs_naukri(query: str, location: str, count: int = 10) -> str:
    """Search for jobs on Naukri using the active browser session.
    
    Args:
        query: The job title or skill to search for.
        location: The city or location.
        count: The maximum number of jobs to fetch.
    """
    playwright, browser, context = get_browser_context()
    try:
        jobs = fetch_naukri(context, query, location, count)
        return json.dumps(jobs, indent=2)
    finally:
        browser.close()
        playwright.stop()

@mcp.tool()
def search_jobs_linkedin(query: str, location: str, count: int = 10) -> str:
    """Search for jobs on LinkedIn using the active browser session.
    
    Args:
        query: The job title or skill to search for.
        location: The city or location.
        count: The maximum number of jobs to fetch.
    """
    playwright, browser, context = get_browser_context()
    try:
        jobs = fetch_linkedin(context, query, location, count)
        return json.dumps(jobs, indent=2)
    finally:
        browser.close()
        playwright.stop()

@mcp.tool()
def search_jobs_glassdoor(query: str, location: str, count: int = 10) -> str:
    """Search for jobs on Glassdoor using the active browser session.
    
    Args:
        query: The job title or skill to search for.
        location: The city or location.
        count: The maximum number of jobs to fetch.
    """
    playwright, browser, context = get_browser_context()
    try:
        jobs = fetch_glassdoor(context, query, location, count)
        return json.dumps(jobs, indent=2)
    finally:
        browser.close()
        playwright.stop()

if __name__ == "__main__":
    print("Starting Browser Job Scraper MCP Server...")
    mcp.run()
