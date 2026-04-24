#!/usr/bin/env python3
"""
opportunity_scorer.py — Revenue Opportunity Scorer

Reads CEO knowledge base outputs (Nexus briefs, equalized reports, bridged guides,
hunt syntheses, blind spots) and scores each identifiable opportunity on:
  - Market signal strength (dollar amounts, unserved segments found?)
  - Build complexity (Python script vs platform?)
  - Time to first dollar (days/weeks/months?)
  - Competitive vacuum (no existing solution found?)
  - Knowledge readiness (do we already have the data/frameworks to build?)

Outputs ranked opportunities to state/revenue/opportunities.json

Usage:
    python3 opportunity_scorer.py              # Score all opportunities
    python3 opportunity_scorer.py --top 5      # Show top 5 only
    python3 opportunity_scorer.py --verbose     # Show full reasoning
"""

import argparse
import json
import os
import sys
import glob
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
NEXUS_DIR = STATE_DIR / "nexus"
REVENUE_DIR = STATE_DIR / "revenue"
REVENUE_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from api import call_claude as _call_claude
MODEL = "claude-sonnet-4-5-20250929"


def call_claude(system: str, user: str, max_tokens: int = 8192) -> str:
    return _call_claude(system, user, model=MODEL, max_tokens=max_tokens)


def gather_inputs() -> dict:
    """Collect all relevant knowledge base outputs for scoring."""
    inputs = {}

    # 1. Latest Nexus brief
    briefs = sorted(glob.glob(str(NEXUS_DIR / "brief-*.md")))
    if briefs:
        inputs["nexus_brief"] = Path(briefs[-1]).read_text()[:6000]

    # 2. Latest emerging patterns
    emerging = sorted(glob.glob(str(NEXUS_DIR / "emerging-*.md")))
    if emerging:
        inputs["emerging_patterns"] = Path(emerging[-1]).read_text()[:6000]

    # 3. Latest connections
    connections = sorted(glob.glob(str(NEXUS_DIR / "connections-*.md")))
    if connections:
        inputs["connections"] = Path(connections[-1]).read_text()[:4000]

    # 4. Equalized reports — get unique topics (deduplicate dates)
    equalized_dir = KNOWLEDGE_DIR / "equalized"
    if equalized_dir.exists():
        # Get unique topic names
        topics = {}
        for f in sorted(equalized_dir.glob("*.md")):
            # Strip date suffix to get topic
            name = f.stem
            # Remove -YYYYMMDD suffix
            parts = name.rsplit("-2026", 1)
            topic = parts[0] if parts else name
            topics[topic] = f  # Keep latest
        
        summaries = []
        for topic, filepath in sorted(topics.items()):
            # Read first 500 chars of each unique topic
            content = filepath.read_text()[:500]
            summaries.append(f"**{topic}:**\n{content[:300]}")
        inputs["equalized_topics"] = "\n\n".join(summaries[:20])

    # 5. Bridged guides — same dedup
    bridged_dir = KNOWLEDGE_DIR / "bridged"
    if bridged_dir.exists():
        topics = {}
        for f in sorted(bridged_dir.glob("*.md")):
            parts = f.stem.rsplit("-2026", 1)
            topic = parts[0] if parts else f.stem
            topics[topic] = f
        
        summaries = []
        for topic, filepath in sorted(topics.items()):
            content = filepath.read_text()[:500]
            summaries.append(f"**{topic}:**\n{content[:300]}")
        inputs["bridged_topics"] = "\n\n".join(summaries[:20])

    # 6. Hunt syntheses (last 10)
    hunt_dir = STATE_DIR / "hunts"
    if hunt_dir.exists():
        synths = sorted(hunt_dir.glob("*-synthesis.md"), key=os.path.getmtime)[-10:]
        summaries = []
        for f in synths:
            content = f.read_text()
            # Get first line (title) + first 300 chars
            lines = content.split("\n", 1)
            title = lines[0][:120]
            body = content[:400]
            summaries.append(f"{title}\n{body}")
        inputs["recent_hunts"] = "\n\n---\n\n".join(summaries)

    # 7. Blind spots from emerging patterns (already in emerging_patterns)

    # 8. Contrarian frameworks — sample the most interesting
    contrarians = []
    for domain_dir in KNOWLEDGE_DIR.iterdir():
        if not domain_dir.is_dir() or domain_dir.name.startswith("_"):
            continue
        for f in domain_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("type", "").lower() == "contrarian":
                    contrarians.append(data.get("name", "unknown"))
            except:
                continue
    inputs["contrarian_count"] = len(contrarians)
    # Sample 30
    import random
    random.shuffle(contrarians)
    inputs["contrarian_sample"] = "\n".join(f"- {c}" for c in contrarians[:30])

    return inputs


