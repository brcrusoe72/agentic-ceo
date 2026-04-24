#!/usr/bin/env python3
"""
fetch.py — Content Extraction Client

Thin client that delegates to AgentSearch's /read endpoint (localhost:3939).
AgentSearch handles the full kill chain: 9 strategies, SSRF protection,
prompt injection scrubbing (70+ patterns), encoding normalization,
content caching, and self-improvement tracking.

If AgentSearch is down, falls back to a minimal local direct fetch.

Usage:
    from fetch import kill_chain
    content = kill_chain(url)  # Returns str or None

    # Or use individual strategies:
    from fetch import direct_fetch
"""

import os
import re
import gc
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

AGENTSEARCH_URL = os.getenv("AGENTSEARCH_URL", "http://localhost:3939")
AGENTSEARCH_TIMEOUT = 60  # Kill chain can take a while

# Content limits
MIN_USEFUL_CHARS = 300
MAX_CONTENT_CHARS = 15000

# User agents for fallback mode
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]

# Selectors for fallback extraction
CONTENT_SELECTORS = [
    "main", "article", "[role=main]", ".content", "#content",
    ".post-content", ".entry-content", ".article-body", ".post-body",
]

GARBAGE_TAGS = ["script", "style", "nav", "footer", "header", "aside",
                "iframe", "noscript", "svg", "form"]

PAYWALL_SIGNALS = ["subscribe to read", "premium content", "paywall",
                   "sign up to continue", "members only", "login to view",
                   "create a free account", "already a subscriber"]

# Domains to never fetch from
BLOCKED_FETCH_DOMAINS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl",
}

SUSPICIOUS_TLDS = {".tk", ".ml", ".ga", ".cf", ".gq", ".buzz", ".top", ".xyz", ".work", ".click"}

P = lambda *a, **kw: print(*a, **kw, flush=True)


# ---------------------------------------------------------------------------
# Security: SSRF Protection (kept locally for _is_safe_url calls)
# ---------------------------------------------------------------------------

def _is_safe_url(url: str, verbose: bool = False) -> bool:
    """Validate URL safety. Blocks private IPs, localhost, suspicious domains."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    hostname_lower = hostname.lower()

    if hostname_lower in ("localhost", "localhost.localdomain", "127.0.0.1", "::1", "0.0.0.0"):
        return False

    for blocked in BLOCKED_FETCH_DOMAINS:
        if hostname_lower == blocked or hostname_lower.endswith("." + blocked):
            return False

    for tld in SUSPICIOUS_TLDS:
        if hostname_lower.endswith(tld):
            return False

    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_link_local:
            return False
    except ValueError:
        try:
            resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for family, _, _, _, sockaddr in resolved:
                ip_str = sockaddr[0]
                try:
                    addr = ipaddress.ip_address(ip_str)
                    if addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_link_local:
                        return False
                except ValueError:
                    continue
        except (socket.gaierror, OSError):
            pass

    return True


def _sanitize_content(text: str) -> str:
    """Basic content sanitization for fallback mode.
    
    Full scrubbing (70+ patterns, encoding, semantic analysis) happens
    in AgentSearch. This is just a safety net for fallback direct fetches.
    """
    if not text:
        return text

    patterns = [
        re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+(instructions?|prompts?)", re.IGNORECASE),
        re.compile(r"(system\s*prompt|system\s*message)\s*[:=]", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+(a|an|in)\s+", re.IGNORECASE),
        re.compile(r"(disregard|forget|override)\s+(all\s+)?(previous|prior|your)\s+", re.IGNORECASE),
        re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
    ]

    for pattern in patterns:
        text = pattern.sub("[REDACTED]", text)

    return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_html(html: str) -> str | None:
    """Extract readable text from HTML (fallback mode)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(GARBAGE_TAGS):
        tag.decompose()
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) >= MIN_USEFUL_CHARS:
                return text[:MAX_CONTENT_CHARS]
    text = soup.get_text(separator="\n", strip=True)
    return text[:MAX_CONTENT_CHARS] if len(text) >= MIN_USEFUL_CHARS else None


def _is_paywalled(text: str) -> bool:
    if len(text) > 2000:
        return False
    lower = text.lower()
    return any(sig in lower for sig in PAYWALL_SIGNALS)


