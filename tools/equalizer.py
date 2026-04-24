#!/usr/bin/env python3
"""
equalizer.py — The Knowledge Equalizer

Target: Knowledge Asymmetry (14 hits across 12 domains)

Insider knowledge creates unfair advantages. OEE benchmarks are hoarded.
Cost structures are tribal knowledge. Industry standards are paywalled.
This agent finds and democratizes that knowledge so small players can compete.

The loop:
  1. Scan knowledge base for frameworks where insider knowledge = advantage
  2. Research to find and aggregate the hoarded knowledge
  3. Generate "Benchmark Reports" — democratized intelligence
  4. Identify specific knowledge gaps small players don't know about
  5. Deposit findings in knowledge/equalized/

Usage:
    python3 equalizer.py                              # Full cycle
    python3 equalizer.py --domain "food-manufacturing" # Equalize a specific domain
    python3 equalizer.py --scan                       # Scan and rank asymmetry targets
    python3 equalizer.py --status                     # Show what's been equalized
    python3 equalizer.py --cost-estimate              # Estimate cost without running
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
EQUALIZED_DIR = KNOWLEDGE_DIR / "equalized"
DISSOLVED_DIR = KNOWLEDGE_DIR / "dissolved"
REPORTS_DIR = STATE_DIR / "agent-reports"
EQUALIZED_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "claude-sonnet-4-5-20250929"


from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str, model: str = MODEL, max_tokens: int = 4096) -> str:
    return _call_claude_base(system, user, model=model, max_tokens=max_tokens)


def search(query: str, limit: int = 5) -> list[dict]:
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
    frameworks = []
    for domain_dir in KNOWLEDGE_DIR.iterdir():
        if domain_dir.is_dir() and not domain_dir.name.startswith("_") and domain_dir.name not in ("dissolved", "equalized", "bridged"):
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
    psych_dir = KNOWLEDGE_DIR / "psychology"
    if not psych_dir.exists():
        return None
    for f in sorted(psych_dir.glob("barrier_taxonomy_*.json"), reverse=True):
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return None


def load_dissolved_guides() -> list[dict]:
    """Load outputs from the Complexity Dissolver for cross-referencing."""
    guides = []
    for f in DISSOLVED_DIR.glob("*.json"):
        try:
            guides.append(json.loads(f.read_text()))
        except Exception:
            pass
    return guides


def scan_asymmetry_targets(frameworks: list[dict]) -> list[dict]:
    """Identify frameworks exhibiting knowledge asymmetry."""
    asymmetry_keywords = [
        "insider", "benchmark", "proprietary", "hoarded", "tribal",
        "paywalled", "cost structure", "pricing", "margin", "secret",
        "specialized knowledge", "expertise gap", "information advantage",
        "asymmetr", "opaque", "hidden", "undisclosed", "industry standard"
    ]

    targets = []
    for fw in frameworks:
        text = json.dumps(fw).lower()
        hits = sum(1 for kw in asymmetry_keywords if kw in text)
        if hits >= 2:
            targets.append({
                "name": fw.get("name", "unnamed"),
                "domain": fw.get("_domain_dir", "unknown"),
                "description": fw.get("description", "")[:200],
                "confidence": fw.get("confidence", 0.5),
                "tags": fw.get("tags", []),
                "asymmetry_signal_strength": hits,
                "path": fw.get("_path", ""),
            })

    # Pull from barrier taxonomy
    taxonomy = load_barrier_taxonomy()
    if taxonomy:
        ka = taxonomy.get("taxonomy", {}).get("barrier_types", {}).get("knowledge_asymmetry", {})
        for evidence in ka.get("evidence", []):
            targets.append({
                "name": evidence[:60],
                "domain": "barrier-taxonomy",
                "description": evidence,
                "confidence": 0.8,
                "tags": ["knowledge-asymmetry", "barrier"],
                "asymmetry_signal_strength": 5,
                "path": "barrier_taxonomy",
            })

    targets.sort(key=lambda x: x["asymmetry_signal_strength"], reverse=True)
    return targets


def rank_asymmetries_with_ai(targets: list[dict]) -> list[dict]:
    """Rank knowledge asymmetry targets by equalizability."""
    if not targets:
        return []

    target_text = "\n".join(
        f"- [{t['domain']}] {t['name']} (signal: {t['asymmetry_signal_strength']}): {t['description'][:150]}"
        for t in targets[:40]
    )

    system = """You are analyzing knowledge asymmetry targets — areas where insider knowledge
