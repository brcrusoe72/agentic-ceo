#!/usr/bin/env python3
"""
content_adapter.py — Smart content extraction for CEO hunter.

Replaces the linear kill chain with source-type-aware strategies:
  1. Detect URL type (PDF, DOI/academic, video, web page)
  2. Pick optimal strategy based on URL type + domain history
  3. Extract content with fallbacks
  4. Always return SOMETHING (abstract beats nothing)

Strategies:
  - pdf_extract: download PDF → pdfplumber → text
  - unpaywall: resolve DOI → find open access version → fetch
  - openalex_abstract: get abstract from OpenAlex API
  - agentsearch: AgentSearch /read endpoint (existing kill chain)
  - direct_fetch: simple HTTP GET + readability
  - skip: URL not worth attempting
"""

import io
import json
import os
import re
import tempfile
import time
import requests
from pathlib import Path
from urllib.parse import urlparse

# ── Config ──────────────────────────────────────────────────
AGENT_SEARCH = "http://localhost:3939"
UNPAYWALL_EMAIL = "generalideaai@gmail.com"
OPENALEX_URL = "https://api.openalex.org"

# Domains where AgentSearch's search-about returns garbage
ACADEMIC_DOMAINS = {
    "emerald.com", "tandfonline.com", "springer.com", "link.springer.com",
    "sciencedirect.com", "wiley.com", "onlinelibrary.wiley.com",
    "ieee.org", "ieeexplore.ieee.org", "acm.org", "dl.acm.org",
    "nature.com", "science.org", "pnas.org", "oup.com", "academic.oup.com",
    "sagepub.com", "journals.sagepub.com", "mdpi.com", "www.mdpi.com",
    "frontiersin.org", "plos.org", "biomedcentral.com", "hindawi.com",
    "worldscientific.com", "degruyter.com", "karger.com",
    "search.proquest.com", "jstor.org",
}

# Domains that never work — don't waste time
SKIP_DOMAINS = {
    "media.defense.gov", "ipdefenseforum.com",
}

DOI_RE = re.compile(r'(10\.\d{4,9}/[^\s&?#\]>]+)')

P = lambda *a, **kw: print(*a, **kw, flush=True)


# ── DOI Extraction ──────────────────────────────────────────

def extract_doi(url: str) -> str | None:
    """Extract DOI from a URL if present."""
    m = DOI_RE.search(url)
    if m:
        doi = m.group(1).rstrip('/.)')
        # Clean trailing path segments that aren't part of the DOI
        # e.g., "10.1108/TQM-04-2025-0247/1300168" → "10.1108/TQM-04-2025-0247"
        # But "10.1007/979-8-8688-1315-3" is valid (book DOI)
        # Heuristic: if last segment is purely numeric and >6 digits, it's probably a publisher ID
        parts = doi.split('/')
        if len(parts) > 2:
            last = parts[-1]
            if last.isdigit() and len(last) >= 6:
                doi = '/'.join(parts[:-1])
        # Remove .pdf suffix
        if doi.endswith('.pdf'):
            doi = doi[:-4]
        return doi
    return None


def is_pdf_url(url: str) -> bool:
    """Check if URL likely points to a PDF."""
    path = urlparse(url).path.lower()
    return (path.endswith('.pdf') or '/pdf/' in path or '/pdf?' in path 
            or path.endswith('/pdf'))


def is_academic_domain(url: str) -> bool:
    """Check if URL is from a known academic publisher."""
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(acad in domain for acad in ACADEMIC_DOMAINS)


def should_skip(url: str) -> bool:
    """Check if URL is from a domain we should never attempt."""
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(skip in domain for skip in SKIP_DOMAINS)


# ── Strategy: PDF Extract ───────────────────────────────────

