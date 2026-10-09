from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
TIMEOUT = 25
MAX_PAGES = 500


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
    })
    return session


def _canonical(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    return parsed._replace(scheme="https", netloc=parsed.netloc.lower()).geturl().rstrip("/")


def _page_links(soup: BeautifulSoup, current_url: str) -> list[str]:
    candidates = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        text = " ".join(anchor.get_text(" ", strip=True).lower().split())
        rel = " ".join(anchor.get("rel", [])).lower()
        if "next" in rel or text in {"next", "next »", "›", "»", "older"}:
            candidates.append(urljoin(current_url, href))
    # Include conventional pagination links only when they are in a pagination container.
    for anchor in soup.select(".pagination a[href], nav[aria-label*=pagination] a[href]"):
        candidates.append(urljoin(current_url, anchor["href"]))
    result = []
    seen = set()
    for candidate in candidates:
        normalized = _canonical(candidate)
        if normalized not in seen and urlparse(normalized).netloc == urlparse(current_url).netloc:
            seen.add(normalized)
            result.append(candidate)
    return result


def _extract_cards(soup: BeautifulSoup, page_url: str) -> list[dict]:
    found = {}
    # Site layout has used section .card for catalogue entries; additional
    # selectors keep the adapter tolerant of minor markup changes.
    cards = soup.select("section .card, .video-card, .movie-card, article.card")
    for card in cards:
        if card.select_one(".bg-danger"):
            continue
        anchor = card.select_one('a[href*="/video/"], a[href*="/watch/"], a[href*="/movie/"]')
        if not anchor:
            anchor = card.select_one("a[href]")
        if not anchor:
            continue
        page_link = _canonical(urljoin(page_url, anchor.get("href", "")))
        parsed = urlparse(page_link)
        if parsed.netloc != urlparse(page_url).netloc:
            continue
        if not re.search(r"/(video|watch|movie)/", parsed.path, re.I):
            continue
        title = (
            anchor.get("title")
            or card.select_one("[title]")
            and card.select_one("[title]").get("title")
            or card.select_one("h2, h3, .card-title, .title")
            and card.select_one("h2, h3, .card-title, .title").get_text(" ", strip=True)
            or anchor.get_text(" ", strip=True)
            or parsed.path.rstrip("/").split("/")[-1]
        )
        # Prefer a stable numeric/source slug from the canonical path.
        match = re.search(r"/(?:video|watch|movie)/(\d+)(?:/|$)", parsed.path, re.I)
        source_id = match.group(1) if match else parsed.path.rstrip("/").split("/")[-1]
        if source_id:
            found[source_id] = {
                "source_id": source_id,
                "title": " ".join(str(title).split())[:300],
                "page_url": page_link,
            }
    return list(found.values())


def discover_channel_entries(channel_url: str) -> list[dict]:
    parsed = urlparse(channel_url)
    if parsed.scheme != "https" or parsed.hostname != "javtiful.com":
        raise ValueError("This source adapter currently accepts HTTPS javtiful.com channel URLs only.")
    if not parsed.path.startswith("/channel/"):
        raise ValueError("Expected a Javtiful channel URL such as /channel/s1-no1-style.")

    session = _session()
    queue = [channel_url]
    visited_pages = set()
    entries = {}
    while queue and len(visited_pages) < MAX_PAGES:
        current = queue.pop(0)
        normalized = _canonical(current)
        if normalized in visited_pages:
            continue
        visited_pages.add(normalized)
        response = session.get(current, timeout=TIMEOUT)
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", "").lower():
            raise RuntimeError(f"Expected HTML from {current}")
        soup = BeautifulSoup(response.text, "html.parser")
        page_entries = _extract_cards(soup, response.url)
        for item in page_entries:
            entries[item["source_id"]] = item

        for candidate in _page_links(soup, response.url):
            target = urlparse(candidate)
            # Avoid enqueuing video pages and unrelated site sections.
            if target.path.startswith(parsed.path.rstrip("/") + "/") or target.path == parsed.path:
                if _canonical(candidate) not in visited_pages and _canonical(candidate) not in {
                    _canonical(x) for x in queue
                }:
                    queue.append(candidate)
        if queue:
            time.sleep(0.35)

    if len(visited_pages) >= MAX_PAGES and queue:
        raise RuntimeError(f"Stopped at MAX_PAGES={MAX_PAGES}; pagination may be incomplete.")
    if not entries:
        raise RuntimeError(
            "No video cards were found. The page markup may have changed or the server returned a challenge page; "
            "the scanner refuses to save an empty inventory as a successful scan."
        )
    return list(entries.values())