def _is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def _is_pdf_url(url: str) -> bool:
    return url.lower().rstrip("/").endswith(".pdf")


# ---------------------------------------------------------------------------
# AgentSearch Client
# ---------------------------------------------------------------------------

def _agentsearch_read(url: str, verbose: bool = True) -> str | None:
    """Fetch content via AgentSearch /read endpoint (kill chain)."""
    try:
        r = requests.get(
            f"{AGENTSEARCH_URL}/read",
            params={"url": url},
            timeout=AGENTSEARCH_TIMEOUT,
        )
        if not r.ok:
            if verbose:
                P(f"      ⚠️ AgentSearch returned {r.status_code}")
            return None

        data = r.json()
        if data.get("success") and data.get("content"):
            strategy = data.get("strategy", "unknown")
            chars = data.get("chars", 0)
            cached = data.get("cached", False)
            if verbose:
                cache_tag = " (cached)" if cached else ""
                P(f"      ✅ [{strategy}]{cache_tag} {chars:,} chars from {urlparse(url).netloc}")
            return data["content"]
        else:
            error = data.get("error", "unknown")
            if verbose:
                P(f"      ⚠️ AgentSearch: {error}")
                tried = data.get("strategies_tried", [])
                if tried:
                    P(f"         Tried: {', '.join(tried)}")
            return None

    except requests.ConnectionError:
        if verbose:
            P(f"      ⚠️ AgentSearch unavailable — falling back to local fetch")
        return None
    except requests.Timeout:
        if verbose:
            P(f"      ⚠️ AgentSearch timed out ({AGENTSEARCH_TIMEOUT}s)")
        return None
    except Exception as e:
        if verbose:
            P(f"      ⚠️ AgentSearch error: {e}")
        return None


# ---------------------------------------------------------------------------
# Fallback: Direct Fetch (used only when AgentSearch is down)
# ---------------------------------------------------------------------------

def direct_fetch(url: str, ua_index: int = 0) -> str | None:
    """Direct GET + BS4. Fallback when AgentSearch is unavailable."""
    try:
        r = requests.get(url, timeout=15, headers={
            "User-Agent": USER_AGENTS[ua_index % len(USER_AGENTS)],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        if r.status_code in (403, 429):
            return None
        r.raise_for_status()
        text = _clean_html(r.text)
        if text and not _is_paywalled(text):
            return _sanitize_content(text)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The Kill Chain (main entry point)
# ---------------------------------------------------------------------------

def kill_chain(url: str, verbose: bool = True) -> str | None:
    """
    Extract content from URL. Delegates to AgentSearch's /read endpoint
    which runs the full 9-strategy kill chain with scrubbing.

    Falls back to local direct fetch if AgentSearch is unreachable.
    """
    if not _is_safe_url(url, verbose=verbose):
        if verbose:
            P(f"      🛡️ BLOCKED: URL failed safety check")
        return None

    # Primary: AgentSearch kill chain (9 strategies + scrubber)
    content = _agentsearch_read(url, verbose=verbose)
    if content:
        return content

    # Fallback: local direct fetch (minimal — no archive cascade)
    if verbose:
        P(f"      🔄 Fallback: local direct fetch")

    content = direct_fetch(url)
    if content:
        if verbose:
            P(f"      ✅ [fallback-direct] {len(content):,} chars from {urlparse(url).netloc}")
        return content

    if verbose:
        P(f"      💀 All strategies exhausted for {urlparse(url).netloc}")
    return None


# ---------------------------------------------------------------------------
# Convenience function for hunter.py
# ---------------------------------------------------------------------------

def fetch_content(url: str, max_chars: int = None) -> str | None:
    """Convenience wrapper for hunter.py compatibility."""
    content = kill_chain(url, verbose=False)
    if content and max_chars:
        content = content[:max_chars]
    return content


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 fetch.py <url>")
        sys.exit(1)

    url = sys.argv[1]
    print(f"🎯 Kill chain targeting: {url}\n")
    content = kill_chain(url, verbose=True)
    if content:
        print(f"\n{'='*60}")
        print(f"Captured {len(content):,} chars")
        print(f"{'='*60}")
        print(content[:500])
        print("..." if len(content) > 500 else "")
    else:
        print("\n❌ Target escaped. All strategies failed.")
