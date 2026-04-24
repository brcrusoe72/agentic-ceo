#!/usr/bin/env python3
"""
spec_writer.py — Autonomous Spec Writer

Takes the top-scored opportunity from opportunity_scorer.py and writes a 
BUILDABLE technical specification. Not a strategy doc — an actual spec that 
the Builder agent (or a sub-agent) can execute.

The spec includes:
  - Data model / schema
  - API endpoints or CLI interface
  - User flow (if web-facing)
  - MVP scope (what's in v1, what's not)
  - File structure
  - Dependencies
  - Deployment plan
  - Revenue integration (Stripe, etc.)
  - Test plan
  - Estimated build time

Usage:
    python3 spec_writer.py                    # Spec the #1 opportunity
    python3 spec_writer.py --opportunity 2    # Spec the #2 opportunity
    python3 spec_writer.py --id "oee-bench"   # Spec by opportunity ID
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
REVENUE_DIR = STATE_DIR / "revenue"
SPECS_DIR = REVENUE_DIR / "specs"
SPECS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from api import call_claude as _call_claude
MODEL = "claude-sonnet-4-5-20250929"


def call_claude(system: str, user: str, max_tokens: int = 12000) -> str:
    return _call_claude(system, user, model=MODEL, max_tokens=max_tokens)


def load_opportunity(rank: int = 1, opp_id: str = None) -> dict | None:
    """Load a scored opportunity."""
    opp_path = REVENUE_DIR / "opportunities.json"
    if not opp_path.exists():
        print("❌ No scored opportunities found. Run opportunity_scorer.py first.", flush=True)
        return None
    
    data = json.loads(opp_path.read_text())
    opportunities = data.get("opportunities", [])
    
    if not opportunities:
        print("❌ No opportunities in file.", flush=True)
        return None
    
    if opp_id:
        for opp in opportunities:
            if opp.get("id") == opp_id:
                return opp
        print(f"❌ Opportunity ID '{opp_id}' not found.", flush=True)
        return None
    
    if rank > len(opportunities):
        print(f"❌ Only {len(opportunities)} opportunities, requested #{rank}.", flush=True)
        return None
    
    return opportunities[rank - 1]


def gather_domain_knowledge(opportunity: dict) -> str:
    """Pull relevant knowledge base content for the opportunity."""
    knowledge_parts = []
    
    sources = opportunity.get("knowledge_sources", [])
    description = opportunity.get("description", "").lower()
    name = opportunity.get("name", "").lower()
    
    # Heuristic: determine which knowledge domains are relevant
    relevant_dirs = []
    keywords = {
        "restaurant": ["restaurant-operations", "restaurant-strategy", "food-operations"],
        "oee": ["manufacturing", "manufacturing|strategy", "manufacturing|technology"],
        "manufacturing": ["manufacturing", "manufacturing|strategy", "manufacturing|ai-systems"],
        "government": ["procurement", "regulatory"],
        "food": ["food-manufacturing", "food-systems", "food-science", "supply-chain"],
        "agent": ["ai-systems", "marketplace-design", "trust-mechanisms", "finance"],
        "consulting": ["strategy", "leadership", "sales-psychology"],
    }
    
    for keyword, dirs in keywords.items():
        if keyword in description or keyword in name:
            relevant_dirs.extend(dirs)
    
    # Also check equalized and bridged
    for keyword in ["restaurant", "oee", "manufacturing", "food", "government", "agent"]:
        if keyword in description or keyword in name:
            # Pull matching equalized reports
            eq_dir = KNOWLEDGE_DIR / "equalized"
            if eq_dir.exists():
                for f in eq_dir.glob("*.md"):
                    if keyword in f.stem.lower():
                        content = f.read_text()[:2000]
                        knowledge_parts.append(f"### Equalized: {f.stem}\n{content}")
                        if len(knowledge_parts) > 8:
                            break
            
            # Pull matching bridged guides
            br_dir = KNOWLEDGE_DIR / "bridged"
            if br_dir.exists():
                for f in br_dir.glob("*.md"):
                    if keyword in f.stem.lower():
                        content = f.read_text()[:2000]
                        knowledge_parts.append(f"### Bridged: {f.stem}\n{content}")
                        if len(knowledge_parts) > 12:
                            break
    
    # Pull some framework samples from relevant domains
    for dirname in set(relevant_dirs):
        domain_dir = KNOWLEDGE_DIR / dirname
        if domain_dir.exists():
            frameworks = list(domain_dir.glob("*.json"))[:5]
            for f in frameworks:
                try:
                    data = json.loads(f.read_text())
                    name_fw = data.get("name", "?")
                    fw_type = data.get("type", "?")
                    desc = data.get("description", data.get("content", ""))[:300]
                    knowledge_parts.append(f"### Framework [{fw_type}]: {name_fw}\n{desc}")
                except:
                    continue
    
    return "\n\n".join(knowledge_parts[:20])


def write_spec(opportunity: dict, domain_knowledge: str) -> str:
    """Generate a buildable technical specification."""
    
    system_prompt = """You are a senior engineer writing a technical specification that an autonomous 
