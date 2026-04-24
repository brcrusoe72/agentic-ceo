#!/usr/bin/env python3
"""
dissolve.py — The Complexity Dissolver

Target: Complexity Theater (19 hits across 13 domains)

Most "complexity" in regulated industries is theater — consultants, vendors,
and incumbents adding layers of jargon and unnecessary process to simple
requirements. This agent finds the actual requirements behind the theater
and generates Plain Language Action Guides.

The loop:
  1. Scan knowledge base for frameworks tagged with regulatory/compliance complexity
  2. Research the ACTUAL requirements (what does the law say vs what consultants say?)
  3. Generate "Plain Language Action Guides" — strips jargon, removes theater
  4. Deposit simplified guides in knowledge/dissolved/
  5. Track complexity scores (perceived vs actual gap)

Usage:
    python3 dissolve.py                          # Full cycle: scan → dissolve → save
    python3 dissolve.py --target "FSMA 204"      # Dissolve a specific regulation/standard
    python3 dissolve.py --scan                   # Scan and rank complexity targets
    python3 dissolve.py --status                 # Show what's been dissolved
    python3 dissolve.py --cost-estimate          # Estimate cost without running
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
DISSOLVED_DIR = KNOWLEDGE_DIR / "dissolved"
REPORTS_DIR = STATE_DIR / "agent-reports"
DISSOLVED_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "claude-sonnet-4-5-20250929"


from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str, model: str = MODEL, max_tokens: int = 4096) -> str:
    return _call_claude_base(system, user, model=model, max_tokens=max_tokens)


def search(query: str, limit: int = 5) -> list[dict]:
    """Search via AgentSearch API."""
    import requests
    try:
        r = requests.get("http://localhost:3939/search", params={"q": query[:80], "limit": limit}, timeout=15)
        if r.ok:
            data = r.json()
            results = data if isinstance(data, list) else data.get("results", [])
            return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("snippet", x.get("content", ""))} for x in results]
    except Exception:
        pass
    return []


def fetch_article(url: str) -> str | None:
    """Fetch and extract article content."""
    import requests
    from bs4 import BeautifulSoup
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:15000] if text and len(text) > 100 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Knowledge Base Scanning
# ---------------------------------------------------------------------------

def load_all_frameworks() -> list[dict]:
    """Load every framework from the knowledge base."""
    frameworks = []
    for domain_dir in KNOWLEDGE_DIR.iterdir():
        if domain_dir.is_dir() and not domain_dir.name.startswith("_") and domain_dir.name != "dissolved":
            for f in domain_dir.glob("*.json"):
                try:
                    fw = json.loads(f.read_text())
                    fw["_path"] = str(f)
                    fw["_domain_dir"] = domain_dir.name
                    frameworks.append(fw)
                except Exception:
                    pass
    return frameworks


def load_barrier_taxonomy() -> dict | None:
    """Load the barrier taxonomy if it exists."""
    psych_dir = KNOWLEDGE_DIR / "psychology"
    if not psych_dir.exists():
        return None
    for f in sorted(psych_dir.glob("barrier_taxonomy_*.json"), reverse=True):
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return None


def scan_complexity_targets(frameworks: list[dict]) -> list[dict]:
    """Identify frameworks that exhibit complexity theater."""
    complexity_keywords = [
        "compliance", "regulatory", "regulation", "standardization", "audit",
        "certification", "protocol", "framework", "methodology", "process",
        "multi-standard", "cascading", "exemption", "requirement", "mandate",
        "complexity", "theater", "jargon", "bureaucra", "overhead"
    ]

    targets = []
    for fw in frameworks:
        text = json.dumps(fw).lower()
        hits = sum(1 for kw in complexity_keywords if kw in text)
        if hits >= 2:
            targets.append({
                "name": fw.get("name", "unnamed"),
                "domain": fw.get("_domain_dir", "unknown"),
                "description": fw.get("description", "")[:200],
                "confidence": fw.get("confidence", 0.5),
                "tags": fw.get("tags", []),
                "complexity_signal_strength": hits,
                "path": fw.get("_path", ""),
            })

    # Also pull from barrier taxonomy
    taxonomy = load_barrier_taxonomy()
    if taxonomy:
        ct = taxonomy.get("taxonomy", {}).get("barrier_types", {}).get("complexity_theater", {})
        for evidence in ct.get("evidence", []):
            targets.append({
                "name": evidence[:60],
                "domain": "barrier-taxonomy",
                "description": evidence,
                "confidence": 0.8,
                "tags": ["complexity-theater", "barrier"],
                "complexity_signal_strength": 5,
                "path": "barrier_taxonomy",
            })

    targets.sort(key=lambda x: x["complexity_signal_strength"], reverse=True)
    return targets


def rank_targets_with_ai(targets: list[dict]) -> list[dict]:
    """Use AI to rank and group complexity targets by dissolvability."""
    if not targets:
        return []

    target_text = "\n".join(
        f"- [{t['domain']}] {t['name']} (signal: {t['complexity_signal_strength']}): {t['description'][:150]}"
        for t in targets[:40]
    )

    system = """You are analyzing complexity theater targets — regulations, standards, and 
