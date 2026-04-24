#!/usr/bin/env python3
"""
Knowledge Router — The nervous system connecting CEO knowledge to all downstream systems.

Watches the CEO knowledge base for new/updated frameworks, classifies them by
which downstream system they're relevant to, and pushes them into system-specific
inboxes. Each system has its own adapter that reads its inbox and takes action.

Architecture:
  CEO Pipeline → knowledge/ → Knowledge Router → system inboxes
                                                    ├── market-intel/ceo_inbox/
                                                    ├── agent-cafe/ceo_inbox/
                                                    ├── ai-cost-calculator/ceo_inbox/
                                                    ├── oee-website/ceo_inbox/
                                                    └── geopolitical-analyst/ceo_inbox/

CLI:
  python3 knowledge_router.py route              # Route new/changed frameworks since last run
  python3 knowledge_router.py backfill           # Route ALL 2,636 frameworks (first run)
  python3 knowledge_router.py backfill --system axelrod  # Backfill one system only
  python3 knowledge_router.py status             # Show routing stats
  python3 knowledge_router.py inspect <system>   # Show what's in a system's inbox
  python3 knowledge_router.py clear <system>     # Clear a system's inbox (adapter already consumed)
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────

CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
WORKSPACE = CEO_DIR.parent.parent  # /home/brcru/.openclaw/workspace
ROUTER_DB = CEO_DIR / "state" / "knowledge_router.db"

# Ensure state dir exists
(CEO_DIR / "state").mkdir(parents=True, exist_ok=True)


# ── System Registry ───────────────────────────────────────────────────
# Maps each downstream system to:
#   - path: where its inbox lives
#   - tags: CEO knowledge tags that are relevant (weighted)
#   - domains: CEO knowledge domains that are relevant
#   - min_confidence: minimum framework confidence to route

@dataclass
class SystemTarget:
    """A downstream system that consumes CEO knowledge."""
    name: str
    inbox_path: Path
    tags: dict[str, float]        # tag → relevance weight (0-1)
    domains: set[str]             # CEO knowledge domains to watch
    min_confidence: float = 0.4   # Minimum framework confidence to route
    description: str = ""


SYSTEMS: dict[str, SystemTarget] = {
    "axelrod": SystemTarget(
        name="axelrod",
        inbox_path=WORKSPACE / "systems" / "market-intel" / "ceo_inbox",
        description="Bobby Axelrod trading system — momentum, risk, regime detection",
        min_confidence=0.4,
        domains={"finance", "economics", "strategy|finance"},
        tags={
            # Core trading
            "momentum": 1.0,
            "volatility": 1.0,
            "volatility-regime": 1.0,
            "volatility-scaling": 0.9,
            "stop-loss": 1.0,
            "trailing": 0.9,
            "backtest": 0.9,
            "sharpe": 0.9,
            "sharpe-ratio": 0.9,
            "crash-protection": 0.9,
            "momentum-crash": 0.9,
            # Portfolio management
            "rebalancing": 0.8,
            "portfolio": 0.8,
            "portfolio-construction": 0.8,
            "no-trade-bands": 0.8,
            "transaction-costs": 0.7,
            "autocorrelation": 0.7,
            # Risk
            "risk-management": 0.8,
            "algorithmic-failure": 0.9,
            "cascade-dynamics": 0.8,
            # Market structure
            "market-microstructure": 0.7,
            "trading-volume": 0.7,
            "institutional-behavior": 0.7,
            "term-structure": 0.7,
            "market-environment": 0.7,
            "market-stress": 0.8,
            # Lookback / timing
            "lookback": 0.9,
            "reversal": 0.8,
            # Broader finance
            "commodity-trading": 0.5,
            "derivatives": 0.5,
            "financial-markets": 0.5,
            "market-efficiency": 0.4,
            "price-discovery": 0.4,
        },
    ),

    "trueaicost": SystemTarget(
        name="trueaicost",
        inbox_path=WORKSPACE / "systems" / "ceo" / "builds" / "ai-cost-calculator" / "ceo_inbox",
        description="AI True Cost Calculator — enterprise AI cost modeling, risk assessment",
        min_confidence=0.5,
        domains={"ai-systems", "ai-systems|manufacturing", "ai-systems|strategy",
                 "ai-systems|technology", "strategy|ai-systems", "technology|ai-systems"},
        tags={
            # Core cost modeling
            "enterprise-ai": 1.0,
            "roi": 1.0,
            "cost-optimization": 1.0,
            "pilot-failure-rate": 1.0,
            "statistics": 0.7,
            # Implementation
            "automation": 0.8,
            "integration": 0.8,
            "deployment": 0.9,
            "data-readiness": 0.9,
            "timeline": 0.8,
            "phase-gate": 0.7,
            # Risk factors
            "adoption": 0.7,
            "scaling": 0.7,
            "compliance": 0.6,
            "governance": 0.6,
            "vendor-lock-in": 0.9,
            "technical-debt": 0.9,
            # Market positioning
            "differentiation": 0.6,
            "pricing": 0.7,
            "benchmarking": 0.7,
            "competitive-analysis": 0.7,
            # AI-specific
            "llm": 0.8,
            "inference": 0.8,
            "fine-tuning": 0.7,
            "mlops": 0.8,
            "data-pipeline": 0.7,
            "model-selection": 0.7,
            "prompt-engineering": 0.6,
            "rag": 0.7,
        },
    ),

    "oee-tool": SystemTarget(
        name="oee-tool",
        inbox_path=WORKSPACE / "oee-website" / "ceo_inbox",
        description="OEE Benchmarking tool — manufacturing analytics, performance benchmarks",
        min_confidence=0.5,
        domains={"manufacturing", "manufacturing|strategy", "manufacturing|technology",
                 "manufacturing|finance", "manufacturing|ai-systems", "food-manufacturing",
                 "food-operations", "operations"},
        tags={
            # Core OEE
            "oee": 1.0,
            "benchmarking": 1.0,
            "root-cause-analysis": 0.9,
            "quality-control": 0.9,
            "six-sigma": 0.9,
            "lean": 0.8,
            # Manufacturing
            "data-architecture": 0.8,
            "computer-vision": 0.7,
            "data-portability": 0.7,
            "plc": 0.8,
            "scada": 0.7,
            "mes": 0.8,
            # Operations
            "downtime": 0.9,
            "utilization": 0.9,
            "throughput": 0.9,
            "cycle-time": 0.8,
            "changeover": 0.8,
            "scheduling": 0.7,
            # Food-specific
            "food-safety": 0.6,
            "supply-chain": 0.6,
            "traceability": 0.6,
            # Performance
            "waste-reduction": 0.8,
            "efficiency": 0.8,
            "capex-justification": 0.7,
        },
    ),

    "agent-cafe": SystemTarget(
        name="agent-cafe",
        inbox_path=WORKSPACE / "systems" / "agent-cafe" / "ceo_inbox",
        description="Agent Café marketplace — trust, security, agent commerce, platform design",
        min_confidence=0.5,
        domains={"marketplace-design", "platform-scaling", "trust-mechanisms",
                 "fintech", "sales-psychology"},
        tags={
            # Core marketplace
            "agent-commerce": 1.0,
            "agent-identity": 1.0,
            "agent-architecture": 0.9,
            "multi-agent": 0.9,
            "marketplace-design": 1.0,
            "platform-strategy": 0.9,
            "platform-scaling": 0.8,
            # Trust & security
            "trust": 0.9,
            "trust-mechanisms": 0.9,
            "governance": 0.8,
            "liability": 0.8,
            "security": 0.8,
            "fraud-detection": 0.9,
            "verifiable-credentials": 0.8,
            # Auth & identity
            "delegation": 0.7,
            "authorization": 0.7,
            "authentication": 0.7,
            "oauth": 0.7,
            "ap2": 0.6,
            "mcp": 0.7,
            # Economics
            "pricing": 0.7,
            "tokenization": 0.6,
            "staking": 0.6,
            "stripe": 0.6,
            "economics": 0.5,
            # Standards
            "open-standard": 0.6,
            "interoperability": 0.6,
            "standardization": 0.5,
            "cryptography": 0.5,
        },
    ),

    "consulting": SystemTarget(
        name="consulting",
        inbox_path=WORKSPACE / "systems" / "consulting" / "ceo_inbox",
        description="Consulting & revenue intelligence — pricing, expert networks, packaging, positioning",
        min_confidence=0.3,
        domains={"strategy", "business", "consulting", "economics"},
        tags={
            # Pricing
            "pricing": 1.0,
            "monetization": 1.0,
            "revenue": 1.0,
            "business-model": 1.0,
            "saas": 0.9,
            "subscription": 0.9,
            "marketplace": 0.8,
            # Consulting
            "consulting": 1.0,
            "advisory": 0.9,
            "expert-network": 1.0,
            "methodology": 0.9,
            "assessment": 0.9,
            "certification": 0.8,
            "workshop": 0.8,
            # Positioning
            "differentiation": 0.9,
            "competitive-analysis": 0.8,
            "positioning": 0.9,
            "branding": 0.7,
            "thought-leadership": 0.8,
            "go-to-market": 0.9,
            # Growth
            "scaling": 0.7,
            "growth": 0.8,
            "acquisition": 0.7,
            "funnel": 0.8,
            "content-marketing": 0.8,
            "network-effects": 0.7,
        },
    ),

    "geopolitical": SystemTarget(
        name="geopolitical",
        inbox_path=WORKSPACE / "systems" / "geopolitical-analyst" / "ceo_inbox",
        description="Geopolitical risk assessment tool",
        min_confidence=0.6,
        domains={"contrarian", "economics"},
        tags={
            "geopolitics": 1.0,
            "trade-policy": 0.9,
            "tariff": 0.9,
            "sanctions": 0.9,
            "supply-chain": 0.7,
            "reshoring": 0.8,
            "national-security": 0.8,
            "china": 0.8,
            "regulation": 0.6,
            "government-policy": 0.7,
            "defense": 0.6,
            "energy-security": 0.7,
        },
    ),
}


# ── Routing Engine ────────────────────────────────────────────────────

@dataclass
class RouteResult:
    """Result of routing a single framework to a system."""
    framework_id: str
    framework_name: str
    framework_domain: str
    system: str
    relevance_score: float     # 0-1, how relevant this framework is to the system
    matched_tags: list[str]    # Which tags matched
    domain_match: bool         # Did the domain match?
    confidence: float          # Framework's own confidence
    routed_at: str


def score_framework_for_system(
    framework: dict,
    system: SystemTarget,
) -> Optional[RouteResult]:
    """Score how relevant a framework is to a specific system.
    
    Returns RouteResult if relevant enough, None if not.
    """
    fw_id = framework.get("id", "unknown")
    fw_name = framework.get("name", framework.get("description", ""))[:100]
    fw_confidence = framework.get("confidence", 0.5)
    fw_tags = set(t.lower() for t in framework.get("tags", []))
    fw_domain = framework.get("domain", "")
    
    # Skip low-confidence frameworks
    if fw_confidence < system.min_confidence:
        return None
    
    # Score based on tag matches (weighted)
    tag_score = 0.0
    matched_tags = []
    for tag in fw_tags:
        if tag in system.tags:
            weight = system.tags[tag]
            tag_score += weight
            matched_tags.append(tag)
    
    # Normalize tag score (max possible = sum of matched weights)
    if matched_tags:
        tag_score = tag_score / max(len(matched_tags), 1)  # Average weight of matched tags
    
    # Domain match bonus
    domain_match = False
    # Check both exact domain and any parent domain (e.g., "finance" matches "strategy|finance")
    for sys_domain in system.domains:
        if fw_domain == sys_domain or fw_domain in sys_domain.split("|") or sys_domain in fw_domain.split("|"):
            domain_match = True
            break
    
    domain_bonus = 0.2 if domain_match else 0.0
    
    # Combined relevance score
    relevance = 0.0
    if matched_tags:
        relevance = tag_score * 0.7 + domain_bonus + fw_confidence * 0.1
    elif domain_match:
        relevance = domain_bonus + fw_confidence * 0.1
    
    # Threshold: must have at least one tag match OR strong domain match
    if relevance < 0.15 or (not matched_tags and not domain_match):
        return None
    
    relevance = min(1.0, relevance)
    
    return RouteResult(
        framework_id=fw_id,
        framework_name=fw_name,
        framework_domain=fw_domain,
        system=system.name,
        relevance_score=round(relevance, 3),
        matched_tags=matched_tags,
        domain_match=domain_match,
        confidence=fw_confidence,
        routed_at=datetime.now(timezone.utc).isoformat(),
    )


def load_all_frameworks() -> list[tuple[str, dict]]:
    """Load all frameworks from CEO knowledge base.
    Returns list of (relative_path, framework_dict).
    """
    frameworks = []
    for domain_dir in sorted(KNOWLEDGE_DIR.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith("_"):
            continue
        for f in sorted(domain_dir.iterdir()):
            if not f.suffix == ".json":
                continue
            try:
                data = json.loads(f.read_text())
                rel_path = f"{domain_dir.name}/{f.name}"
                # Inject domain from directory if not in the framework
                if "domain" not in data or not data["domain"]:
                    data["domain"] = domain_dir.name.split("|")[0]
                frameworks.append((rel_path, data))
            except (json.JSONDecodeError, OSError):
                pass
    return frameworks


def load_changed_frameworks(since_ts: Optional[str] = None) -> list[tuple[str, dict]]:
    """Load only frameworks changed since a given timestamp.
    Falls back to loading all if no timestamp given.
    """
    if not since_ts:
        return load_all_frameworks()
    
    try:
        cutoff = datetime.fromisoformat(since_ts).timestamp()
    except:
        return load_all_frameworks()
    
    frameworks = []
    for domain_dir in sorted(KNOWLEDGE_DIR.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith("_"):
            continue
        for f in sorted(domain_dir.iterdir()):
            if not f.suffix == ".json":
                continue
            # Check modification time
            if f.stat().st_mtime <= cutoff:
                continue
            try:
                data = json.loads(f.read_text())
                rel_path = f"{domain_dir.name}/{f.name}"
                if "domain" not in data or not data["domain"]:
                    data["domain"] = domain_dir.name.split("|")[0]
                frameworks.append((rel_path, data))
            except (json.JSONDecodeError, OSError):
                pass
    return frameworks


# ── Database (routing history + state) ────────────────────────────────

def init_db(conn: sqlite3.Connection):
    """Create routing tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS route_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            framework_id TEXT,
            framework_path TEXT,
            framework_name TEXT,
            system TEXT,
            relevance_score REAL,
            matched_tags TEXT,       -- JSON list
            domain_match INTEGER,
            confidence REAL,
            routed_at TEXT,
            consumed INTEGER DEFAULT 0,
            consumed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS route_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_route_system ON route_log(system);
        CREATE INDEX IF NOT EXISTS idx_route_framework ON route_log(framework_id);
        CREATE INDEX IF NOT EXISTS idx_route_consumed ON route_log(consumed);
    """)
    conn.commit()


def get_state(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM route_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str):
    conn.execute("INSERT OR REPLACE INTO route_state (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


# ── Inbox Writing ─────────────────────────────────────────────────────

def write_to_inbox(result: RouteResult, framework: dict, framework_path: str):
    """Write a routed framework to the target system's inbox."""
    system = SYSTEMS.get(result.system)
    if not system:
        return
    
    inbox = system.inbox_path
    inbox.mkdir(parents=True, exist_ok=True)
    
    # Write an enriched copy with routing metadata
    envelope = {
        "routing": {
            "routed_at": result.routed_at,
            "relevance_score": result.relevance_score,
            "matched_tags": result.matched_tags,
            "domain_match": result.domain_match,
            "source_path": framework_path,
        },
        "framework": framework,
    }
    
    filename = f"{result.framework_id}.json"
    (inbox / filename).write_text(json.dumps(envelope, indent=2))


