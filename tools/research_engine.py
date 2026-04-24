#!/usr/bin/env python3
"""
research_engine.py — Multi-source research search for CEO hunter.

Queries multiple source types in parallel:
  1. Web search (AgentSearch / SearXNG — Bing + whatever's alive)
  2. Google Scholar (via SearXNG with engine filter)
  3. OpenAlex API (free, unlimited, peer-reviewed)
  4. AgentSearch content extraction (for top hits)

Returns deduplicated, quality-scored results ready for the hunter's
bite/kill phases.
"""

import json
import re
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote_plus

AGENT_SEARCH = "http://localhost:3939"
SEARXNG_URL = "http://localhost:8080"  # Direct SearXNG (inside Docker network won't work, go through AgentSearch)
OPENALEX_URL = "https://api.openalex.org"

# Rich domain authority map (category → score)
DOMAIN_AUTHORITY = {
    # Academic publishers (high signal)
    "sciencedirect.com": 0.90, "springer.com": 0.90, "link.springer.com": 0.90,
    "tandfonline.com": 0.88, "emerald.com": 0.88, "wiley.com": 0.88,
    "ieee.org": 0.90, "acm.org": 0.88, "mdpi.com": 0.82, "nature.com": 0.92,
    "science.org": 0.92, "pnas.org": 0.90, "arxiv.org": 0.85,
    "researchgate.net": 0.75, "ssrn.com": 0.80, "jstor.org": 0.85,
    # Government / standards
    "nist.gov": 0.90, "epa.gov": 0.85, "bls.gov": 0.85, "census.gov": 0.85,
    "sec.gov": 0.88, "congress.gov": 0.85, "iso.org": 0.88,
    "who.int": 0.85, "worldbank.org": 0.85, "oecd.org": 0.85,
    # Consulting / industry (moderate-high)
    "mckinsey.com": 0.82, "bcg.com": 0.82, "deloitte.com": 0.80,
    "accenture.com": 0.78, "pwc.com": 0.78, "bain.com": 0.78,
    "gartner.com": 0.82, "forrester.com": 0.80, "idc.com": 0.78,
    "hbr.org": 0.85, "sloanreview.mit.edu": 0.85,
    # Industry associations
    "asq.org": 0.82, "sme.org": 0.80, "isa.org": 0.80,
    "mesa.org": 0.80, "incit.org": 0.82, "weforum.org": 0.80,
    # Tech (moderate)
    "github.com": 0.70, "stackoverflow.com": 0.65,
    "medium.com": 0.40, "substack.com": 0.45,
    "reddit.com": 0.35, "quora.com": 0.25,
    # News
    "reuters.com": 0.78, "bloomberg.com": 0.78, "ft.com": 0.78,
    "wsj.com": 0.78, "nytimes.com": 0.75,
}

# Junk domains to always filter
JUNK_DOMAINS = {
    "merriam-webster.com", "dictionary.com", "cambridge.org/dictionary",
    "thefreedictionary.com", "wiktionary.org", "thesaurus.com",
    "zhihu.com", "baidu.com", "sogou.com", "163.com", "qq.com",
    "pinterest.com", "instagram.com", "tiktok.com", "facebook.com",
    "linkedin.com/pulse",  # LinkedIn articles are mostly SEO filler
    "youtube.com",  # YouTube handled separately
    "coursera.org", "udemy.com", "skillshare.com",  # Course ads
    "amazon.com", "ebay.com", "walmart.com",  # Shopping
    "kochind.com",  # Known garbage result
    "ell.stackexchange.com", "english.stackexchange.com",  # Grammar Q&A
    "stackexchange.com/questions",  # Generic SE questions
    "forums.digitalspy.com",  # TV forums
    "apple.com/siri",  # Siri product page
}


def _is_junk(url: str) -> bool:
    """Check if URL is from a junk domain."""
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
        return any(junk in domain for junk in JUNK_DOMAINS)
    except Exception:
        return False


def _domain_score(url: str) -> float:
    """Get domain authority score."""
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
        # Check exact match first, then partial
        if domain in DOMAIN_AUTHORITY:
            return DOMAIN_AUTHORITY[domain]
        for known, score in DOMAIN_AUTHORITY.items():
            if known in domain:
                return score
        return 0.30  # Unknown domain default
    except Exception:
        return 0.30


