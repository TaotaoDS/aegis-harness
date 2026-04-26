"""Web browser tools: headless Playwright-based web search and URL reading.

Public API
----------
search_web(query, engine="bing", num_results=5) -> str
    Navigate a search engine, extract top N results as JSON.

read_url(url) -> str
    Load a page, strip boilerplate, return clean Markdown-ish plain text.

WebBrowserError
    Raised on timeout, navigation failure, or parse error.
    Has a ``retryable`` attribute: True for transient network faults,
    False for structural errors (e.g. page permanently blocked).

Both functions use the sync Playwright API to match the codebase's synchronous
thread-based execution model. Each call opens and closes its own browser context
— no shared state, fully thread-safe for ParallelExecutor workers.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TIMEOUT_MS = 30_000    # 30 s per navigation
_MAX_CHARS   = 4_000    # output cap — prevents context bloat / token waste

_SEARCH_ENGINES: Dict[str, str] = {
    "bing":  "https://www.bing.com/search?q={query}",
    "sogou": "https://www.sogou.com/web?query={query}",
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# CSS selectors for extracting search result anchors per engine.
# Targets stable semantic class names rather than layout-specific markup.
_RESULT_SELECTORS: Dict[str, str] = {
    "bing":  "li.b_algo h2 a",
    "sogou": "div.vrwrap h3 a",
}

# HTML tags whose subtrees contain no useful content and should be stripped.
_STRIP_TAGS: List[str] = [
    "script", "style", "nav", "footer", "aside",
    "header", "form", "iframe", "noscript",
]

# ARIA landmark roles whose subtrees should be stripped.
_STRIP_ROLES: List[str] = ["banner", "navigation", "complementary", "contentinfo"]


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class WebBrowserError(Exception):
    """Raised when a browser operation fails.

    Attributes
    ----------
    retryable : bool
        True  — transient fault (network timeout, DNS failure); worth retrying.
        False — structural fault (blocked, parse error, bad URL); do not retry.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


# ---------------------------------------------------------------------------
# Private: browser context factory
# ---------------------------------------------------------------------------

def _launch_browser():
    """Start Playwright and return a (pw, browser, context) triple.

    Caller must close all three in reverse order inside a finally block.
    Uses --no-sandbox because Docker containers lack user-namespace support
    needed by the Chromium sandbox; OS-level container isolation compensates.
    """
    from playwright.sync_api import sync_playwright  # lazy — not always installed

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = browser.new_context(
        user_agent=_USER_AGENT,
        java_script_enabled=True,
        viewport={"width": 1280, "height": 800},
    )
    return pw, browser, context


# ---------------------------------------------------------------------------
# Private: search result extractor
# ---------------------------------------------------------------------------

def _extract_search_results(page, engine: str, num_results: int) -> List[Dict[str, str]]:
    """Extract title+url pairs from a loaded search results page."""
    selector = _RESULT_SELECTORS[engine]
    anchors = page.query_selector_all(selector)
    results: List[Dict[str, str]] = []
    for a in anchors[:num_results]:
        title = (a.inner_text() or "").strip()
        href  = (a.get_attribute("href") or "").strip()
        if title and href and href.startswith("http"):
            results.append({"title": title, "url": href})
    return results


# ---------------------------------------------------------------------------
# Private: HTML → plain text
# ---------------------------------------------------------------------------