# ── Core Route Function ──────────────────────────────────────────────

def route_frameworks(
    frameworks: list[tuple[str, dict]],
    systems_filter: Optional[list[str]] = None,
    write_inboxes: bool = True,
    verbose: bool = False,
) -> dict[str, list[RouteResult]]:
    """Route frameworks to all relevant systems.
    
    Returns dict of system_name → list of RouteResults.
    """
    conn = sqlite3.connect(str(ROUTER_DB))
    init_db(conn)
    
    results: dict[str, list[RouteResult]] = defaultdict(list)
    total_routes = 0
    
    target_systems = {k: v for k, v in SYSTEMS.items()
                      if not systems_filter or k in systems_filter}
    
    for fw_path, fw_data in frameworks:
        fw_id = fw_data.get("id", "unknown")
        
        for sys_name, sys_target in target_systems.items():
            result = score_framework_for_system(fw_data, sys_target)
            if result is None:
                continue
            
            results[sys_name].append(result)
            total_routes += 1
            
            # Log to database
            conn.execute("""
                INSERT INTO route_log
                (framework_id, framework_path, framework_name, system,
                 relevance_score, matched_tags, domain_match, confidence, routed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fw_id, fw_path, result.framework_name, sys_name,
                result.relevance_score, json.dumps(result.matched_tags),
                1 if result.domain_match else 0, result.confidence,
                result.routed_at,
            ))
            
            # Write to inbox
            if write_inboxes:
                write_to_inbox(result, fw_data, fw_path)
            
            if verbose:
                print(f"  → {sys_name:15s} [{result.relevance_score:.2f}] {result.framework_name[:60]}")
    
    # Update last-run timestamp
    set_state(conn, "last_route_at", datetime.now(timezone.utc).isoformat())
    conn.commit()
    conn.close()
    
    return results


# ── CLI Commands ──────────────────────────────────────────────────────

def cmd_route(args):
    """Route new/changed frameworks since last run."""
    conn = sqlite3.connect(str(ROUTER_DB))
    init_db(conn)
    last_run = get_state(conn, "last_route_at")
    conn.close()
    
    if last_run:
        print(f"  Loading frameworks changed since {last_run}...")
        frameworks = load_changed_frameworks(since_ts=last_run)
    else:
        print("  No previous run found. Use 'backfill' for initial routing.")
        print("  Running incremental route on recent files (last 24h)...")
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        frameworks = load_changed_frameworks(since_ts=cutoff)
    
    if not frameworks:
        print("  No new/changed frameworks to route.")
        return
    
    print(f"  Found {len(frameworks)} frameworks to route...")
    
    systems_filter = [args.system] if hasattr(args, 'system') and args.system else None
    results = route_frameworks(frameworks, systems_filter=systems_filter, verbose=args.verbose)
    
    print(f"\n  Routing complete:")
    total = 0
    for sys_name, routes in sorted(results.items()):
        print(f"    {sys_name:15s}: {len(routes):4d} frameworks routed")
        total += len(routes)
    print(f"    {'TOTAL':15s}: {total:4d}")


def cmd_backfill(args):
    """Route ALL frameworks (first run or reset)."""
    print(f"  Loading all frameworks from {KNOWLEDGE_DIR}...")
    frameworks = load_all_frameworks()
    print(f"  Found {len(frameworks)} total frameworks")
    
    systems_filter = [args.system] if hasattr(args, 'system') and args.system else None
    if systems_filter:
        print(f"  Filtering to system: {systems_filter[0]}")
    
    # Clear existing inbox contents for targeted systems
    targets = systems_filter or list(SYSTEMS.keys())
    for sys_name in targets:
        inbox = SYSTEMS[sys_name].inbox_path
        if inbox.exists():
            cleared = 0
            for f in inbox.glob("*.json"):
                f.unlink()
                cleared += 1
            if cleared:
                print(f"  Cleared {cleared} files from {sys_name} inbox")
    
    results = route_frameworks(frameworks, systems_filter=systems_filter, verbose=args.verbose)
    
    print(f"\n  Backfill complete:")
    total = 0
    for sys_name, routes in sorted(results.items()):
        top_3 = sorted(routes, key=lambda r: r.relevance_score, reverse=True)[:3]
        print(f"    {sys_name:15s}: {len(routes):4d} frameworks")
        for r in top_3:
            print(f"      [{r.relevance_score:.2f}] {r.framework_name[:65]}")
        total += len(routes)
    print(f"    {'TOTAL':15s}: {total:4d}")


def cmd_status(args):
    """Show routing statistics."""
    conn = sqlite3.connect(str(ROUTER_DB))
    init_db(conn)
    
    last_run = get_state(conn, "last_route_at")
    
    print(f"\n{'='*80}")
    print(f"  KNOWLEDGE ROUTER STATUS")
    print(f"{'='*80}")
    print(f"\n  Last route: {last_run or 'never'}")
    
    # Total frameworks available
    frameworks = load_all_frameworks()
    print(f"  Total CEO frameworks: {len(frameworks)}")
    
    # Per-system stats
    print(f"\n  System Routing Stats:")
    print(f"  {'System':15s} {'Routed':>8s} {'Consumed':>10s} {'Inbox':>8s} {'Top Score':>10s}")
    print(f"  {'─'*55}")
    
    for sys_name, sys_target in SYSTEMS.items():
        routed = conn.execute(
            "SELECT COUNT(*) FROM route_log WHERE system = ?", (sys_name,)
        ).fetchone()[0]
        
        consumed = conn.execute(
            "SELECT COUNT(*) FROM route_log WHERE system = ? AND consumed = 1", (sys_name,)
        ).fetchone()[0]
        
        top_score = conn.execute(
            "SELECT MAX(relevance_score) FROM route_log WHERE system = ?", (sys_name,)
        ).fetchone()[0] or 0
        
        # Count inbox files
        inbox_count = 0
        if sys_target.inbox_path.exists():
            inbox_count = len(list(sys_target.inbox_path.glob("*.json")))
        
        print(f"  {sys_name:15s} {routed:8d} {consumed:10d} {inbox_count:8d} {top_score:10.3f}")
    
    # Tag coverage
    print(f"\n  Tag Coverage (all systems combined):")
    all_tags = set()
    for sys in SYSTEMS.values():
        all_tags.update(sys.tags.keys())
    
    # Count how many frameworks match any registered tag
    matched = 0
    for _, fw in frameworks:
        fw_tags = set(t.lower() for t in fw.get("tags", []))
        if fw_tags & all_tags:
            matched += 1
    
    coverage = matched / len(frameworks) * 100 if frameworks else 0
    print(f"  {matched}/{len(frameworks)} frameworks match at least one system tag ({coverage:.1f}%)")
    
    # Unmatched domains (knowledge we're ignoring)
    routed_domains = set()
    for _, fw in frameworks:
        fw_tags = set(t.lower() for t in fw.get("tags", []))
        if fw_tags & all_tags:
            routed_domains.add(fw.get("domain", "unknown"))
    
    all_domains = set(fw.get("domain", "unknown") for _, fw in frameworks)
    unrouted = all_domains - routed_domains
    if unrouted:
        print(f"\n  ⚠️  Unrouted domains (no system consumes these):")
        for d in sorted(unrouted):
            count = sum(1 for _, fw in frameworks if fw.get("domain") == d)
            print(f"    {d:40s} {count:4d} frameworks")
    
    conn.close()
    print()


def cmd_inspect(args):
    """Show contents of a system's inbox."""
    sys_name = args.system
    if sys_name not in SYSTEMS:
        print(f"  Unknown system '{sys_name}'. Available: {', '.join(SYSTEMS.keys())}")
        return
    
    inbox = SYSTEMS[sys_name].inbox_path
    if not inbox.exists():
        print(f"  No inbox for {sys_name} (not yet created)")
        return
    
    files = sorted(inbox.glob("*.json"))
    print(f"\n  Inbox for {sys_name}: {len(files)} items")
    print(f"  Path: {inbox}\n")
    
    if not files:
        print("  (empty)")
        return
    
    # Sort by relevance score
    items = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            routing = data.get("routing", {})
            fw = data.get("framework", {})
            items.append({
                "file": f.name,
                "relevance": routing.get("relevance_score", 0),
                "tags": routing.get("matched_tags", []),
                "name": fw.get("name", fw.get("description", ""))[:70],
                "confidence": fw.get("confidence", 0),
                "type": fw.get("type", "?"),
            })
        except:
            pass
    
    items.sort(key=lambda x: x["relevance"], reverse=True)
    
    limit = args.limit if hasattr(args, 'limit') else 30
    for item in items[:limit]:
        print(f"  [{item['relevance']:.2f}|{item['confidence']:.1f}] {item['name']}")
        print(f"        type={item['type']} tags={item['tags'][:5]}")
    
    if len(items) > limit:
        print(f"\n  ... {len(items) - limit} more items")


def cmd_clear(args):
    """Clear a system's inbox."""
    sys_name = args.system
    if sys_name not in SYSTEMS:
        print(f"  Unknown system '{sys_name}'. Available: {', '.join(SYSTEMS.keys())}")
        return
    
    inbox = SYSTEMS[sys_name].inbox_path
    if not inbox.exists():
        print(f"  No inbox for {sys_name}")
        return
    
    files = list(inbox.glob("*.json"))
    for f in files:
        f.unlink()
    
    print(f"  Cleared {len(files)} items from {sys_name} inbox")
    
    # Mark as consumed in DB
    conn = sqlite3.connect(str(ROUTER_DB))
    init_db(conn)
    conn.execute(
        "UPDATE route_log SET consumed = 1, consumed_at = ? WHERE system = ? AND consumed = 0",
        (datetime.now(timezone.utc).isoformat(), sys_name)
    )
    conn.commit()
    conn.close()


# ── Pipeline Hook ─────────────────────────────────────────────────────

def post_pipeline_hook():
    """Called after CEO pipeline completes. Routes any new frameworks."""
    conn = sqlite3.connect(str(ROUTER_DB))
    init_db(conn)
    last_run = get_state(conn, "last_route_at")
    conn.close()
    
    frameworks = load_changed_frameworks(since_ts=last_run)
    if not frameworks:
        return 0
    
    results = route_frameworks(frameworks)
    total = sum(len(routes) for routes in results.values())
    
    if total > 0:
        summary_parts = []
        for sys_name, routes in results.items():
            if routes:
                summary_parts.append(f"{sys_name}:{len(routes)}")
        print(f"  📡 Knowledge Router: {total} frameworks routed ({', '.join(summary_parts)})")
    
    return total


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Knowledge Router — CEO knowledge → downstream systems",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")
    
    # route
    p_route = sub.add_parser("route", help="Route new/changed frameworks")
    p_route.add_argument("--system", type=str, help="Route to specific system only")
    p_route.add_argument("--verbose", "-v", action="store_true")
    
    # backfill
    p_backfill = sub.add_parser("backfill", help="Route ALL frameworks (initial run)")
    p_backfill.add_argument("--system", type=str, help="Backfill specific system only")
    p_backfill.add_argument("--verbose", "-v", action="store_true")
    
    # status
    p_status = sub.add_parser("status", help="Show routing stats")
    
    # inspect
    p_inspect = sub.add_parser("inspect", help="Show system inbox contents")
    p_inspect.add_argument("system", type=str, help="System name")
    p_inspect.add_argument("--limit", type=int, default=30)
    
    # clear
    p_clear = sub.add_parser("clear", help="Clear system inbox")
    p_clear.add_argument("system", type=str, help="System name")
    
    args = parser.parse_args()
    
    if args.command == "route":
        cmd_route(args)
    elif args.command == "backfill":
        cmd_backfill(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "clear":
        cmd_clear(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