processes that are more complex than they need to be. Rank them by DISSOLVABILITY:
how much value would simplifying this create?

For each target, output JSON:
{
    "name": "short name of the complexity target",
    "dissolvability": "high|medium|low",
    "perceived_complexity": 1-10,
    "estimated_actual_complexity": 1-10,
    "theater_gap": "perceived minus actual",
    "who_benefits_from_theater": "consultants|vendors|incumbents|regulators",
    "research_queries": ["2-3 search queries to find the actual requirements"],
    "priority_reason": "why dissolving this matters"
}

Output a JSON array. Focus on the top 5-8 most dissolvable targets."""

    print("🎯 Ranking complexity targets by dissolvability...", flush=True)
    response = call_claude(system, f"## Complexity Targets\n{target_text}")

    try:
        match = re.search(r'\[[\s\S]*\]', response)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass
    return []


# ---------------------------------------------------------------------------
# Dissolution Engine
# ---------------------------------------------------------------------------

def research_actual_requirements(target: dict) -> str:
    """Research the actual requirements behind the complexity."""
    queries = target.get("research_queries", [target["name"]])
    all_content = []

    for query in queries[:3]:
        print(f"   🔎 Searching: {query}", flush=True)
        results = search(query, limit=3)
        for r in results[:2]:
            content = fetch_article(r.get("url", ""))
            if content and len(content) > 200:
                all_content.append(f"### {r.get('title', 'Unknown')}\nURL: {r.get('url', '')}\n\n{content[:5000]}")
                print(f"      📄 {r.get('title', '')[:50]} ({len(content):,} chars)", flush=True)

    return "\n\n---\n\n".join(all_content) if all_content else ""


def dissolve_target(target: dict, research: str) -> dict:
    """Generate a Plain Language Action Guide for a complexity target."""
    system = """You are the Complexity Dissolver. Your job is to strip complexity theater 
from regulations, standards, and processes to reveal what's ACTUALLY required.

You produce "Plain Language Action Guides" that:
1. State what the regulation/standard ACTUALLY requires in plain English
2. Identify what's REAL requirement vs what's THEATER (added by consultants/vendors/incumbents)
3. Provide the minimum viable compliance path
4. List specific jargon terms and their plain-English equivalents
5. Identify who benefits from the complexity (follow the money)

Be AGGRESSIVE about simplification. If a 50-page compliance manual can be reduced to 
a 1-page checklist, do it. If "specialized training" means "read this 3-page document," say so.

Output a markdown guide with these sections:
# [Name] — Dissolved

## TL;DR (3 sentences max)
## What's Actually Required (numbered list, plain English)
## What's Theater (things that LOOK required but aren't)
## Minimum Viable Compliance (step-by-step, simplest path)
## Jargon Decoder (term → plain English)
## Who Benefits From The Complexity
## Complexity Score
- Perceived complexity: X/10
- Actual complexity: X/10
- Theater gap: X points
## Sources"""

    user = f"""## Target: {target['name']}
Domain: {target.get('domain', 'unknown')}
Description: {target.get('description', '')}

## Research Findings
{research[:10000] if research else 'No external research available — dissolve based on the framework description and your knowledge.'}

Generate the Plain Language Action Guide."""

    print(f"   🧪 Dissolving: {target['name'][:50]}...", flush=True)
    guide = call_claude(system, user, max_tokens=6000)
    return {
        "name": target["name"],
        "domain": target.get("domain", "unknown"),
        "guide": guide,
        "perceived_complexity": target.get("perceived_complexity", 7),
        "estimated_actual_complexity": target.get("estimated_actual_complexity", 3),
        "theater_gap": target.get("theater_gap", "4"),
    }