creates unfair advantages for incumbents over small players. Rank them by EQUALIZABILITY:
how much value would democratizing this knowledge create?

For each target, output JSON:
{
    "name": "short name",
    "domain": "the industry/domain",
    "equalizability": "high|medium|low",
    "knowledge_type": "benchmarks|cost_structures|processes|regulations|tribal_knowledge",
    "who_hoards": "description of who has this knowledge",
    "who_needs": "description of who lacks it",
    "research_queries": ["2-3 search queries to find the hidden knowledge"],
    "equalizer_approach": "how to democratize this — benchmarks? templates? calculators?",
    "priority_reason": "why equalizing this matters"
}

Output a JSON array. Top 5-8 most impactful targets."""

    print("🎯 Ranking asymmetry targets by equalizability...", flush=True)
    response = call_claude(system, f"## Knowledge Asymmetry Targets\n{target_text}")

    try:
        match = re.search(r'\[[\s\S]*\]', response)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass
    return []


# ---------------------------------------------------------------------------
# Equalization Engine
# ---------------------------------------------------------------------------

def research_hidden_knowledge(target: dict) -> str:
    """Research to find the hoarded/hidden knowledge."""
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


def equalize_target(target: dict, research: str) -> dict:
    """Generate a Benchmark Report that democratizes knowledge."""
    # Check if Dissolver has relevant guides
    dissolved = load_dissolved_guides()
    dissolved_context = ""
    if dissolved:
        relevant = [d for d in dissolved if any(
            kw in d.get("name", "").lower() or kw in d.get("domain", "").lower()
            for kw in target.get("domain", "").lower().split("-")
        )]
        if relevant:
            dissolved_context = "\n\nRelated Dissolved Guides:\n" + "\n".join(
                f"- {d['name']} (theater gap: {d.get('theater_gap', '?')})" for d in relevant[:3]
            )

    system = """You are the Knowledge Equalizer. Your job is to democratize insider knowledge
so small players can compete with incumbents.

You produce "Benchmark Reports" that contain:
1. ACTUAL NUMBERS — real benchmarks, costs, timelines that insiders know but outsiders don't
2. INDUSTRY STANDARDS — what "normal" looks like (OEE rates, margins, costs, timelines)
3. HIDDEN RESOURCES — programs, tools, associations that small players don't know about
4. INSIDER TERMINOLOGY — the language you need to speak to be taken seriously
5. COMMON TRAPS — mistakes newcomers make that insiders avoid
6. ACTION ITEMS — what to do with this knowledge

Be SPECIFIC. "Typical OEE for a food plant your size is 55-65%" beats "OEE varies."
"MEP offers free consulting for manufacturers under 500 employees" beats "government help exists."

Output markdown:
# [Domain] — Knowledge Equalized