def search_web(query: str, limit: int = 10) -> list[dict]:
    """Search via AgentSearch (routes to SearXNG general engines)."""
    try:
        r = requests.get(
            f"{AGENT_SEARCH}/search",
            params={"q": query, "count": limit},
            timeout=15,
        )
        if r.ok:
            data = r.json()
            results = data.get("results", []) if isinstance(data, dict) else data
            return [
                {
                    "title": x.get("title", ""),
                    "url": x.get("url", ""),
                    "snippet": x.get("snippet", x.get("content", "")),
                    "source_type": "web",
                    "engine": "agentsearch",
                }
                for x in results
                if x.get("url") and not _is_junk(x.get("url", ""))
            ]
    except Exception:
        pass
    return []


def search_scholar(query: str, limit: int = 10) -> list[dict]:
    """Search Google Scholar via AgentSearch/SearXNG with engine filter."""
    try:
        # Route through AgentSearch which forwards to SearXNG
        r = requests.get(
            f"{AGENT_SEARCH}/search",
            params={"q": query, "count": limit, "engines": "google scholar"},
            timeout=15,
        )
        if r.ok:
            data = r.json()
            results = data.get("results", []) if isinstance(data, dict) else data
            return [
                {
                    "title": x.get("title", ""),
                    "url": x.get("url", ""),
                    "snippet": x.get("snippet", x.get("content", "")),
                    "source_type": "scholar",
                    "engine": "google_scholar",
                }
                for x in results
                if x.get("url") and not _is_junk(x.get("url", ""))
            ]
    except Exception:
        pass
    return []


def search_openalex(query: str, limit: int = 10) -> list[dict]:
    """Search OpenAlex API (free, unlimited, peer-reviewed papers)."""
    try:
        r = requests.get(
            f"{OPENALEX_URL}/works",
            params={
                "search": query,
                "per_page": limit,
                "select": "title,publication_year,cited_by_count,doi,open_access,primary_location,abstract_inverted_index",
            },
            headers={"User-Agent": "CEO-Research/1.0 (mailto:research@example.com)"},
            timeout=15,
        )
        if r.ok:
            data = r.json()
            results = []
            for w in data.get("results", []):
                title = w.get("title", "")
                if not title:
                    continue
                # Get best URL
                oa = w.get("open_access", {}) or {}
                loc = w.get("primary_location", {}) or {}
                url = (
                    oa.get("oa_url")
                    or (loc.get("landing_page_url"))
                    or w.get("doi", "")
                )
                if not url:
                    continue
                # Reconstruct abstract from inverted index
                abstract = ""
                aii = w.get("abstract_inverted_index")
                if aii and isinstance(aii, dict):
                    try:
                        word_positions = []
                        for word, positions in aii.items():
                            for pos in positions:
                                word_positions.append((pos, word))
                        word_positions.sort()
                        abstract = " ".join(w for _, w in word_positions)[:300]
                    except Exception:
                        pass

                cited = w.get("cited_by_count", 0)
                year = w.get("publication_year", "")
                results.append({
                    "title": f"[{year}] {title}" if year else title,
                    "url": url,
                    "snippet": abstract or f"Peer-reviewed paper ({year}). Cited by {cited}.",
                    "source_type": "academic",
                    "engine": "openalex",
                    "cited_by": cited,
                    "year": year,
                })
            return results
    except Exception:
        pass
    return []


def search_extract(query: str, limit: int = 5) -> list[dict]:
    """Search with content extraction via AgentSearch kill chain."""
    try:
        r = requests.get(
            f"{AGENT_SEARCH}/search/extract",
            params={"q": query, "count": limit},
            timeout=20,
        )
        if r.ok:
            data = r.json()
            results = data.get("results", []) if isinstance(data, dict) else data
            return [
                {
                    "title": x.get("title", ""),
                    "url": x.get("url", ""),
                    "snippet": x.get("snippet", ""),
                    "content": x.get("content", ""),
                    "source_type": "web_extracted",
                    "engine": "agentsearch_extract",
                }
                for x in results
                if x.get("url") and not _is_junk(x.get("url", ""))
            ]
    except Exception:
        pass
    return []