def save_dissolved(result: dict) -> Path:
    """Save a dissolved guide to the knowledge base."""
    slug = re.sub(r'[^a-z0-9]+', '-', result["name"].lower().strip())[:60]
    date = datetime.now().strftime("%Y%m%d")

    # Save markdown guide
    md_path = DISSOLVED_DIR / f"{slug}-{date}.md"
    md_path.write_text(result["guide"])

    # Save metadata
    meta_path = DISSOLVED_DIR / f"{slug}-{date}.json"
    meta = {
        "name": result["name"],
        "domain": result["domain"],
        "dissolved_at": datetime.now(timezone.utc).isoformat(),
        "perceived_complexity": result.get("perceived_complexity"),
        "estimated_actual_complexity": result.get("estimated_actual_complexity"),
        "theater_gap": result.get("theater_gap"),
        "guide_path": str(md_path),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"   💾 Saved: {md_path.name}", flush=True)
    return md_path


# ---------------------------------------------------------------------------
# Status & Reporting
# ---------------------------------------------------------------------------

def show_status():
    """Show what's been dissolved."""
    print(f"\n{'='*60}", flush=True)
    print("🧪 COMPLEXITY DISSOLVER — Status", flush=True)
    print(f"{'='*60}\n", flush=True)

    dissolved = list(DISSOLVED_DIR.glob("*.json"))
    if not dissolved:
        print("  No targets dissolved yet. Run: python3 dissolve.py", flush=True)
        return

    for f in sorted(dissolved, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(f.read_text())
            gap = meta.get("theater_gap", "?")
            print(f"  🧪 {meta.get('name', '?')[:50]}", flush=True)
            print(f"     Domain: {meta.get('domain', '?')} | Theater gap: {gap} | {meta.get('dissolved_at', '?')[:10]}", flush=True)
        except Exception:
            pass
    print(flush=True)


def cost_estimate(targets: list[dict]) -> None:
    """Estimate cost without running."""
    n = min(len(targets), 5)
    # Per target: 1 ranking call (shared) + 1-3 search fetches + 1 dissolve call
    # Ranking: ~2K input + 2K output = ~$0.02
    # Per dissolve: ~5K input + 3K output = ~$0.04
    ranking_cost = 0.02
    per_target = 0.04 + 0.01  # dissolve + search overhead
    total = ranking_cost + (n * per_target)
    print(f"\n💰 COST ESTIMATE", flush=True)
    print(f"   Targets to dissolve: {n}", flush=True)
    print(f"   Ranking call: ~${ranking_cost:.2f}", flush=True)
    print(f"   Per target: ~${per_target:.2f}", flush=True)
    print(f"   Estimated total: ~${total:.2f}", flush=True)
    print(f"   Budget target: <$1.00 ✅" if total < 1.0 else f"   ⚠️ May exceed $1.00", flush=True)


# ---------------------------------------------------------------------------
# Main Cycle
# ---------------------------------------------------------------------------

def run_scan():
    """Scan and rank complexity targets."""
    print(f"\n{'='*70}", flush=True)
    print("🧪 COMPLEXITY DISSOLVER — Scan Mode", flush=True)
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'='*70}\n", flush=True)

    frameworks = load_all_frameworks()
    print(f"📚 Loaded {len(frameworks)} frameworks", flush=True)

    targets = scan_complexity_targets(frameworks)
    print(f"🎯 Found {len(targets)} complexity signals\n", flush=True)

    ranked = rank_targets_with_ai(targets)
    if ranked:
        print(f"\n📋 TOP COMPLEXITY TARGETS (by dissolvability):", flush=True)
        print("-" * 60, flush=True)
        for i, t in enumerate(ranked, 1):
            perceived = t.get("perceived_complexity", "?")
            actual = t.get("estimated_actual_complexity", "?")
            print(f"\n  {i}. [{t.get('dissolvability', '?').upper()}] {t.get('name', '?')}", flush=True)
            print(f"     Perceived: {perceived}/10 → Actual: {actual}/10 (gap: {t.get('theater_gap', '?')})", flush=True)
            print(f"     Theater beneficiary: {t.get('who_benefits_from_theater', '?')}", flush=True)
            print(f"     Why: {t.get('priority_reason', '')[:100]}", flush=True)

    return ranked


