"""Async web crawler for the knowledge graph ingestion pipeline.

Converts a URL into clean Markdown using:
  Playwright (JS-rendered HTML) → BeautifulSoup (noise removal) → markdownify

Design goals
------------
* No external SaaS APIs — fully local, works offline for intranet pages.
* Handles dynamic/SPA content via Playwright's real Chromium engine.
* Removes ads, navigation bars, sidebars, cookie banners, and boilerplate.
* Returns a truncated Markdown string ready for LLM concept extraction.
* Graceful degradation: falls back to ``requests`` + BS4 plain-text parse
  when Playwright is not installed or fails (e.g. missing system deps).

Usage
-----
::
    from core_orchestrator.web_crawler import crawl_url

    markdown = await crawl_url("https://example.com/article", timeout=30.0)

Returns an empty string on irrecoverable failure (caller handles logging).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum characters of Markdown returned to the caller.
# ~12k chars ≈ ~3k tokens — enough context for concept extraction without
# blowing through LLM context limits or embedding truncation.
_MAX_CHARS = 12_000

# Tags whose entire subtree we strip before converting to Markdown.
_NOISE_TAGS = [
    "script", "style", "noscript",
    "header", "footer", "nav", "aside",
    "form", "button", "input", "select", "textarea",
    "iframe", "embed", "object",
    "advertisement", "ads",
]

# CSS class / id substrings that typically indicate noise blocks.
# We remove any tag whose class or id contains one of these substrings.
_NOISE_PATTERNS = [
    "cookie", "consent", "gdpr", "banner",
    "sidebar", "widget", "ad-", "-ad",
    "promo", "newsletter", "popup", "modal",
    "share", "social", "comment", "related",
    "breadcrumb", "pagination", "menu",
    "footer", "header", "navbar", "nav-",
]


def _clean_html(html: str) -> str:
    """Remove noise from raw HTML and return cleaned HTML ready for markdownify."""
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
    except ImportError:
        logger.debug("[WebCrawler] beautifulsoup4 not installed — returning raw html")
        return html

    soup = BeautifulSoup(html, "html.parser")

    # Remove noise tags by tag name
    for tag_name in _NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove noise tags by class/id patterns
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        tag_id  = tag.get("id", "")
        combined = (classes + " " + tag_id).lower()
        if any(pat in combined for pat in _NOISE_PATTERNS):
            tag.decompose()

    # Try to narrow down to the main content area
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id=re.compile(r"content|main|body|article", re.I))
        or soup.find(class_=re.compile(r"content|main|body|article|post", re.I))
        or soup.find("body")
        or soup
    )

    return str(main)


def _html_to_markdown(html: str) -> str:
    """Convert cleaned HTML to Markdown."""
    try:
        import markdownify  # type: ignore[import]
        md = markdownify.markdownify(
            html,
            heading_style="ATX",
            bullets="-",
            strip=["img", "video", "audio"],
        )
        # Collapse excessive blank lines
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md.strip()
    except ImportError:
        # Fallback: crude tag-stripping
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


async def _crawl_with_playwright(url: str, timeout: float) -> Optional[str]:
    """Fetch *url* with Playwright and return raw HTML, or None on failure."""
    try:
        from playwright.async_api import async_playwright  # type: ignore[import]
    except ImportError:
        logger.debug("[WebCrawler] playwright not installed — cannot use headless browser")
        return None

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                ctx  = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    java_script_enabled=True,
                    locale="en-US",
                )
                page = await ctx.new_page()
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout * 1000,     # Playwright uses ms
                )
                # Small grace period for lazy-loaded content
                try:
                    await page.wait_for_load_state("networkidle", timeout=5_000)
                except Exception:
                    pass  # networkidle timeout is acceptable; content is usually there

                html = await page.content()
                return html
            finally:
                await browser.close()
    except Exception as exc:
        logger.warning("[WebCrawler] Playwright fetch failed for %s: %s", url, exc)
        return None


async def _crawl_with_urllib(url: str, timeout: float) -> Optional[str]:
    """Fallback: plain HTTP GET with urllib (no JS rendering)."""
    import urllib.request
    import urllib.error

    def _sync() -> Optional[str]:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; AegisBot/2.0; "
                        "+https://github.com/aegis-harness)"
                    )
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = "utf-8"
                ct = resp.headers.get_content_charset()
                if ct:
                    charset = ct
                return resp.read().decode(charset, errors="replace")
        except Exception as exc:
            logger.warning("[WebCrawler] urllib fallback failed for %s: %s", url, exc)
            return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


async def crawl_url(url: str, timeout: float = 30.0) -> str:
    """Fetch *url* and return clean Markdown content.

    Parameters
    ----------
    url:
        Absolute HTTP/HTTPS URL to crawl.
    timeout:
        Per-step timeout in seconds (applied to browser launch + navigation
        and separately to the urllib fallback).

    Returns
    -------
    str
        Cleaned Markdown (≤ ``_MAX_CHARS`` characters).
        Empty string if crawling failed completely.

    Notes
    -----
    * Tries Playwright first (handles JS-rendered SPAs).
    * Falls back to plain ``urllib`` GET if Playwright is unavailable
      or times out.
    * Both paths run inside an executor so the event loop is never blocked.
    """
    if not url.startswith(("http://", "https://")):
        logger.warning("[WebCrawler] Rejecting non-HTTP URL: %s", url[:80])
        return ""

    logger.info("[WebCrawler] Crawling %s (timeout=%.0fs)", url, timeout)

    # Try Playwright first
    html = await _crawl_with_playwright(url, timeout)

    # Fallback to urllib if Playwright unavailable or failed
    if not html:
        logger.info("[WebCrawler] Falling back to urllib for %s", url)
        html = await _crawl_with_urllib(url, timeout)

    if not html:
        logger.warning("[WebCrawler] All crawl methods failed for %s", url)
        return ""

    # Clean and convert
    cleaned_html = _clean_html(html)
    markdown     = _html_to_markdown(cleaned_html)

    if not markdown.strip():
        logger.warning("[WebCrawler] Empty markdown after conversion for %s", url)
        return ""

    # Truncate to stay within LLM context limits
    truncated = markdown[:_MAX_CHARS]
    logger.info(
        "[WebCrawler] Done — %d chars (from %d raw html chars) for %s",
        len(truncated), len(html), url,
    )
    return truncated
