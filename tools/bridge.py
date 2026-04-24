#!/usr/bin/env python3
"""
bridge.py — The Participation Bridge

Target: Participation Gap (14 hits across 10 domains)

Massive markets exist where tiny participation rates mean most people are
locked out. Government procurement ($10.1T), manufacturing technology,
food safety compliance — the opportunities are known but participation
is near zero. This agent builds bridges from awareness to action.

The loop:
  1. Scan knowledge base for frameworks with low participation in large markets
  2. Use Dissolve and Equalizer outputs to build "Bridge Guides"
  3. Each guide: What's the opportunity? Why don't people participate? What's step 1?
  4. Generate "Participation Scorecards" — accessibility scoring
  5. Identify where Dissolve or Equalizer need to do more work
  6. Deposit in knowledge/bridged/

Usage:
    python3 bridge.py                                        # Full cycle
    python3 bridge.py --opportunity "government procurement"  # Bridge specific opportunity
    python3 bridge.py --scan                                 # Scan and rank gaps
    python3 bridge.py --status                               # Show what's been bridged
    python3 bridge.py --cost-estimate                        # Estimate cost
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
BRIDGED_DIR = KNOWLEDGE_DIR / "bridged"
DISSOLVED_DIR = KNOWLEDGE_DIR / "dissolved"
EQUALIZED_DIR = KNOWLEDGE_DIR / "equalized"
REPORTS_DIR = STATE_DIR / "agent-reports"
BRIDGED_DIR.mkdir(parents=True, exist_ok=True)
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
# Knowledge Base & Cross-Agent Loading
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
    """Load Complexity Dissolver outputs."""
    guides = []
    for f in DISSOLVED_DIR.glob("*.json"):
        try:
            meta = json.loads(f.read_text())
            # Also load the markdown guide if available
            guide_path = meta.get("guide_path")
            if guide_path and Path(guide_path).exists():
                meta["guide_content"] = Path(guide_path).read_text()[:3000]
            guides.append(meta)
        except Exception:
            pass
    return guides


def load_equalized_reports() -> list[dict]:
    """Load Knowledge Equalizer outputs."""
    reports = []
    for f in EQUALIZED_DIR.glob("*.json"):
        try:
            meta = json.loads(f.read_text())
            report_path = meta.get("report_path")
            if report_path and Path(report_path).exists():
                meta["report_content"] = Path(report_path).read_text()[:3000]
            reports.append(meta)
        except Exception:
            pass
    return reports


def scan_participation_gaps(frameworks: list[dict]) -> list[dict]:
    """Identify frameworks with participation gaps."""
    gap_keywords = [
        "participation", "adoption", "gap", "underserved", "untapped",
        "market size", "trillion", "billion", "low adoption", "barrier",
        "accessibility", "small player", "excluded", "locked out",
        "opportunity", "procurement", "compliance deadline", "mandate"
    ]

    targets = []
    for fw in frameworks:
        text = json.dumps(fw).lower()
        hits = sum(1 for kw in gap_keywords if kw in text)
        if hits >= 2:
            targets.append({
                "name": fw.get("name", "unnamed"),
                "domain": fw.get("_domain_dir", "unknown"),
                "description": fw.get("description", "")[:200],
                "confidence": fw.get("confidence", 0.5),
                "tags": fw.get("tags", []),
                "gap_signal_strength": hits,
                "path": fw.get("_path", ""),
            })

    # Pull from barrier taxonomy
    taxonomy = load_barrier_taxonomy()
    if taxonomy:
        pg = taxonomy.get("taxonomy", {}).get("barrier_types", {}).get("participation_gap", {})
        for evidence in pg.get("evidence", []):
            targets.append({
                "name": evidence[:60],
                "domain": "barrier-taxonomy",
                "description": evidence,
                "confidence": 0.8,
                "tags": ["participation-gap", "barrier"],
                "gap_signal_strength": 5,
                "path": "barrier_taxonomy",
            })

    targets.sort(key=lambda x: x["gap_signal_strength"], reverse=True)
    return targets


def rank_gaps_with_ai(targets: list[dict]) -> list[dict]:
    """Rank participation gaps by bridgeability."""
    if not targets:
        return []

    target_text = "\n".join(
        f"- [{t['domain']}] {t['name']} (signal: {t['gap_signal_strength']}): {t['description'][:150]}"
        for t in targets[:40]
    )

    # Include cross-agent context
    dissolved = load_dissolved_guides()
    equalized = load_equalized_reports()
    cross_context = ""
    if dissolved:
        cross_context += "\n\nAlready Dissolved (complexity stripped):\n" + "\n".join(
            f"- {d['name']}" for d in dissolved[:5])
    if equalized:
        cross_context += "\n\nAlready Equalized (knowledge democratized):\n" + "\n".join(
            f"- {e['name']}" for e in equalized[:5])

    system = """You are analyzing participation gaps — massive markets/opportunities where 