AI agent will use to BUILD a working product. This is not a proposal. This is a BUILD DOCUMENT.

Requirements:
1. Every file that needs to be created must be listed with its path
2. Data models must include actual field names and types
3. API endpoints must include request/response shapes
4. The spec must be executable top-to-bottom — no "TBD" sections
5. Include exact pip dependencies
6. Include deployment commands
7. Include a revenue integration plan (Stripe checkout, API key gating, etc.)

The builder agent has access to:
- Python 3.12 with any pip packages
- A VPS at 87.99.137.159 (SSH access, Docker available)
- AgentSearch API at localhost:3939 for any research during build
- Claude API via OpenClaw gateway
- Alpaca trading API
- The CEO knowledge base (2,619 frameworks of domain data)

Write the spec in markdown. Be precise. Be complete. The builder should be able to 
execute this without asking questions.

CRITICAL CONSTRAINTS:
- MVP must be buildable in under 40 hours of agent time
- Must have a working revenue path (even if it's just a Stripe checkout page)
- Must be deployable (not just a local script)
- Must use data that already exists in the knowledge base where possible
- No vaporware features — only what can ship in v1"""

    user_prompt = f"""Write a complete technical specification for this product:

## OPPORTUNITY
**Name:** {opportunity.get('name', '?')}
**Description:** {opportunity.get('description', '?')}
**Score:** {opportunity.get('composite_score', '?')}/10
**Revenue Model:** {opportunity.get('revenue_model', '?')}

**Build Sketch from Scorer:**
{json.dumps(opportunity.get('build_sketch', ''), indent=2)}

**Scorer's Reasoning:**
{opportunity.get('reasoning', '')}

## RELEVANT DOMAIN KNOWLEDGE FROM CEO KNOWLEDGE BASE
{domain_knowledge}

## DEPLOYMENT TARGET
- VPS: 87.99.137.159 (Hetzner, Docker available)
- Domain: Can use a subdomain or raw IP for MVP
- Already running: Agent Café (port 8000), AgentSearch (port 3939)

Write the full spec now. Include file-by-file breakdown, data models, API routes, 
deployment plan, and revenue integration."""

    print("📝 Writing technical specification...", flush=True)
    return call_claude(system_prompt, user_prompt, max_tokens=12000)


def main():
    parser = argparse.ArgumentParser(description="Write buildable spec from scored opportunity")
    parser.add_argument("--opportunity", type=int, default=1, help="Opportunity rank (1=top)")
    parser.add_argument("--id", type=str, default=None, help="Opportunity ID")
    args = parser.parse_args()

    # Load opportunity
    opp = load_opportunity(rank=args.opportunity, opp_id=args.id)
    if not opp:
        sys.exit(1)
    
    print(f"\n🎯 Speccing: {opp.get('name', '?')} (Score: {opp.get('composite_score', '?')}/10)")
    print(f"   {opp.get('description', '')[:150]}\n")

    # Gather domain knowledge
    print("📚 Pulling relevant domain knowledge...", flush=True)
    domain_knowledge = gather_domain_knowledge(opp)
    print(f"   Gathered {len(domain_knowledge)} chars of domain context", flush=True)

    # Write spec
    spec_content = write_spec(opp, domain_knowledge)
    
    # Save
    opp_id = opp.get("id", f"opp-{args.opportunity}")
    spec_path = SPECS_DIR / f"spec-{opp_id}.md"
    
    # Add metadata header
    full_spec = f"""---
opportunity_id: {opp_id}
opportunity_name: {opp.get('name', '?')}
composite_score: {opp.get('composite_score', '?')}
generated_at: {datetime.now(timezone.utc).isoformat()}
status: ready_to_build
---

{spec_content}
"""
    
    spec_path.write_text(full_spec)
    print(f"\n💾 Spec saved to: {spec_path}")
    print(f"📏 Spec length: {len(full_spec):,} chars")
    
    # Update opportunity status
    opp_path = REVENUE_DIR / "opportunities.json"
    if opp_path.exists():
        data = json.loads(opp_path.read_text())
        for o in data.get("opportunities", []):
            if o.get("id") == opp_id:
                o["status"] = "spec_written"
                o["spec_path"] = str(spec_path)
                o["spec_written_at"] = datetime.now(timezone.utc).isoformat()
        opp_path.write_text(json.dumps(data, indent=2))
    
    print(f"\n✅ Spec ready for Builder agent: {spec_path}")
    print(f"   Next: python3 builder.py --spec {spec_path}")


if __name__ == "__main__":
    main()