def _html_to_text(html: str, title: str) -> str:
    """Strip boilerplate from HTML and return clean plain text.

    Requires beautifulsoup4. Uses html.parser (stdlib) — no C extension needed.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise WebBrowserError(
            "beautifulsoup4 is not installed. Add 'beautifulsoup4>=4.12.0' to requirements.txt.",
            retryable=False,
        ) from exc

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    for role in _STRIP_ROLES:
        for el in soup.find_all(attrs={"role": role}):
            el.decompose()

    raw = soup.get_text(separator="\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", raw).strip()
    return f"# {title}\n\n{cleaned}"


# ---------------------------------------------------------------------------
# Public: search_web
# ---------------------------------------------------------------------------

def search_web(
    query: str,
    engine: str = "bing",
    num_results: int = 5,
) -> str:
    """Search the web and return top N results as a JSON string.

    Parameters
    ----------
    query      : The search query.
    engine     : "bing" (default) or "sogou".
    num_results: Number of results to return (capped at 10).

    Returns
    -------
    JSON string: {"results": [{"title": "...", "url": "..."}, ...]}

    Raises
    ------
    WebBrowserError
        retryable=True  on navigation timeout or DNS failure.
        retryable=False on unsupported engine or zero results extracted.
    """
    if engine not in _SEARCH_ENGINES:
        raise WebBrowserError(
            f"Unsupported search engine '{engine}'. Choose from: {list(_SEARCH_ENGINES)}",
            retryable=False,
        )
    num_results = min(max(1, num_results), 10)
    url = _SEARCH_ENGINES[engine].format(query=query.replace(" ", "+"))

    pw, browser, context = _launch_browser()
    try:
        page = context.new_page()
        try:
            page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
        except Exception as exc:
            raise WebBrowserError(
                f"Navigation to {engine} failed: {exc}",
                retryable=True,
            ) from exc

        time.sleep(random.uniform(0.5, 1.5))

        results = _extract_search_results(page, engine, num_results)
        if not results:
            raise WebBrowserError(
                f"No results extracted from {engine} for query '{query}'. "
                "The page structure may have changed or the query was blocked.",
                retryable=False,
            )

        logger.debug("[web_browser] search_web(%r) → %d results", query, len(results))
        return json.dumps({"results": results})
    finally:
        context.close()
        browser.close()
        pw.stop()


# ---------------------------------------------------------------------------
# Public: read_url
# ---------------------------------------------------------------------------

def read_url(url: str) -> str:
    """Load a URL and return its main content as clean plain text.

    Strips scripts, styles, navigation, footers, ads, and sidebars.
    Output is capped at _MAX_CHARS characters to prevent context bloat.

    Parameters
    ----------
    url : Full URL including http:// or https:// scheme.

    Returns
    -------
    Plain-text string with page title as a Markdown H1 heading.
    Capped at 4 000 characters.

    Raises
    ------
    WebBrowserError
        retryable=True  on navigation timeout.
        retryable=False on invalid URL scheme or completely empty content.
    """
    if not url.startswith(("http://", "https://")):
        raise WebBrowserError(
            f"Invalid URL scheme: '{url}'. Only http/https supported.",
            retryable=False,
        )

    pw, browser, context = _launch_browser()
    try:
        page = context.new_page()
        try:
            page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
        except Exception as exc:
            raise WebBrowserError(
                f"Failed to load URL '{url}': {exc}",
                retryable=True,
            ) from exc

        time.sleep(random.uniform(0.3, 0.8))

        html  = page.content()
        title = page.title() or url
        text  = _html_to_text(html, title)

        if not text.strip():
            raise WebBrowserError(
                f"Extracted empty content from '{url}'. "
                "The page may require JavaScript rendering or login.",
                retryable=False,
            )

        logger.debug("[web_browser] read_url(%r) → %d chars", url, len(text))
        return text[:_MAX_CHARS]
    finally:
        context.close()
        browser.close()
        pw.stop()


# ---------------------------------------------------------------------------
# Tool definitions (provider-agnostic, matches WRITE_FILE_TOOL pattern)
# ---------------------------------------------------------------------------

SEARCH_WEB_TOOL: Dict[str, Any] = {
    "name": "search_web",
    "description": (
        "Search the web for current information using Bing or Sogou. "
        "Use when the task needs facts, documentation, library versions, or any "
        "knowledge that may have changed after your training cutoff. "
        "Returns JSON: {\"results\": [{\"title\": \"...\", \"url\": \"...\"}]}. "
        "Follow up with read_url to fetch the full content of a promising result. "
        "DO NOT use when your existing knowledge is sufficient."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Concise web search string.",
            },
            "engine": {
                "type": "string",
                "enum": ["bing", "sogou"],
                "description": (
                    "Search engine. Default 'bing' for English content; "
                    "'sogou' for Chinese-language queries."
                ),
            },
            "num_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Number of results to return (default 5).",
            },
        },
        "required": ["query"],
    },
}

READ_URL_TOOL: Dict[str, Any] = {
    "name": "read_url",
    "description": (
        "Load a URL and return its main text content as clean plain text (~4000 chars max). "
        "Use after search_web to read the full content of a specific search result. "
        "Output is capped to prevent context bloat — call on multiple URLs if needed. "
        "Returns text with page title as a heading. "
        "Only handles HTML pages — not PDFs, images, or binary files."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL including http:// or https:// scheme.",
            },
        },
        "required": ["url"],
    },
}