def dissolve_specific(target_name: str):
    """Dissolve a specific regulation/standard by name."""
    print(f"\n{'='*70}", flush=True)
    print(f"🧪 DISSOLVING: {target_name}", flush=True)
    print(f"{'='*70}\n", flush=True)

    target = {
        "name": target_name,
        "domain": "specific-request",
        "description": target_name,
        "research_queries": [
            f"{target_name} actual requirements plain language",
            f"{target_name} compliance simplified",
            f"{target_name} what is actually required",
        ],
        "perceived_complexity": 8,
        "estimated_actual_complexity": 3,
        "theater_gap": "5",
    }

    research = research_actual_requirements(target)
    result = dissolve_target(target, research)
    path = save_dissolved(result)

    print(f"\n{'='*70}", flush=True)
    print(f"✅ DISSOLVED: {target_name}", flush=True)
    print(f"   Guide: {path}", flush=True)
    print(f"{'='*70}", flush=True)


def run_full_cycle():
    """Full cycle: scan → rank → dissolve top targets → save."""
    print(f"\n{'='*70}", flush=True)
    print("🧪 COMPLEXITY DISSOLVER — Full Cycle", flush=True)
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'='*70}\n", flush=True)

    # Step 1: Scan
    print("📡 Step 1/3: Scanning knowledge base for complexity targets...", flush=True)
    frameworks = load_all_frameworks()
    print(f"   {len(frameworks)} frameworks loaded", flush=True)
    targets = scan_complexity_targets(frameworks)
    print(f"   {len(targets)} complexity signals found\n", flush=True)

    # Step 2: Rank
    print("🎯 Step 2/3: Ranking targets by dissolvability...", flush=True)
    ranked = rank_targets_with_ai(targets)
    if not ranked:
        print("   ⚠️ No rankable targets found.", flush=True)
        return

    # Filter to high/medium dissolvability
    dissolvable = [t for t in ranked if t.get("dissolvability") in ("high", "medium")]
    if not dissolvable:
        dissolvable = ranked[:3]
    dissolvable = dissolvable[:5]  # Cap at 5 per cycle
    print(f"   {len(dissolvable)} targets selected for dissolution\n", flush=True)

    # Step 3: Dissolve
    print("🧪 Step 3/3: Dissolving complexity...\n", flush=True)
    dissolved_count = 0
    for target in dissolvable:
        print(f"\n{'─'*50}", flush=True)
        print(f"  Target: {target.get('name', '?')}", flush=True)
        research = research_actual_requirements(target)
        result = dissolve_target(target, research)
        save_dissolved(result)
        dissolved_count += 1

    # Write agent report
    report = {
        "agent": "dissolve",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frameworks_scanned": len(frameworks),
        "complexity_signals": len(targets),
        "targets_ranked": len(ranked),
        "targets_dissolved": dissolved_count,
    }
    report_path = REPORTS_DIR / f"dissolve-{datetime.now().strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*70}", flush=True)
    print(f"✅ DISSOLVE CYCLE COMPLETE", flush=True)
    print(f"   Dissolved: {dissolved_count} targets", flush=True)
    print(f"   Guides saved to: {DISSOLVED_DIR}", flush=True)
    print(f"   Report: {report_path}", flush=True)
    print(f"{'='*70}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Complexity Dissolver — strips complexity theater")
    parser.add_argument("--target", type=str, help="Dissolve a specific regulation/standard")
    parser.add_argument("--scan", action="store_true", help="Scan and rank complexity targets only")
    parser.add_argument("--status", action="store_true", help="Show what's been dissolved")
    parser.add_argument("--cost-estimate", action="store_true", help="Estimate cost without running")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.scan:
        run_scan()
    elif args.target:
        dissolve_specific(args.target)
    elif args.cost_estimate:
        frameworks = load_all_frameworks()
        targets = scan_complexity_targets(frameworks)
        cost_estimate(targets)
    else:
        run_full_cycle()


if __name__ == "__main__":
    main()