## TL;DR (what insiders know that you don't)
## The Numbers (benchmarks, costs, margins, timelines)
## Hidden Resources (programs, tools, associations)
## Insider Playbook (how the experienced players actually operate)
## Common Traps (expensive mistakes newcomers make)
## Terminology Guide (speak the language)
## What To Do Monday Morning (3 specific actions)
## Knowledge Gaps Remaining (what we still need to find)"""

    user = f"""## Target: {target['name']}
Domain: {target.get('domain', 'unknown')}
Knowledge type: {target.get('knowledge_type', 'unknown')}
Who hoards: {target.get('who_hoards', 'unknown')}
Who needs: {target.get('who_needs', 'unknown')}

## Research Findings
{research[:10000] if research else 'No external research — equalize based on framework data and your knowledge.'}
{dissolved_context}

Generate the Benchmark Report."""

    print(f"   ⚖️ Equalizing: {target['name'][:50]}...", flush=True)
    report = call_claude(system, user, max_tokens=6000)
    return {
        "name": target["name"],
        "domain": target.get("domain", "unknown"),
        "knowledge_type": target.get("knowledge_type", "unknown"),
        "report": report,
        "who_hoards": target.get("who_hoards", ""),
        "who_needs": target.get("who_needs", ""),
    }


def save_equalized(result: dict) -> Path:
    slug = re.sub(r'[^a-z0-9]+', '-', result["name"].lower().strip())[:60]
    date = datetime.now().strftime("%Y%m%d")

    md_path = EQUALIZED_DIR / f"{slug}-{date}.md"
    md_path.write_text(result["report"])

    meta_path = EQUALIZED_DIR / f"{slug}-{date}.json"
    meta = {
        "name": result["name"],
        "domain": result["domain"],
        "knowledge_type": result["knowledge_type"],
        "equalized_at": datetime.now(timezone.utc).isoformat(),
        "who_hoards": result.get("who_hoards"),
        "who_needs": result.get("who_needs"),
        "report_path": str(md_path),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"   💾 Saved: {md_path.name}", flush=True)
    return md_path


# ---------------------------------------------------------------------------
# Status & Reporting
# ---------------------------------------------------------------------------

def show_status():
    print(f"\n{'='*60}", flush=True)
    print("⚖️ KNOWLEDGE EQUALIZER — Status", flush=True)
    print(f"{'='*60}\n", flush=True)

    equalized = list(EQUALIZED_DIR.glob("*.json"))
    if not equalized:
        print("  No targets equalized yet. Run: python3 equalizer.py", flush=True)
        return

    for f in sorted(equalized, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(f.read_text())
            print(f"  ⚖️ {meta.get('name', '?')[:50]}", flush=True)
            print(f"     Domain: {meta.get('domain', '?')} | Type: {meta.get('knowledge_type', '?')} | {meta.get('equalized_at', '?')[:10]}", flush=True)
        except Exception:
            pass
    print(flush=True)


def cost_estimate(targets: list[dict]) -> None:
    n = min(len(targets), 5)
    ranking_cost = 0.02
    per_target = 0.05
    total = ranking_cost + (n * per_target)
    print(f"\n💰 COST ESTIMATE", flush=True)
    print(f"   Targets to equalize: {n}", flush=True)
    print(f"   Estimated total: ~${total:.2f}", flush=True)
    print(f"   Budget target: <$1.00 ✅" if total < 1.0 else f"   ⚠️ May exceed $1.00", flush=True)


# ---------------------------------------------------------------------------
# Main Cycles
# ---------------------------------------------------------------------------

def run_scan():
    print(f"\n{'='*70}", flush=True)
    print("⚖️ KNOWLEDGE EQUALIZER — Scan Mode", flush=True)
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'='*70}\n", flush=True)

    frameworks = load_all_frameworks()
    print(f"📚 Loaded {len(frameworks)} frameworks", flush=True)

    targets = scan_asymmetry_targets(frameworks)
    print(f"🎯 Found {len(targets)} asymmetry signals\n", flush=True)

    ranked = rank_asymmetries_with_ai(targets)
    if ranked:
        print(f"\n📋 TOP KNOWLEDGE ASYMMETRY TARGETS:", flush=True)
        print("-" * 60, flush=True)
        for i, t in enumerate(ranked, 1):
            print(f"\n  {i}. [{t.get('equalizability', '?').upper()}] {t.get('name', '?')}", flush=True)
            print(f"     Type: {t.get('knowledge_type', '?')} | Hoarded by: {t.get('who_hoards', '?')[:40]}", flush=True)
            print(f"     Approach: {t.get('equalizer_approach', '')[:80]}", flush=True)

    return ranked


