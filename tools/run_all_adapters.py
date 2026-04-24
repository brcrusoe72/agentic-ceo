#!/usr/bin/env python3
"""
Run all CEO Knowledge Adapters — consume inbox items across all 5 downstream systems.

Usage:
  python3 run_all_adapters.py scan    # Scan all inboxes, show categorization
  python3 run_all_adapters.py apply   # Apply overlays + mark consumed for all systems
  python3 run_all_adapters.py stats   # Show stats for all systems
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add tools dir to path
sys.path.insert(0, str(Path(__file__).parent))
from adapter_common import load_inbox, scan_and_categorize, mark_consumed, extract_numbers

CEO_DIR = Path(__file__).parent.parent
WORKSPACE = CEO_DIR.parent.parent

# ═══════════════════════════════════════════════════════════
# SYSTEM DEFINITIONS
# ═══════════════════════════════════════════════════════════

SYSTEMS = {
    "axelrod": {
        "inbox": WORKSPACE / "systems" / "market-intel" / "ceo_inbox",
        "overlay": WORKSPACE / "systems" / "market-intel" / "ceo_overlay.json",
        "adapter_name": "axelrod_adapter",
        "categories": {
            "momentum_params": {
                "tags": ["momentum", "backtest", "stop-loss", "trailing", "rebalancing",
                         "sharpe", "sharpe-ratio", "volatility-scaling"],
                "keywords": ["momentum", "stop-loss", "trailing stop", "sharpe", "rebalancing",
                             "lookback", "holding period", "vol-adjusted", "mean reversion"],
                "domains": ["finance", "trading"],
            },
            "risk_management": {
                "tags": ["volatility", "risk", "drawdown", "crash-protection", "hedging",
                         "market-stress", "tail-risk"],
                "keywords": ["drawdown", "max loss", "position size", "volatility", "risk",
                             "hedge", "correlation", "tail risk", "black swan", "var"],
            },
            "sector_signals": {
                "tags": ["sector", "rotation", "policy", "regulation", "tariff", "fiscal",
                         "industrial-policy"],
                "keywords": ["sector rotation", "policy impact", "regulatory", "tariff",
                             "industrial policy", "defense spending", "infrastructure"],
            },
            "edge_research": {
                "tags": ["alpha", "edge", "insider", "earnings", "pead", "congressional",
                         "information-advantage", "arbitrage"],
                "keywords": ["alpha", "edge", "signal strength", "insider", "earnings drift",
                             "congressional trading", "information advantage", "asymmetric"],
            },
            "market_structure": {
                "tags": ["market-structure", "liquidity", "market-maker", "order-flow"],
                "keywords": ["market structure", "liquidity", "spread", "market maker",
                             "order flow", "dark pool", "volatility regime"],
            },
            "behavioral_finance": {
                "tags": ["behavioral", "psychology", "bias", "sentiment", "contrarian"],
                "keywords": ["behavioral", "cognitive bias", "sentiment", "contrarian",
                             "overreaction", "anchoring", "herding", "loss aversion"],
                "domains": ["psychology"],
            },
        },
    },

    "trueaicost": {
        "inbox": CEO_DIR / "builds" / "ai-cost-calculator" / "ceo_inbox",
        "overlay": CEO_DIR / "builds" / "ai-cost-calculator" / "app" / "ceo_overlay.json",
        "adapter_name": "trueaicost_adapter",
        "categories": {
            "failure_rates": {
                "tags": ["pilot-failure", "statistics", "automation", "success-rate",
                         "scaling", "enterprise-ai"],
                "keywords": ["failure rate", "success rate", "% fail", "% succeed",
                             "deliver value", "production failure", "pilot", "scale",
                             "88% use", "33% scale", "action gap", "coordination theater"],
            },
            "cost_multipliers": {
                "tags": ["cost-optimization", "roi", "benchmarking", "data-readiness",
                         "hidden-cost", "total-cost", "pricing"],
                "keywords": ["2-3x", "multiplier", "cost overrun", "budget", "data prep",
                             "integration cost", "hidden cost", "true cost", "real cost",
                             "pricing", "cost tier", "cost range", "per-machine",
                             "pricing model", "rate tier", "rate anchor", "discount"],
            },
            "timeline_reality": {
                "tags": ["timeline", "deployment", "phase-gate", "implementation"],
                "keywords": ["months", "timeline", "delayed", "overrun", "longer than",
                             "production", "pilot to production", "deployment time"],
            },
            "risk_patterns": {
                "tags": ["risk-management", "adoption", "compliance", "governance",
                         "vendor-lock-in", "technical-debt", "differentiation"],
                "keywords": ["risk", "vendor lock", "technical debt", "governance",
                             "compliance", "change management", "organizational",
                             "commoditization", "differentiation", "monopoly", "competition"],
            },
            "roi_evidence": {
                "tags": ["roi", "value", "savings", "productivity", "automation-gains"],
                "keywords": ["roi", "return on investment", "payback", "savings",
                             "productivity gain", "automation", "efficiency"],
            },
            "architecture_patterns": {
                "tags": ["enterprise-ai", "integration", "llm", "mlops", "rag",
                         "data-pipeline"],
                "keywords": ["architecture", "multi-agent", "mcp", "protocol", "middleware",
                             "integration", "mlops", "rag", "llm", "factory model",
                             "composition", "digital twin", "iiot", "edge"],
            },
        },
    },

    "oee-tool": {
        "inbox": WORKSPACE / "oee-website" / "ceo_inbox",
        "overlay": WORKSPACE / "oee-website" / "backend" / "ceo_overlay.json",
        "adapter_name": "oee_adapter",
        "categories": {
            "oee_benchmarks": {
                "tags": ["oee", "benchmark", "world-class", "target", "kpi"],
                "keywords": ["oee", "world-class", "benchmark", "85%", "target oee",
                             "availability target", "performance target", "quality target",
                             "food and beverage", "f&b", "manufacturing benchmark"],
                "domains": ["manufacturing"],
            },
            "downtime_patterns": {
                "tags": ["downtime", "changeover", "breakdown", "maintenance", "tpm",
                         "six-big-losses", "mtbf", "mttr"],
                "keywords": ["downtime", "changeover", "breakdown", "preventive maintenance",
                             "tpm", "mtbf", "mttr", "planned stop", "unplanned stop",
                             "minor stop", "speed loss", "six big losses"],
            },
            "continuous_improvement": {
                "tags": ["lean", "six-sigma", "kaizen", "dmaic", "continuous-improvement",
                         "5s", "value-stream"],
                "keywords": ["lean", "six sigma", "kaizen", "dmaic", "5s", "value stream",
                             "bottleneck", "constraint", "toc", "theory of constraints",
                             "pareto", "root cause"],
                "domains": ["manufacturing"],
            },
            "ai_manufacturing": {
                "tags": ["ai", "machine-learning", "predictive", "analytics", "iiot",
                         "industry-4.0", "digital-twin"],
                "keywords": ["predictive maintenance", "machine learning", "ai deployment",
                             "digital twin", "iiot", "industry 4.0", "smart factory",
                             "anomaly detection"],
            },
            "food_manufacturing": {
                "tags": ["food", "cpg", "fda", "gmp", "sanitation", "canning", "packaging"],
                "keywords": ["food manufacturing", "cpg", "fda", "gmp", "sanitation",
                             "canning", "filling", "packaging", "food safety"],
                "domains": ["food", "agriculture", "food-manufacturing"],
            },
            "mes_integration": {
                "tags": ["mes", "erp", "scada", "isa-95", "opc-ua", "traksys", "historian"],
                "keywords": ["mes", "traksys", "parsec", "ignition", "wonderware",
                             "scada", "opc-ua", "isa-95", "erp integration", "data historian"],
            },
        },
    },

    "agent-cafe": {
        "inbox": WORKSPACE / "systems" / "agent-cafe" / "ceo_inbox",
        "overlay": WORKSPACE / "systems" / "agent-cafe" / "ceo_overlay.json",
        "adapter_name": "agent_cafe_adapter",
        "categories": {
            "trust_reputation": {
                "tags": ["trust", "reputation", "verification", "identity", "behavioral",
                         "credential", "attestation"],
                "keywords": ["trust", "reputation", "verification", "identity",
                             "credential", "attestation", "proof of work", "track record"],
            },
            "pricing_economics": {
                "tags": ["pricing", "marketplace", "economics", "auction", "incentive",
                         "tokenomics", "currency-systems", "agent-commerce"],
                "keywords": ["pricing", "auction", "bid", "commission", "fee structure",
                             "take rate", "unit economics", "marketplace economics",
                             "two-sided", "platform pricing", "agentic commerce",
                             "commerce", "transaction"],
            },
            "agent_evaluation": {
                "tags": ["evaluation", "quality", "benchmark", "testing", "evals"],
                "keywords": ["evaluation", "quality assurance", "benchmark", "testing",
                             "capability", "agent performance", "task completion"],
            },
            "marketplace_design": {
                "tags": ["marketplace", "platform", "network-effects", "matching",
                         "discovery", "marketplace-design"],
                "keywords": ["marketplace", "platform", "network effect", "matching",
                             "discovery", "curation", "cold start", "supply demand",
                             "liquidity", "two-sided market"],
                "domains": ["marketplace"],
            },
            "agent_architecture": {
                "tags": ["agent-architecture", "multi-agent", "agent-commerce",
                         "mcp", "a2a", "orchestration"],
                "keywords": ["multi-agent", "agent architecture", "orchestration",
                             "composition", "coordinator", "routing", "specialist",
                             "agentic", "agent chain", "delegation", "evolution"],
            },
            "protocols_standards": {
                "tags": ["oauth", "delegation", "mcp", "a2a", "gnap", "ap2",
                         "interoperability", "standardization"],
                "keywords": ["oauth", "delegation", "gnap", "ap2", "mcp", "a2a",
                             "protocol", "standard", "interoperability", "ietf",
                             "verifiable intent", "credential", "token"],
            },
            "legal_liability": {
                "tags": ["liability", "fraud-detection", "regulation", "compliance"],
                "keywords": ["liability", "fraud", "legal", "regulation", "compliance",
                             "principal-agent", "defense", "deployer", "negligence"],
            },
            "security_governance": {
                "tags": ["security", "governance", "authorization", "sandboxing", "audit",
                         "access-control", "permission"],
                "keywords": ["security", "governance", "authorization", "sandboxing",
                             "permission", "audit", "compliance", "access control",
                             "rate limiting", "abuse prevention"],
            },
            "payment_infrastructure": {
                "tags": ["payment", "stripe", "escrow", "settlement", "billing",
                         "payment-protocol", "agent-payment"],
                "keywords": ["payment", "stripe", "escrow", "settlement", "billing",
                             "refund", "dispute", "agent payment", "autonomous payment",
                             "mastercard", "visa", "fiserv", "adyen", "paypal"],
            },
        },
    },

    "consulting": {
        "inbox": WORKSPACE / "systems" / "consulting" / "ceo_inbox",
        "overlay": WORKSPACE / "systems" / "consulting" / "ceo_overlay.json",
        "adapter_name": "consulting_adapter",
        "categories": {
            "pricing_strategy": {
                "tags": ["pricing", "rate", "tier", "billing", "monetization"],
                "keywords": ["pricing", "rate", "tier", "hourly", "project", "retainer",
                             "discount", "anchor", "premium", "value-based",
                             "per-machine", "subscription", "saas", "revenue model",
                             "business model", "margin", "cogs", "close rate"],
            },
            "expert_networks": {
                "tags": ["expert-network", "consulting", "advisory"],
                "keywords": ["expert network", "glg", "alphasights", "atheneum",
                             "consulting", "advisory", "engagement", "client",
                             "seniority", "rate tier", "expert call", "domain expert"],
            },
            "packaging_delivery": {
                "tags": ["productization", "methodology", "framework", "assessment"],
                "keywords": ["productize", "package", "assessment", "methodology",
                             "framework", "workshop", "certification", "dmaic",
                             "six sigma", "deliverable", "template", "repeatable",
                             "scalable", "service ladder"],
            },
            "market_positioning": {
                "tags": ["differentiation", "competitive-analysis", "positioning",
                         "go-to-market", "branding"],
                "keywords": ["differentiation", "positioning", "competitive advantage",
                             "moat", "monopoly", "niche", "specialization",
                             "credential", "credibility", "thought leader",
                             "content", "substack", "linkedin"],
            },
            "revenue_models": {
                "tags": ["revenue", "monetization", "business-model", "saas",
                         "marketplace", "platform"],
                "keywords": ["revenue", "monetization", "recurring", "mrr", "arr",
                             "take rate", "platform", "marketplace", "freemium",
                             "conversion", "funnel", "churn", "ltv", "cac",
                             "unit economics", "network effect"],
            },
            "scaling_growth": {
                "tags": ["scaling", "growth", "acquisition", "marketing"],
                "keywords": ["scale", "growth", "acquisition", "marketing",
                             "funnel", "seo", "content marketing", "audience",
                             "cold start", "flywheel", "compounding"],
            },
        },
    },

    "geopolitical": {
        "inbox": WORKSPACE / "systems" / "geopolitical-analyst" / "ceo_inbox",
        "overlay": WORKSPACE / "systems" / "geopolitical-analyst" / "ceo_overlay.json",
        "adapter_name": "geopolitical_adapter",
        "categories": {
            "great_power": {
                "tags": ["geopolitics", "hegemony", "strategy", "competition",
                         "containment", "deterrence"],
                "keywords": ["great power", "hegemony", "multipolar", "unipolar", "china",
                             "russia", "nato", "alliance", "containment", "deterrence"],
                "domains": ["geopolitics", "military"],
            },
            "economic_warfare": {
                "tags": ["sanctions", "trade", "tariff", "economic", "financial-warfare"],
                "keywords": ["sanctions", "tariff", "trade war", "economic coercion",
                             "financial warfare", "swift", "dollar", "export controls",
                             "decoupling"],
            },
            "military_industrial": {
                "tags": ["defense", "military", "arms", "procurement", "industrial-base"],
                "keywords": ["defense industrial", "arms production", "military spending",
                             "procurement", "munitions", "shipbuilding", "aerospace"],
            },
            "resource_energy": {
                "tags": ["energy", "oil", "rare-earth", "critical-minerals", "arctic"],
                "keywords": ["energy security", "oil", "natural gas", "rare earth",
                             "critical minerals", "arctic", "shipping lanes"],
            },
            "tech_competition": {
                "tags": ["semiconductor", "ai-race", "cyber", "space", "quantum"],
                "keywords": ["ai race", "semiconductor", "chip war", "quantum",
                             "cyber warfare", "tech sovereignty"],
            },
        },
    },
}


def run_scan(system_name=None):
    """Scan one or all system inboxes."""
    targets = {system_name: SYSTEMS[system_name]} if system_name else SYSTEMS
    results = {}
    for name, cfg in targets.items():
        if not cfg["inbox"].exists():
            print(f"\n  {name}: no inbox directory at {cfg['inbox']}")
            continue
        categorized, uncategorized = scan_and_categorize(
            cfg["inbox"], cfg["categories"], name.upper()
        )
        results[name] = {"categorized": categorized, "uncategorized": uncategorized}
    return results


def run_apply(system_name=None):
    """Apply overlays for one or all systems.
    
    Systems with dedicated ceo_adapter.py files are CONSUME-ONLY here —
    the dedicated adapter writes the overlay in its own schema.
    Only systems without a dedicated adapter get overlays written here.
    """
    targets = {system_name: SYSTEMS[system_name]} if system_name else SYSTEMS
    total_consumed = 0

    # Systems with dedicated adapters — we only mark consumed, don't write overlay
    DEDICATED_ADAPTER_SYSTEMS = {"axelrod", "trueaicost", "oee-tool", "agent-cafe", "geopolitical", "consulting"}

    for name, cfg in targets.items():
        if not cfg["inbox"].exists():
            print(f"\n  {name}: no inbox directory")
            continue

        categorized, uncategorized = scan_and_categorize(
            cfg["inbox"], cfg["categories"], name.upper()
        )

        if not categorized:
            continue

        has_dedicated = name in DEDICATED_ADAPTER_SYSTEMS

        # Only write overlay for systems WITHOUT a dedicated adapter
        if not has_dedicated:
            overlay = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "ceo_knowledge_router",
                "system": name,
                "frameworks_consumed": sum(len(v) for v in categorized.values()),
                "categories": {},
            }

            for cat, items_list in categorized.items():
                overlay["categories"][cat] = {
                    "count": len(items_list),
                    "top_items": [
                        {
                            "name": it["name"],
                            "relevance": it["relevance"],
                            "confidence": it["confidence"],
                            "type": it["type"],
                            "description": it.get("description", "")[:200],
                            "source_url": it.get("source_url", ""),
                            "claims": it.get("claims", []),
                        }
                        for it in sorted(items_list, key=lambda x: -x["relevance"])[:20]
                    ],
                }

            cfg["overlay"].parent.mkdir(parents=True, exist_ok=True)
            with open(cfg["overlay"], "w") as f:
                json.dump(overlay, f, indent=2)
            print(f"\n  Wrote overlay: {cfg['overlay']}")
        else:
            print(f"\n  {name}: has dedicated adapter — skipping overlay write (consume only)")

        # Mark consumed (always — even for dedicated adapter systems)
        all_items = []
        cat_map = {}
        for cat, items_list in categorized.items():
            for it in items_list:
                all_items.append(it)
                cat_map[it.get("id", "")] = cat

        consumed = mark_consumed(all_items, cfg["adapter_name"], cat_map)
        total_consumed += consumed
        print(f"  Marked {consumed} items consumed for {name}")

    print(f"\n{'='*60}")
    print(f"  TOTAL CONSUMED ACROSS ALL SYSTEMS: {total_consumed}")
    print(f"{'='*60}")


def run_stats():
    """Show stats for all systems."""
    print(f"\n{'='*60}")
    print(f"  CEO KNOWLEDGE ADAPTER STATS")
    print(f"{'='*60}")

    for name, cfg in SYSTEMS.items():
        inbox = cfg["inbox"]
        if not inbox.exists():
            print(f"  {name:20s}: no inbox")
            continue
        total = list(inbox.glob("*.json"))
        consumed = 0
        for f in total:
            try:
                if json.loads(f.read_text()).get("consumed"):
                    consumed += 1
            except Exception:
                pass
        overlay_exists = cfg["overlay"].exists()
        print(f"  {name:20s}: {len(total):5d} total, {consumed:5d} consumed, "
              f"{len(total)-consumed:5d} pending | overlay: {'YES' if overlay_exists else 'NO'}")


def main():
    parser = argparse.ArgumentParser(description="Run all CEO Knowledge Adapters")
    parser.add_argument("action", choices=["scan", "apply", "stats"], default="stats", nargs="?")
    parser.add_argument("--system", "-s", help="Run for a single system only")
    args = parser.parse_args()

    if args.action == "scan":
        run_scan(args.system)
    elif args.action == "apply":
        run_apply(args.system)
    elif args.action == "stats":
        run_stats()


if __name__ == "__main__":
    main()