def research(
    query: str,
    max_results: int = 15,
    include_content: bool = True,
) -> list[dict]:
    """
    Multi-source research search. Queries web, scholar, and academic APIs
    in parallel, deduplicates, scores, and returns ranked results.
    
    Args:
        query: Research question or search query
        max_results: Maximum results to return
        include_content: Whether to run content extraction on top web hits
        
    Returns:
        List of scored, deduplicated results sorted by quality
    """
    start = time.time()
    all_results = []

    # Shorten query for search engines (they choke on long queries)
    short_query = query[:120] if len(query) > 120 else query
    # Clean keywords for APIs: strip stopwords and short words, keep core terms
    _stopwords = {"has", "have", "anyone", "does", "what", "which", "where", "when",
                  "how", "that", "this", "with", "from", "into", "been", "being",
                  "they", "them", "their", "there", "here", "about", "specifically",
                  "before", "after", "then", "than", "also", "just", "very", "most",
                  "some", "such", "only", "other", "more", "less", "over", "under",
                  "between", "through", "during", "would", "could", "should", "will"}
    keywords = re.sub(r'[^\w\s]', ' ', query.lower())
    keywords = ' '.join(w for w in keywords.split() if len(w) > 3 and w not in _stopwords)[:100]

    print(f"   🔬 Research engine: querying 4 sources in parallel...")

    # Fire all searches in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(search_web, short_query, 10): "web",
            executor.submit(search_scholar, short_query, 10): "scholar",
            executor.submit(search_openalex, keywords, 10): "openalex",
        }
        if include_content:
            futures[executor.submit(search_extract, short_query, 5)] = "extract"

        source_counts = {}
        for future in as_completed(futures, timeout=25):
            source = futures[future]
            try:
                results = future.result()
                source_counts[source] = len(results)
                all_results.extend(results)
            except Exception as e:
                source_counts[source] = f"error: {e}"

    # Report source health
    for source, count in source_counts.items():
        status = f"{count} results" if isinstance(count, int) else count
        print(f"      {'✅' if isinstance(count, int) and count > 0 else '⚠️'} {source}: {status}")

    if not all_results:
        print("   ❌ No results from any source")
        return []

    # Deduplicate by normalized URL
    seen = {}
    for r in all_results:
        url = r.get("url", "")
        if not url:
            continue
        # Normalize
        norm = urlparse(url).netloc.lower().replace("www.", "") + urlparse(url).path.rstrip("/")
        if norm in seen:
            existing = seen[norm]
            # Merge: keep longer snippet, accumulate engines
            if len(r.get("snippet") or "") > len(existing.get("snippet") or ""):
                existing["snippet"] = r["snippet"]
            if r.get("content") and not existing.get("content"):
                existing["content"] = r["content"]
            existing.setdefault("engines", set()).add(r.get("engine", "?"))
            # Keep highest citation count
            if r.get("cited_by", 0) > existing.get("cited_by", 0):
                existing["cited_by"] = r["cited_by"]
        else:
            r.setdefault("engines", set()).add(r.get("engine", "?"))
            seen[norm] = r

    # Score results
    scored = []
    for r in seen.values():
        url = r.get("url", "")

        # Domain authority (0-1)
        authority = _domain_score(url)

        # Multi-source bonus (found by multiple sources = more relevant)
        engines = r.get("engines", set())
        source_bonus = min(len(engines) * 0.1, 0.3)

        # Citation signal (academic papers)
        cited = r.get("cited_by", 0)
        citation_score = min(cited / 100, 1.0) * 0.15 if cited else 0

        # Freshness (prefer recent)
        year = r.get("year", 0)
        if year and year >= 2024:
            freshness = 0.10
        elif year and year >= 2022:
            freshness = 0.05
        else:
            freshness = 0

        # Content depth (has extracted content or long snippet)
        content_len = len(r.get("content") or "") + len(r.get("snippet") or "")
        depth = min(content_len / 2000, 1.0) * 0.10

        # Source type bonus (academic > web for research)
        type_bonus = {"academic": 0.10, "scholar": 0.08, "web_extracted": 0.05, "web": 0}.get(
            r.get("source_type", "web"), 0
        )

        total = authority * 0.35 + source_bonus + citation_score + freshness + depth + type_bonus
        r["quality_score"] = round(total, 3)
        r["engines"] = list(r.get("engines", []))
        scored.append(r)

    # Sort by quality score
    scored.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    results = scored[:max_results]

    elapsed = time.time() - start
    print(f"   📊 {len(results)} results from {len(source_counts)} sources ({elapsed:.1f}s)")
    print(f"      Top domains: {', '.join(set(urlparse(r['url']).netloc.replace('www.','') for r in results[:5]))}")

    return results


# ── CLI for testing ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "manufacturing AI readiness assessment maturity"
    print(f"\nResearch query: {q}\n")
    results = research(q)
    print(f"\n{'='*70}")
    for i, r in enumerate(results):
        print(f"\n{i+1}. [{r.get('quality_score',0):.3f}] {r['title'][:80]}")
        print(f"   {r['url'][:100]}")
        print(f"   Source: {r.get('source_type','?')} | Engines: {r.get('engines',[])} | Cited: {r.get('cited_by','-')}")
        s = r.get("snippet", "")[:150]
        if s:
            print(f"   {s}")
