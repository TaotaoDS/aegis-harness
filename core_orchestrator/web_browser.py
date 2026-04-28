"""Web browser tools: headless Playwright-based web search and URL reading.

Public API
----------
search_web(query, engine="auto", num_results=5, client_ip=None) -> str
    Search the web and return top N results as a JSON string.

    engine values
    ~~~~~~~~~~~~~
    "auto"       — auto-select based on client IP geolocation:
                     China (CN) → Bing with Chinese locale (httpx, no browser)
                     Elsewhere  → DuckDuckGo (httpx, no browser)
                   Falls back to the other engine if the primary fails.
    "duckduckgo" — DuckDuckGo lite HTML endpoint via httpx (fast, no Playwright)
    "bing"       — Bing search via httpx (li.b_algo results, mkt=zh-CN aware)
    "sogou"      — Sogou via headless Playwright (legacy; kept for compatibility)

read_url(url) -> str
    Load a page, strip boilerplate, return clean Markdown-ish plain text.

WebBrowserError
    Raised on timeout, navigation failure, or parse error.
    Has a ``retryable`` attribute: True for transient network faults,
    False for structural errors (e.g. page permanently blocked).

Playwright is only used for read_url and engine="sogou". All httpx-based paths
are synchronous and thread-safe for ParallelExecutor workers.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IP → region cache  (avoids repeated geolocation API calls for same IP)
# ---------------------------------------------------------------------------

_ip_region_cache: Dict[str, Tuple[str, float]] = {}   # ip → (country_code, timestamp)
_IP_CACHE_TTL = 3600.0   # 1 hour

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TIMEOUT_MS = 30_000    # 30 s per navigation
_MAX_CHARS   = 4_000    # output cap — prevents context bloat / token waste

_SEARCH_ENGINES: Dict[str, str] = {
    # "bing" and "duckduckgo" are handled by httpx scrapers (no Playwright).
    # "sogou" still uses Playwright (legacy; URL-obfuscated so httpx can't decode hrefs).
    # "auto" is a meta-engine that picks bing/duckduckgo based on client IP.
    "auto":       "",
    "bing":       "https://www.bing.com/search?q={query}&mkt={mkt}&setlang={lang}&count={count}",
    "sogou":      "https://www.sogou.com/web?query={query}",
    "duckduckgo": "https://html.duckduckgo.com/html/?q={query}",
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

def _search_duckduckgo(query: str, num_results: int) -> List[Dict[str, str]]:
    """Lightweight httpx-based DuckDuckGo HTML scraper.

    Faster (no Chromium boot) and far less likely to be blocked than the
    JS-rendered engines above.  Falls back gracefully if httpx isn't
    installed by raising WebBrowserError(retryable=False).
    """
    try:
        import httpx
    except ImportError as exc:
        raise WebBrowserError("httpx not installed", retryable=False) from exc

    url = _SEARCH_ENGINES["duckduckgo"].format(query=query.replace(" ", "+"))
    headers = {"User-Agent": _USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=20.0) as c:
            resp = c.get(url)
        resp.raise_for_status()
    except Exception as exc:
        raise WebBrowserError(f"DuckDuckGo request failed: {exc}", retryable=True) from exc

    html = resp.text

    # DuckDuckGo returns a CAPTCHA / anomaly challenge when our server IP is
    # rate-limited or flagged.  Detect it and raise retryable so auto-mode
    # can fall back to Bing instead of silently returning 0 results.
    if "anomaly.js" in html and ("botnet" in html or "challenge" in html.lower()):
        raise WebBrowserError(
            "DuckDuckGo returned a bot-challenge page (rate-limited). "
            "Will retry via fallback engine.",
            retryable=True,
        )

    # Each result block looks like:
    #   <a class="result__a" href="...">Title</a>
    #   ... <a class="result__snippet" ...>Snippet</a>
    anchor_re = re.compile(
        r'<a\s+[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.+?)</a>',
        re.DOTALL,
    )
    snippet_re = re.compile(
        r'<a\s+[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.+?)</a>',
        re.DOTALL,
    )

    anchors  = anchor_re.findall(html)
    snippets = snippet_re.findall(html)

    def _strip_tags(s: str) -> str:
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"&amp;",  "&", s)
        s = re.sub(r"&quot;", '"', s)
        s = re.sub(r"&#x27;", "'", s)
        s = re.sub(r"&#39;",  "'", s)
        s = re.sub(r"&lt;",   "<", s)
        s = re.sub(r"&gt;",   ">", s)
        s = re.sub(r"&nbsp;", " ", s)
        return s.strip()

    def _decode_ddg_url(href: str) -> str:
        # DDG wraps URLs in /l/?uddg=<encoded>
        if href.startswith("/l/?") or href.startswith("//duckduckgo.com/l/?"):
            from urllib.parse import urlparse, parse_qs, unquote
            qs = parse_qs(urlparse(href).query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        if href.startswith("//"):
            return "https:" + href
        return href

    results: List[Dict[str, str]] = []
    for i, (href, raw_title) in enumerate(anchors[:num_results * 2]):  # over-fetch to cover ads
        url = _decode_ddg_url(href)
        title = _strip_tags(raw_title)
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        # Skip DDG ad redirect URLs (y.js?ad_domain=...) — keep only real results
        if not url or "duckduckgo.com/y.js" in url or not url.startswith("http"):
            continue
        if title:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= num_results:
            break
    return results


def _geolocate_ip(ip: str) -> str:
    """Return ISO-3166-1 alpha-2 country code for *ip*, or '' on failure.

    Uses ip-api.com (free tier, no API key, 45 req/min).
    Results are cached in-process for ``_IP_CACHE_TTL`` seconds so repeated
    calls for the same visitor IP don't count against the rate limit.

    Private / loopback addresses (127.x, 10.x, 192.168.x, ::1, etc.) are
    returned as '' immediately — no network call.
    """
    import ipaddress

    # Skip non-routable addresses (local dev / Docker internal)
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return ""
    except ValueError:
        return ""

    now = time.time()
    cached = _ip_region_cache.get(ip)
    if cached and now - cached[1] < _IP_CACHE_TTL:
        return cached[0]

    try:
        import httpx
        resp = httpx.get(
            f"http://ip-api.com/json/{ip}?fields=countryCode",
            timeout=3.0,
        )
        code: str = resp.json().get("countryCode", "") if resp.status_code == 200 else ""
    except Exception as exc:
        logger.debug("[web_browser] geolocate %s failed: %s", ip, exc)
        code = ""

    _ip_region_cache[ip] = (code, now)
    logger.debug("[web_browser] geolocate %s → %r", ip, code)
    return code


def _search_bing_httpx(query: str, num_results: int, *, cn_locale: bool = False) -> List[Dict[str, str]]:
    """httpx-based Bing scraper — no Playwright required.

    Uses ``li.b_algo h2 a`` anchors which Bing has kept stable across redesigns.
    ``cn_locale=True`` adds ``mkt=zh-CN&setlang=zh-CN&cc=CN`` for Chinese-biased
    results (better coverage of Chinese-language content).
    """
    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise WebBrowserError("httpx or beautifulsoup4 not installed", retryable=False) from exc

    mkt  = "zh-CN" if cn_locale else "en-US"
    lang = "zh-CN" if cn_locale else "en-US"
    url  = (
        f"https://www.bing.com/search"
        f"?q={query.replace(' ', '+')}"
        f"&mkt={mkt}&setlang={lang}"
        f"&count={min(num_results * 2, 20)}"
    )
    headers = {
        "User-Agent":      _USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8" if cn_locale else "en-US,en;q=0.9",
        "Accept":          "text/html,application/xhtml+xml",
    }

    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=20.0) as c:
            resp = c.get(url)
        resp.raise_for_status()
    except Exception as exc:
        raise WebBrowserError(f"Bing request failed: {exc}", retryable=True) from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    results: List[Dict[str, str]] = []

    for item in soup.select("li.b_algo"):
        a = item.select_one("h2 a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href  = a.get("href", "")
        if not href.startswith("http"):
            continue
        # Snippet: Bing puts it in p.b_algoSlug, .b_caption p, or .b_paractl
        snip_el = item.select_one("p.b_algoSlug, .b_caption p, .b_paractl, p")
        snippet = snip_el.get_text(strip=True)[:300] if snip_el else ""
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= num_results:
            break

    return results


def search_web(
    query: str,
    engine: str = "auto",
    num_results: int = 5,
    client_ip: Optional[str] = None,
) -> str:
    """Search the web and return top N results as a JSON string.

    Parameters
    ----------
    query      : The search query.
    engine     : Engine name — "auto" (default), "bing", "duckduckgo", or "sogou".
    num_results: Number of results to return (capped at 10).
    client_ip  : Originating client IP used for geolocation when engine="auto".
                 If omitted or unroutable, auto-mode defaults to DuckDuckGo.

    Returns
    -------
    JSON string: {"results": [{"title": "...", "url": "...", "snippet": "..."}]}

    Raises
    ------
    WebBrowserError
        retryable=True  on navigation timeout or DNS failure.
        retryable=False on unsupported engine or zero results extracted.

    Auto-selection logic
    --------------------
    "auto" geolocates ``client_ip`` via ip-api.com (3 s timeout, cached 1 h):
      • CN  → Bing (zh-CN locale, httpx) → fallback DuckDuckGo
      • else → DuckDuckGo (httpx)         → fallback Bing (en-US locale, httpx)
    Bing and DuckDuckGo are both httpx-based — no Playwright required.
    "sogou" still uses Playwright (its result URLs are obfuscated server-side).
    """
    _valid = set(_SEARCH_ENGINES.keys())
    if engine not in _valid:
        raise WebBrowserError(
            f"Unsupported search engine '{engine}'. Choose from: {sorted(_valid)}",
            retryable=False,
        )
    num_results = min(max(1, num_results), 10)

    # ── auto mode: geo-detect + query-language aware engine selection ──────────
    if engine == "auto":
        country = _geolocate_ip(client_ip) if client_ip else ""
        is_cn   = country == "CN"
        # Detect CJK characters in query — Bing zh-CN works from datacenter IPs
        # only for Chinese/Japanese/Korean queries; English queries are CAPTCHA'd.
        is_cjk  = any(
            "　" <= c <= "鿿" or "가" <= c <= "힯" or "぀" <= c <= "ヿ"
            for c in query
        )

        if is_cn and is_cjk:
            # CN user + Chinese query → Bing zh-CN (best Chinese content, server-accessible)
            primary_fn  = lambda: _search_bing_httpx(query, num_results, cn_locale=True)
            fallback_fn = lambda: _search_duckduckgo(query, num_results)
            primary_name, fallback_name = "bing(zh-CN)", "duckduckgo"
        else:
            # Non-CN user OR English/mixed query → DuckDuckGo (reliable from any server IP)
            # Fallback: Bing zh-CN can still surface some results for mixed queries
            primary_fn  = lambda: _search_duckduckgo(query, num_results)
            fallback_fn = lambda: _search_bing_httpx(query, num_results, cn_locale=is_cn)
            primary_name, fallback_name = "duckduckgo", "bing(zh-CN)" if is_cn else "bing"

        logger.info(
            "[web_browser] auto-select: client_ip=%s country=%r cjk=%s → primary=%s",
            client_ip, country, is_cjk, primary_name,
        )

        try:
            results = primary_fn()
            if results:
                logger.debug("[web_browser] %s → %d results", primary_name, len(results))
                return json.dumps({"results": results})
            logger.warning("[web_browser] %s returned 0 results; trying %s", primary_name, fallback_name)
        except WebBrowserError as exc:
            logger.warning("[web_browser] %s failed (%s); trying %s", primary_name, exc, fallback_name)

        try:
            results = fallback_fn()
        except WebBrowserError as exc:
            raise WebBrowserError(
                f"Both {primary_name} and {fallback_name} failed for query '{query}'",
                retryable=True,
            ) from exc

        if not results:
            raise WebBrowserError(
                f"No results extracted (auto-mode) for query '{query}'",
                retryable=True,
            )
        logger.debug("[web_browser] %s (fallback) → %d results", fallback_name, len(results))
        return json.dumps({"results": results})

    # ── DuckDuckGo: httpx, no Playwright ─────────────────────────────────────
    if engine == "duckduckgo":
        results = _search_duckduckgo(query, num_results)
        if not results:
            raise WebBrowserError(
                f"No results extracted from duckduckgo for query '{query}'",
                retryable=False,
            )
        logger.debug("[web_browser] search_web(duckduckgo, %r) → %d", query, len(results))
        return json.dumps({"results": results})

    # ── Bing: httpx, no Playwright ────────────────────────────────────────────
    # Note: Bing blocks datacenter/cloud IPs for en-US requests with CAPTCHA.
    # zh-CN locale requests succeed from server IPs for CJK-language queries.
    # For explicit engine="bing", we use zh-CN locale to maximise server compatibility.
    if engine == "bing":
        results = _search_bing_httpx(query, num_results, cn_locale=True)
        if not results:
            raise WebBrowserError(
                f"No results extracted from bing for query '{query}'",
                retryable=False,
            )
        logger.debug("[web_browser] search_web(bing, %r) → %d", query, len(results))
        return json.dumps({"results": results})

    # ── Sogou: Playwright (legacy, kept for compatibility) ────────────────────
    # Note: Sogou obfuscates result URLs so httpx scraping can't decode hrefs.
    url = _SEARCH_ENGINES["sogou"].format(query=query.replace(" ", "+"))

    pw, browser, context = _launch_browser()
    try:
        page = context.new_page()
        try:
            page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
        except Exception as exc:
            raise WebBrowserError(
                f"Navigation to sogou failed: {exc}",
                retryable=True,
            ) from exc

        time.sleep(random.uniform(0.5, 1.5))

        results = _extract_search_results(page, "sogou", num_results)
        if not results:
            raise WebBrowserError(
                f"No results extracted from sogou for query '{query}'. "
                "The page structure may have changed or the query was blocked.",
                retryable=False,
            )

        logger.debug("[web_browser] search_web(sogou, %r) → %d results", query, len(results))
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
        "Search the web for current information. "
        "Use when the task needs facts, documentation, library versions, or any "
        "knowledge that may have changed after your training cutoff. "
        "Returns JSON: {\"results\": [{\"title\": \"...\", \"url\": \"...\", \"snippet\": \"...\"}]}. "
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
                "enum": ["auto", "bing", "duckduckgo", "sogou"],
                "description": (
                    "Search engine. 'auto' (default) geo-detects the client and picks "
                    "Bing (zh-CN) for China or DuckDuckGo elsewhere. "
                    "'bing' forces English Bing. 'duckduckgo' forces DDG. "
                    "'sogou' uses headless Playwright (slow, legacy)."
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