def score_opportunities(inputs: dict, verbose: bool = False) -> list[dict]:
    """Use Claude to identify and score revenue opportunities from the knowledge base."""

    system_prompt = """You are a ruthless opportunity scorer for an autonomous AI system.

Your job: read the knowledge base outputs and identify SPECIFIC, BUILDABLE products or services 
that could generate revenue. Not strategies. Not "we should think about." PRODUCTS.

For each opportunity, score on these dimensions (1-10):

1. MARKET_SIGNAL: How strong is the evidence of paying demand?
   - 10: Dollar amounts cited, specific unserved segments with budgets
   - 5: General "there's a gap" language without specifics
   - 1: Speculative, no evidence

2. BUILD_COMPLEXITY: How hard is it to build an MVP?
   - 10: Could be built in a weekend with Python + existing data
   - 5: Needs 2-4 weeks, some external data sources, moderate complexity
   - 1: Needs a team, months of work, infrastructure

3. TIME_TO_REVENUE: How fast from build to first dollar?
   - 10: Ship → Stripe checkout → money (days)
   - 5: Needs marketing, sales cycle, or relationship building (weeks)
   - 1: Enterprise sales cycle, months of pipeline

4. COMPETITIVE_VACUUM: Is anyone else doing this?
   - 10: Research explicitly found NO existing solution
   - 5: Some competitors but clear differentiation possible
   - 1: Crowded market, major players

5. KNOWLEDGE_READINESS: Does the knowledge base already have the data to build this?
   - 10: Benchmarks, frameworks, domain knowledge all ready — just needs packaging
   - 5: Partial data, would need additional research
   - 1: Would need to start research from scratch

COMPOSITE_SCORE = (MARKET_SIGNAL * 3 + BUILD_COMPLEXITY * 2 + TIME_TO_REVENUE * 2 + COMPETITIVE_VACUUM * 1.5 + KNOWLEDGE_READINESS * 1.5) / 10

Output EXACTLY this JSON format (no other text):
{
  "opportunities": [
    {
      "id": "short-kebab-id",
      "name": "Product Name",
      "description": "One paragraph: what it is, who pays, how much",
      "market_signal": 8,
      "build_complexity": 9,
      "time_to_revenue": 7,
      "competitive_vacuum": 8,
      "knowledge_readiness": 9,
      "composite_score": 8.25,
      "reasoning": "Why this scores high/low on each dimension",
      "build_sketch": "What the MVP looks like in 3-5 bullet points",
      "revenue_model": "How it makes money",
      "knowledge_sources": ["Which knowledge base entries support this"]
    }
  ]
}

Be BRUTAL. Do not list more than 10 opportunities. Only list things that could realistically 
generate revenue within 60 days of building. If only 3 things qualify, list 3.

CRITICAL: The autonomous system that runs after you WILL ACTUALLY BUILD the top-scored item. 
Do not score anything high that you wouldn't bet $1000 on working."""

    user_prompt = f"""Here is the current state of our knowledge base. Identify and score every 
revenue opportunity you can find.

## LATEST NEXUS BRIEF (strategic analysis)
{inputs.get('nexus_brief', 'Not available')}

## EMERGING PATTERNS
{inputs.get('emerging_patterns', 'Not available')}

## CROSS-DOMAIN CONNECTIONS
{inputs.get('connections', 'Not available')}

## EQUALIZED REPORTS (democratized knowledge — benchmark data)
{inputs.get('equalized_topics', 'Not available')}

## BRIDGED GUIDES (action-ready step-by-step)
{inputs.get('bridged_topics', 'Not available')}

## RECENT HUNT SYNTHESES (deep research findings)
{inputs.get('recent_hunts', 'Not available')}

## CONTRARIAN FRAMEWORKS ({inputs.get('contrarian_count', 0)} total, sample of 30)
{inputs.get('contrarian_sample', 'Not available')}

## EXISTING SYSTEMS WE'VE BUILT
- Agent Café: Agent marketplace with 5-layer security, deployed on VPS (87.99.137.159)
- Market Intel: Momentum trading engine with Alpaca paper trading
- AgentSearch: Multi-engine search API (localhost:3939)
- CEO System: This knowledge pipeline (2,619 frameworks, 47 hunts)
- Cortex: Structured memory system
- OEE Transition Analyzer: Manufacturing analytics tool

## SKILLS AVAILABLE
- Python 3.12, full data science stack
- Web development (can deploy to VPS)
- API development (FastAPI/Flask)
- Alpaca trading API experience
- AgentSearch integration
- LLM integration (Claude API via OpenClaw)
"""

    print("🎯 Scoring opportunities against knowledge base...", flush=True)
    response = call_claude(system_prompt, user_prompt, max_tokens=8192)
    
    # Parse JSON from response
    try:
        # Try to extract JSON from response (may have markdown wrapping)
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]
        else:
            json_str = response
        
        data = json.loads(json_str.strip())
        opportunities = data.get("opportunities", [])
    except (json.JSONDecodeError, IndexError) as e:
        print(f"⚠️ Failed to parse scoring response: {e}", flush=True)
        print(f"Raw response:\n{response[:1000]}", flush=True)
        return []

    # Sort by composite score
    opportunities.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
    
    return opportunities


