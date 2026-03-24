"""
Web scraper: fetches and cleans page text from any URL.
Uses requests + BeautifulSoup. Respects a configurable delay.
"""
import time
import re
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from .config import SCRAPER_DELAY

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; tidb-lead-bot/1.0; "
        "+https://tidbcloud.com) research/sales-intelligence"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_last_request_time: float = 0.0


def _polite_get(url: str, timeout: int = 20) -> requests.Response | None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < SCRAPER_DELAY:
        time.sleep(SCRAPER_DELAY - elapsed)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        _last_request_time = time.time()
        resp.raise_for_status()
        return resp
    except Exception:
        _last_request_time = time.time()
        return None


def scrape_text(url: str, max_chars: int = 6000) -> str | None:
    """Fetch a URL and return cleaned plain text (up to max_chars)."""
    resp = _polite_get(url)
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Remove boilerplate tags
    for tag in soup(["script", "style", "nav", "header", "footer",
                     "noscript", "iframe", "svg", "form"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text[:max_chars]


def extract_links(url: str, same_domain: bool = True) -> list[str]:
    """Extract all href links from a page, optionally filtered to same domain."""
    resp = _polite_get(url)
    if not resp:
        return []
    base_domain = urlparse(url).netloc
    soup = BeautifulSoup(resp.text, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        if same_domain and parsed.netloc != base_domain:
            continue
        links.append(full)
    return list(dict.fromkeys(links))  # deduplicate while preserving order


def extract_company_cards(url: str) -> list[dict]:
    """
    Generic company-card extractor for directory pages.
    Tries to find <a> tags with company names + external hrefs.
    Returns list of {"name": str, "website": str}.
    """
    resp = _polite_get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    base_domain = urlparse(url).netloc
    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https"):
            continue
        # Skip internal links and common noise
        if parsed.netloc == base_domain:
            continue
        if any(skip in parsed.netloc for skip in [
            "linkedin", "twitter", "facebook", "instagram",
            "youtube", "crunchbase", "google", "apple",
        ]):
            continue

        name = a.get_text(strip=True)
        if not name or len(name) < 3 or len(name) > 80:
            continue

        domain = parsed.netloc
        if domain not in seen:
            seen.add(domain)
            results.append({"name": name, "website": f"{parsed.scheme}://{parsed.netloc}"})

    return results