def equalize_domain(domain: str):
    """Equalize knowledge for a specific domain."""
    print(f"\n{'='*70}", flush=True)
    print(f"⚖️ EQUALIZING DOMAIN: {domain}", flush=True)
    print(f"{'='*70}\n", flush=True)

    target = {
        "name": f"{domain} industry knowledge",
        "domain": domain,
        "knowledge_type": "benchmarks",
        "who_hoards": f"Large {domain} incumbents and industry consultants",
        "who_needs": f"Small {domain} businesses and new entrants",
        "research_queries": [
            f"{domain} industry benchmarks small business",
            f"{domain} typical costs margins operations",
            f"{domain} resources programs small manufacturers",
        ],
    }

    research = research_hidden_knowledge(target)
    result = equalize_target(target, research)
    path = save_equalized(result)

    print(f"\n✅ EQUALIZED: {domain}", flush=True)
    print(f"   Report: {path}", flush=True)


def run_full_cycle():
    print(f"\n{'='*70}", flush=True)
    print("⚖️ KNOWLEDGE EQUALIZER — Full Cycle", flush=True)
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'='*70}\n", flush=True)

    # Step 1: Scan
    print("📡 Step 1/3: Scanning for knowledge asymmetries...", flush=True)
    frameworks = load_all_frameworks()
    print(f"   {len(frameworks)} frameworks loaded", flush=True)
    targets = scan_asymmetry_targets(frameworks)
    print(f"   {len(targets)} asymmetry signals found\n", flush=True)

    # Step 2: Rank
    print("🎯 Step 2/3: Ranking by equalizability...", flush=True)
    ranked = rank_asymmetries_with_ai(targets)
    if not ranked:
        print("   ⚠️ No rankable targets found.", flush=True)
        return

    equalizable = [t for t in ranked if t.get("equalizability") in ("high", "medium")]
    if not equalizable:
        equalizable = ranked[:3]
    equalizable = equalizable[:5]
    print(f"   {len(equalizable)} targets selected for equalization\n", flush=True)

    # Step 3: Equalize
    print("⚖️ Step 3/3: Equalizing knowledge...\n", flush=True)
    equalized_count = 0
    for target in equalizable:
        print(f"\n{'─'*50}", flush=True)
        print(f"  Target: {target.get('name', '?')}", flush=True)
        research = research_hidden_knowledge(target)
        result = equalize_target(target, research)
        save_equalized(result)
        equalized_count += 1

    # Write agent report
    report = {
        "agent": "equalizer",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frameworks_scanned": len(frameworks),
        "asymmetry_signals": len(targets),
        "targets_ranked": len(ranked),
        "targets_equalized": equalized_count,
    }
    report_path = REPORTS_DIR / f"equalizer-{datetime.now().strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*70}", flush=True)
    print(f"✅ EQUALIZER CYCLE COMPLETE", flush=True)
    print(f"   Equalized: {equalized_count} targets", flush=True)
    print(f"   Reports saved to: {EQUALIZED_DIR}", flush=True)
    print(f"   Agent report: {report_path}", flush=True)
    print(f"{'='*70}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Knowledge Equalizer — democratizes insider knowledge")
    parser.add_argument("--domain", type=str, help="Equalize knowledge for a specific domain")
    parser.add_argument("--scan", action="store_true", help="Scan and rank asymmetry targets only")
    parser.add_argument("--status", action="store_true", help="Show what's been equalized")
    parser.add_argument("--cost-estimate", action="store_true", help="Estimate cost without running")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.scan:
        run_scan()
    elif args.domain:
        equalize_domain(args.domain)
    elif args.cost_estimate:
        frameworks = load_all_frameworks()
        targets = scan_asymmetry_targets(frameworks)
        cost_estimate(targets)
    else:
        run_full_cycle()


if __name__ == "__main__":
    main()