most potential participants are locked out. Rank them by BRIDGEABILITY:
how actionable is it to close this gap?

For each gap, output JSON:
{
    "name": "short name of the opportunity",
    "market_size": "estimated market size",
    "current_participation": "who participates now and roughly what %",
    "bridgeability": "high|medium|low",
    "primary_blocker": "complexity|knowledge|cost|access|awareness",
    "needs_dissolve": true/false (does complexity theater block participation?),
    "needs_equalize": true/false (does knowledge asymmetry block participation?),
    "research_queries": ["2-3 search queries"],
    "first_step": "the single first action someone could take TODAY",
    "priority_reason": "why bridging this matters"
}

Output a JSON array. Top 5-8 most bridgeable gaps."""

    print("🎯 Ranking participation gaps by bridgeability...", flush=True)
    response = call_claude(system, f"## Participation Gaps\n{target_text}{cross_context}")

    try:
        match = re.search(r'\[[\s\S]*\]', response)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass
    return []


# ---------------------------------------------------------------------------
# Bridge Building Engine
# ---------------------------------------------------------------------------

def research_participation(target: dict) -> str:
    """Research the participation gap."""
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


def build_bridge(target: dict, research: str) -> dict:
    """Generate a Bridge Guide and Participation Scorecard."""
    # Gather cross-agent intelligence
    dissolved = load_dissolved_guides()
    equalized = load_equalized_reports()

    cross_intel = ""
    domain_keywords = target.get("domain", "").lower().replace("-", " ").split()
    name_keywords = target.get("name", "").lower().split()[:3]
    match_keywords = set(domain_keywords + name_keywords)

    for d in dissolved:
        if any(kw in d.get("name", "").lower() or kw in d.get("domain", "").lower() for kw in match_keywords):
            cross_intel += f"\n\n### Dissolved Guide: {d['name']}\n{d.get('guide_content', 'No content')[:1500]}"

    for e in equalized:
        if any(kw in e.get("name", "").lower() or kw in e.get("domain", "").lower() for kw in match_keywords):
            cross_intel += f"\n\n### Equalized Report: {e['name']}\n{e.get('report_content', 'No content')[:1500]}"

    system = """You are the Participation Bridge. You build step-by-step guides that close 
the gap between knowing an opportunity exists and actually participating in it.

Every Bridge Guide must be BRUTALLY ACTIONABLE. No theory. No "consider your options."
Real steps, real timelines, real first moves.

Output TWO things:

## PART 1: Bridge Guide (markdown)

# [Opportunity] — Bridge Guide

## The Opportunity (2-3 sentences: what exists, how big, why it matters)
## Why People Don't Participate (the real blockers, not the excuses)
## The Bridge (step-by-step action plan)
### Step 1: What to do TODAY (literally today, <30 minutes)
### Step 2: This week
### Step 3: This month  
### Step 4: First 90 days
## What You DON'T Need (myths about requirements)
## Who's Already Doing This (real examples of small players succeeding)
## Resources (specific links, programs, tools)

## PART 2: Participation Scorecard (embedded in the guide)

Rate 1-10 (10 = easiest):
- **Cost to start**: 
- **Complexity**: 
- **Time to first result**: 
- **Expertise required**: 
- **Overall accessibility**: (average)

## PART 3: Cross-Agent Requests

List any areas where:
- Complexity Dissolver should investigate (regulation/process too complex)
- Knowledge Equalizer should investigate (insider knowledge needed)

Format as JSON at the end:
```json
{"dissolve_requests": ["..."], "equalize_requests": ["..."]}
```"""

    user = f"""## Opportunity: {target['name']}
Market size: {target.get('market_size', 'unknown')}
Current participation: {target.get('current_participation', 'unknown')}
Primary blocker: {target.get('primary_blocker', 'unknown')}
First step idea: {target.get('first_step', 'unknown')}

## Research Findings
{research[:8000] if research else 'No external research — build bridge from framework data and your knowledge.'}

## Intelligence From Other Agents
{cross_intel if cross_intel else 'No dissolved guides or equalized reports available yet for this domain.'}