def strategy_pdf_extract(url: str, max_chars: int = 15000) -> dict:
    """Download PDF and extract text via pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        return {"success": False, "error": "pdfplumber not installed"}

    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (compatible; CEO-Research/1.0)"
        })
        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        content_type = resp.headers.get("content-type", "")
        if "pdf" not in content_type and not is_pdf_url(url):
            return {"success": False, "error": f"Not a PDF: {content_type}"}

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(resp.content)
            tmp.flush()
            
            with pdfplumber.open(tmp.name) as pdf:
                pages_text = []
                total_chars = 0
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                        total_chars += len(text)
                        if total_chars >= max_chars:
                            break

                full_text = "\n\n".join(pages_text)[:max_chars]
                if len(full_text) < 100:
                    return {"success": False, "error": f"PDF text too short ({len(full_text)} chars)"}

                return {
                    "success": True,
                    "content": full_text,
                    "chars": len(full_text),
                    "strategy": "pdf_extract",
                    "pages": len(pages_text),
                }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ── Strategy: Unpaywall ─────────────────────────────────────

def strategy_unpaywall(doi: str) -> dict:
    """Look up DOI on Unpaywall to find open access version."""
    try:
        resp = requests.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": UNPAYWALL_EMAIL},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"Unpaywall HTTP {resp.status_code}"}

        data = resp.json()
        title = data.get("title", "")
        is_oa = data.get("is_oa", False)

        if is_oa:
            best = data.get("best_oa_location") or {}
            pdf_url = best.get("url_for_pdf") or best.get("url")
            if pdf_url:
                # Try to fetch the PDF
                pdf_result = strategy_pdf_extract(pdf_url)
                if pdf_result["success"]:
                    pdf_result["strategy"] = "unpaywall_pdf"
                    pdf_result["doi"] = doi
                    return pdf_result
                
                # If PDF extraction failed, try as web page via AgentSearch
                web_result = strategy_agentsearch(pdf_url)
                if web_result["success"]:
                    web_result["strategy"] = "unpaywall_web"
                    web_result["doi"] = doi
                    return web_result

        # Paper exists but isn't OA — return metadata as partial content
        if title:
            # Try all OA locations
            for loc in data.get("oa_locations", []):
                loc_url = loc.get("url_for_pdf") or loc.get("url")
                if loc_url:
                    pdf_result = strategy_pdf_extract(loc_url)
                    if pdf_result["success"]:
                        pdf_result["strategy"] = "unpaywall_alt_pdf"
                        return pdf_result

            return {
                "success": False,
                "error": "not_oa",
                "title": title,
                "doi": doi,
                "is_oa": is_oa,
            }

        return {"success": False, "error": "DOI not found in Unpaywall"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ── Strategy: OpenAlex Abstract ─────────────────────────────

def strategy_openalex_abstract(doi: str = None, title: str = None) -> dict:
    """Get paper abstract from OpenAlex. Always returns something if the paper exists."""
    try:
        if doi:
            url = f"{OPENALEX_URL}/works/doi:{doi}"
        elif title:
            url = f"{OPENALEX_URL}/works"
        else:
            return {"success": False, "error": "Need DOI or title"}

        params = {}
        if title and not doi:
            params["search"] = title
            params["per_page"] = 1

        resp = requests.get(
            url,
            params=params if params else None,
            headers={"User-Agent": "CEO-Research/1.0 (mailto:generalideaai@gmail.com)"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"OpenAlex HTTP {resp.status_code}"}

        data = resp.json()

        # Handle search results vs direct lookup
        if "results" in data:
            works = data.get("results", [])
            if not works:
                return {"success": False, "error": "Not found in OpenAlex"}
            work = works[0]
        else:
            work = data

        paper_title = work.get("title", "")
        year = work.get("publication_year", "")
        cited = work.get("cited_by_count", 0)

        # Reconstruct abstract from inverted index
        abstract = ""
        aii = work.get("abstract_inverted_index")
        if aii and isinstance(aii, dict):
            word_positions = []
            for word, positions in aii.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort()
            abstract = " ".join(w for _, w in word_positions)

        if not abstract and not paper_title:
            return {"success": False, "error": "No content in OpenAlex"}

        # Build content from metadata + abstract
        content_parts = []
        if paper_title:
            content_parts.append(f"Title: {paper_title}")
        if year:
            content_parts.append(f"Year: {year}")
        if cited:
            content_parts.append(f"Citations: {cited}")
        if abstract:
            content_parts.append(f"\nAbstract:\n{abstract}")

        # Add concept tags
        concepts = work.get("concepts", [])
        if concepts:
            top_concepts = [c.get("display_name", "") for c in concepts[:5] if c.get("display_name")]
            if top_concepts:
                content_parts.append(f"\nKey concepts: {', '.join(top_concepts)}")

        content = "\n".join(content_parts)
        return {
            "success": True,
            "content": content,
            "chars": len(content),
            "strategy": "openalex_abstract",
            "is_abstract_only": True,
            "title": paper_title,
            "year": year,
            "cited_by": cited,
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ── Strategy: AgentSearch ───────────────────────────────────

def strategy_agentsearch(url: str) -> dict:
    """Use AgentSearch's /read endpoint (existing kill chain)."""
    try:
        resp = requests.get(
            f"{AGENT_SEARCH}/read",
            params={"url": url},
            timeout=30,
        )
        if resp.ok:
            data = resp.json()
            content = data.get("content", "")
            strategy = data.get("strategy", "agentsearch")

            # Detect garbage: Wikipedia WWW article returned as "coverage"
            if content and "From Wikipedia, the free encyclopedia" in content[:200]:
                if "wikipedia.org" not in url:
                    return {"success": False, "error": "Got Wikipedia instead of actual content"}

            # Detect raw PDF binary returned as "content"
            if content and (content.startswith("%PDF") or content[:20].count('\x00') > 3):
                return {"success": False, "error": "Got raw PDF binary, need pdf_extract"}

            if content and len(content) > 200:
                return {
                    "success": True,
                    "content": content,
                    "chars": len(content),
                    "strategy": f"agentsearch_{strategy}",
                }
        return {"success": False, "error": "AgentSearch returned no content"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ── Main Extraction Logic ───────────────────────────────────

def extract_content(url: str, title: str = None, max_chars: int = 15000) -> dict:
    """
    Smart content extraction. Picks strategy based on URL type.
    
    Returns dict with:
      - success: bool
      - content: str (the extracted text)
      - chars: int
      - strategy: str (which strategy worked)
      - is_abstract_only: bool (if only abstract was available)
    
    Always tries to return SOMETHING. Abstract > nothing.
    """
    if should_skip(url):
        return {"success": False, "error": "Domain in skip list", "strategy": "skip"}

    domain = urlparse(url).netloc.lower().replace("www.", "")
    doi = extract_doi(url)
    is_pdf = is_pdf_url(url)
    is_academic = is_academic_domain(url)
    attempts = []

    # ── Strategy selection based on URL type ──

    if is_pdf:
        # PDF URL → try PDF extraction first
        P(f"      📄 PDF detected → pdf_extract")
        result = strategy_pdf_extract(url, max_chars)
        attempts.append(("pdf_extract", result["success"]))
        if result["success"]:
            return result

        # PDF failed → try Unpaywall if we have a DOI
        if doi:
            P(f"      🔓 PDF failed, trying Unpaywall ({doi[:30]})")
            result = strategy_unpaywall(doi)
            attempts.append(("unpaywall", result["success"]))
            if result["success"]:
                return result

    elif is_academic and doi:
        # Academic publisher with DOI → Unpaywall first, then PDF, then abstract
        P(f"      🎓 Academic + DOI → unpaywall → pdf → abstract")
        
        result = strategy_unpaywall(doi)
        attempts.append(("unpaywall", result["success"]))
        if result["success"]:
            return result

        # Try AgentSearch (but it might return Wikipedia)
        result = strategy_agentsearch(url)
        attempts.append(("agentsearch", result["success"]))
        if result["success"]:
            return result

        # Fall back to abstract
        P(f"      📝 Full text unavailable, using abstract")
        result = strategy_openalex_abstract(doi=doi, title=title)
        attempts.append(("openalex_abstract", result["success"]))
        if result["success"]:
            return result

    elif is_academic:
        # Academic publisher, no DOI → try PDF if URL looks like one, then AgentSearch, then abstract
        P(f"      🎓 Academic, no DOI → {'pdf → ' if is_pdf else ''}agentsearch → abstract")
        
        if is_pdf:
            result = strategy_pdf_extract(url, max_chars)
            attempts.append(("pdf_extract", result["success"]))
            if result["success"]:
                return result

        result = strategy_agentsearch(url)
        attempts.append(("agentsearch", result["success"]))
        if result["success"]:
            return result

        if title:
            result = strategy_openalex_abstract(title=title)
            attempts.append(("openalex_abstract", result["success"]))
            if result["success"]:
                return result

    else:
        # Regular web page → AgentSearch kill chain (works well for non-academic)
        result = strategy_agentsearch(url)
        attempts.append(("agentsearch", result["success"]))
        if result["success"]:
            return result

        # If AgentSearch failed and we have a DOI, try academic path
        if doi:
            P(f"      🔓 Web fetch failed, found DOI → trying academic path")
            result = strategy_unpaywall(doi)
            attempts.append(("unpaywall", result["success"]))
            if result["success"]:
                return result

            result = strategy_openalex_abstract(doi=doi, title=title)
            attempts.append(("openalex_abstract", result["success"]))
            if result["success"]:
                return result

    # ── Everything failed ──
    # Last resort: try to get ANYTHING from OpenAlex by title
    if title and not any(a[0] == "openalex_abstract" for a in attempts):
        P(f"      📝 Last resort: OpenAlex title search")
        result = strategy_openalex_abstract(title=title)
        attempts.append(("openalex_abstract", result["success"]))
        if result["success"]:
            return result

    return {
        "success": False,
        "error": f"All strategies failed: {attempts}",
        "strategy": "none",
        "attempts": attempts,
    }


# ── CLI for testing ─────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 content_adapter.py <url> [title]")
        sys.exit(1)

    url = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"\nExtracting: {url}")
    if title:
        print(f"Title hint: {title}")
    print()

    result = extract_content(url, title=title)
    
    print(f"\n{'='*60}")
    print(f"Success: {result['success']}")
    print(f"Strategy: {result.get('strategy', '?')}")
    print(f"Chars: {result.get('chars', 0)}")
    if result.get("is_abstract_only"):
        print(f"⚠️  Abstract only (full text unavailable)")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
    if result.get("content"):
        print(result["content"][:1000])