def save_results(opportunities: list[dict]):
    """Save scored opportunities to state."""
    output = {
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "count": len(opportunities),
        "opportunities": opportunities,
    }
    
    out_path = REVENUE_DIR / "opportunities.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\n💾 Saved {len(opportunities)} opportunities to {out_path}", flush=True)
    
    # Also write a human-readable markdown version
    md_lines = [
        f"# Revenue Opportunities — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\nScored against {2619} frameworks across CEO knowledge base.\n",
    ]
    
    for i, opp in enumerate(opportunities, 1):
        score = opp.get("composite_score", 0)
        md_lines.append(f"## #{i}: {opp.get('name', '?')} (Score: {score:.1f}/10)")
        md_lines.append(f"\n{opp.get('description', '')}\n")
        md_lines.append(f"| Dimension | Score |")
        md_lines.append(f"|-----------|-------|")
        md_lines.append(f"| Market Signal | {opp.get('market_signal', '?')}/10 |")
        md_lines.append(f"| Build Complexity | {opp.get('build_complexity', '?')}/10 |")
        md_lines.append(f"| Time to Revenue | {opp.get('time_to_revenue', '?')}/10 |")
        md_lines.append(f"| Competitive Vacuum | {opp.get('competitive_vacuum', '?')}/10 |")
        md_lines.append(f"| Knowledge Readiness | {opp.get('knowledge_readiness', '?')}/10 |")
        md_lines.append(f"\n**Reasoning:** {opp.get('reasoning', '')}\n")
        md_lines.append(f"**MVP Build:**")
        build = opp.get("build_sketch", "")
        if isinstance(build, list):
            for item in build:
                md_lines.append(f"- {item}")
        else:
            md_lines.append(build)
        md_lines.append(f"\n**Revenue Model:** {opp.get('revenue_model', '')}\n")
        md_lines.append("---\n")
    
    md_path = REVENUE_DIR / f"opportunities-{datetime.now().strftime('%Y-%m-%d')}.md"
    md_path.write_text("\n".join(md_lines))
    print(f"📄 Readable report: {md_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Score revenue opportunities from CEO knowledge base")
    parser.add_argument("--top", type=int, default=10, help="Show top N opportunities")
    parser.add_argument("--verbose", action="store_true", help="Show full reasoning")
    args = parser.parse_args()

    print("📊 Gathering knowledge base inputs...", flush=True)
    inputs = gather_inputs()
    
    print(f"   Nexus brief: {'✅' if 'nexus_brief' in inputs else '❌'}")
    print(f"   Emerging patterns: {'✅' if 'emerging_patterns' in inputs else '❌'}")
    print(f"   Connections: {'✅' if 'connections' in inputs else '❌'}")
    print(f"   Equalized topics: {'✅' if 'equalized_topics' in inputs else '❌'}")
    print(f"   Bridged guides: {'✅' if 'bridged_topics' in inputs else '❌'}")
    print(f"   Recent hunts: {'✅' if 'recent_hunts' in inputs else '❌'}")
    print(f"   Contrarians: {inputs.get('contrarian_count', 0)}", flush=True)

    opportunities = score_opportunities(inputs, verbose=args.verbose)
    
    if not opportunities:
        print("❌ No opportunities scored. Check API response.", flush=True)
        sys.exit(1)
    
    save_results(opportunities[:args.top])
    
    # Print summary
    print(f"\n{'='*70}")
    print(f"🎯 TOP {min(args.top, len(opportunities))} REVENUE OPPORTUNITIES")
    print(f"{'='*70}\n")
    
    for i, opp in enumerate(opportunities[:args.top], 1):
        score = opp.get("composite_score", 0)
        emoji = "🔥" if score >= 7.5 else "⚡" if score >= 6 else "💡"
        print(f"{emoji} #{i}: {opp.get('name', '?')} — Score: {score:.1f}/10")
        print(f"   {opp.get('description', '')[:120]}")
        if args.verbose:
            print(f"   Reasoning: {opp.get('reasoning', '')[:200]}")
        print()


if __name__ == "__main__":
    main()