Build the Bridge Guide with Participation Scorecard."""

    print(f"   🌉 Building bridge: {target['name'][:50]}...", flush=True)
    guide = call_claude(system, user, max_tokens=6000)

    # Extract cross-agent requests
    dissolve_requests = []
    equalize_requests = []
    try:
        json_match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', guide)
        if json_match:
            requests_data = json.loads(json_match.group(1))
            dissolve_requests = requests_data.get("dissolve_requests", [])
            equalize_requests = requests_data.get("equalize_requests", [])
    except (json.JSONDecodeError, AttributeError):
        pass

    return {
        "name": target["name"],
        "domain": target.get("domain", "unknown"),
        "market_size": target.get("market_size", "unknown"),
        "primary_blocker": target.get("primary_blocker", "unknown"),
        "guide": guide,
        "dissolve_requests": dissolve_requests,
        "equalize_requests": equalize_requests,
    }


def save_bridged(result: dict) -> Path:
    slug = re.sub(r'[^a-z0-9]+', '-', result["name"].lower().strip())[:60]
    date = datetime.now().strftime("%Y%m%d")

    md_path = BRIDGED_DIR / f"{slug}-{date}.md"
    md_path.write_text(result["guide"])

    meta_path = BRIDGED_DIR / f"{slug}-{date}.json"
    meta = {
        "name": result["name"],
        "domain": result["domain"],
        "bridged_at": datetime.now(timezone.utc).isoformat(),
        "market_size": result.get("market_size"),
        "primary_blocker": result.get("primary_blocker"),
        "guide_path": str(md_path),
        "dissolve_requests": result.get("dissolve_requests", []),
        "equalize_requests": result.get("equalize_requests", []),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    # Log cross-agent requests
    if result.get("dissolve_requests"):
        print(f"   📤 Requests for Dissolver: {result['dissolve_requests']}", flush=True)
    if result.get("equalize_requests"):
        print(f"   📤 Requests for Equalizer: {result['equalize_requests']}", flush=True)

    print(f"   💾 Saved: {md_path.name}", flush=True)
    return md_path


# ---------------------------------------------------------------------------
# Status & Reporting
# ---------------------------------------------------------------------------

def show_status():
    print(f"\n{'='*60}", flush=True)
    print("🌉 PARTICIPATION BRIDGE — Status", flush=True)
    print(f"{'='*60}\n", flush=True)

    bridged = list(BRIDGED_DIR.glob("*.json"))
    if not bridged:
        print("  No opportunities bridged yet. Run: python3 bridge.py", flush=True)
        return

    pending_dissolve = []
    pending_equalize = []

    for f in sorted(bridged, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(f.read_text())
            print(f"  🌉 {meta.get('name', '?')[:50]}", flush=True)
            print(f"     Domain: {meta.get('domain', '?')} | Blocker: {meta.get('primary_blocker', '?')} | {meta.get('bridged_at', '?')[:10]}", flush=True)
            pending_dissolve.extend(meta.get("dissolve_requests", []))
            pending_equalize.extend(meta.get("equalize_requests", []))
        except Exception:
            pass

    if pending_dissolve:
        print(f"\n  📤 Pending Dissolve Requests:", flush=True)
        for r in pending_dissolve:
            print(f"     → {r}", flush=True)
    if pending_equalize:
        print(f"\n  📤 Pending Equalize Requests:", flush=True)
        for r in pending_equalize:
            print(f"     → {r}", flush=True)
    print(flush=True)


def cost_estimate(targets: list[dict]) -> None:
    n = min(len(targets), 5)
    ranking_cost = 0.02
    per_target = 0.05
    total = ranking_cost + (n * per_target)
    print(f"\n💰 COST ESTIMATE", flush=True)
    print(f"   Gaps to bridge: {n}", flush=True)
    print(f"   Estimated total: ~${total:.2f}", flush=True)
    print(f"   Budget target: <$1.00 ✅" if total < 1.0 else f"   ⚠️ May exceed $1.00", flush=True)


# ---------------------------------------------------------------------------
# Main Cycles
# ---------------------------------------------------------------------------

def run_scan():
    print(f"\n{'='*70}", flush=True)
    print("🌉 PARTICIPATION BRIDGE — Scan Mode", flush=True)
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'='*70}\n", flush=True)

    frameworks = load_all_frameworks()
    print(f"📚 Loaded {len(frameworks)} frameworks", flush=True)

    targets = scan_participation_gaps(frameworks)
    print(f"🎯 Found {len(targets)} participation gap signals\n", flush=True)

    ranked = rank_gaps_with_ai(targets)
    if ranked:
        print(f"\n📋 TOP PARTICIPATION GAPS:", flush=True)
        print("-" * 60, flush=True)
        for i, t in enumerate(ranked, 1):
            print(f"\n  {i}. [{t.get('bridgeability', '?').upper()}] {t.get('name', '?')}", flush=True)
            print(f"     Market: {t.get('market_size', '?')} | Blocker: {t.get('primary_blocker', '?')}", flush=True)
            print(f"     First step: {t.get('first_step', '')[:80]}", flush=True)
            if t.get("needs_dissolve"):
                print(f"     ⚠️ Needs Complexity Dissolver", flush=True)
            if t.get("needs_equalize"):
                print(f"     ⚠️ Needs Knowledge Equalizer", flush=True)

    return ranked


def bridge_specific(opportunity: str):
    """Bridge a specific opportunity."""
    print(f"\n{'='*70}", flush=True)
    print(f"🌉 BRIDGING: {opportunity}", flush=True)
    print(f"{'='*70}\n", flush=True)

    target = {
        "name": opportunity,
        "domain": "specific-request",
        "market_size": "unknown — will research",
        "current_participation": "unknown — will research",
        "primary_blocker": "unknown",
        "first_step": "to be determined",
        "research_queries": [
            f"{opportunity} how to get started small business",
            f"{opportunity} participation rates barriers",
            f"{opportunity} step by step guide beginners",
        ],
    }

    research = research_participation(target)
    result = build_bridge(target, research)
    path = save_bridged(result)

    print(f"\n✅ BRIDGED: {opportunity}", flush=True)
    print(f"   Guide: {path}", flush=True)


def run_full_cycle():
    print(f"\n{'='*70}", flush=True)
    print("🌉 PARTICIPATION BRIDGE — Full Cycle", flush=True)
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'='*70}\n", flush=True)

    # Step 1: Scan
    print("📡 Step 1/3: Scanning for participation gaps...", flush=True)
    frameworks = load_all_frameworks()
    print(f"   {len(frameworks)} frameworks loaded", flush=True)
    targets = scan_participation_gaps(frameworks)
    print(f"   {len(targets)} gap signals found\n", flush=True)

    # Step 2: Rank
    print("🎯 Step 2/3: Ranking by bridgeability...", flush=True)
    ranked = rank_gaps_with_ai(targets)
    if not ranked:
        print("   ⚠️ No rankable gaps found.", flush=True)
        return

    bridgeable = [t for t in ranked if t.get("bridgeability") in ("high", "medium")]
    if not bridgeable:
        bridgeable = ranked[:3]
    bridgeable = bridgeable[:5]
    print(f"   {len(bridgeable)} gaps selected for bridging\n", flush=True)

    # Step 3: Bridge
    print("🌉 Step 3/3: Building bridges...\n", flush=True)
    bridged_count = 0
    all_dissolve_requests = []
    all_equalize_requests = []

    for target in bridgeable:
        print(f"\n{'─'*50}", flush=True)
        print(f"  Gap: {target.get('name', '?')}", flush=True)
        research = research_participation(target)
        result = build_bridge(target, research)
        save_bridged(result)
        bridged_count += 1
        all_dissolve_requests.extend(result.get("dissolve_requests", []))
        all_equalize_requests.extend(result.get("equalize_requests", []))

    # Write agent report
    report = {
        "agent": "bridge",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frameworks_scanned": len(frameworks),
        "gap_signals": len(targets),
        "targets_ranked": len(ranked),
        "targets_bridged": bridged_count,
        "dissolve_requests": all_dissolve_requests,
        "equalize_requests": all_equalize_requests,
    }
    report_path = REPORTS_DIR / f"bridge-{datetime.now().strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*70}", flush=True)
    print(f"✅ BRIDGE CYCLE COMPLETE", flush=True)
    print(f"   Bridged: {bridged_count} opportunities", flush=True)
    print(f"   Guides saved to: {BRIDGED_DIR}", flush=True)
    if all_dissolve_requests:
        print(f"   📤 {len(all_dissolve_requests)} requests queued for Dissolver", flush=True)
    if all_equalize_requests:
        print(f"   📤 {len(all_equalize_requests)} requests queued for Equalizer", flush=True)
    print(f"   Agent report: {report_path}", flush=True)
    print(f"{'='*70}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Participation Bridge — closes the gap from awareness to action")
    parser.add_argument("--opportunity", type=str, help="Bridge a specific opportunity")
    parser.add_argument("--scan", action="store_true", help="Scan and rank participation gaps only")
    parser.add_argument("--status", action="store_true", help="Show what's been bridged")
    parser.add_argument("--cost-estimate", action="store_true", help="Estimate cost without running")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.scan:
        run_scan()
    elif args.opportunity:
        bridge_specific(args.opportunity)
    elif args.cost_estimate:
        frameworks = load_all_frameworks()
        targets = scan_participation_gaps(frameworks)
        cost_estimate(targets)
    else:
        run_full_cycle()


if __name__ == "__main__":
    main()
