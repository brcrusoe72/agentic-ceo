#!/usr/bin/env python3
"""
Knowledge Tracker — Feedback loop from downstream systems to CEO Director.

Records which frameworks get consumed, applied, or ignored by each system.
Produces a report the Director agent can read to prioritize future hunts.

Architecture:
  System adapters → mark consumed → knowledge_tracker.py
       ↓
  Tracker → "Your most impactful domain: manufacturing (12 applied)"
       ↓
  Director → hunts more manufacturing, less philosophy

CLI:
  python3 knowledge_tracker.py record <system> <framework_id> <action>  # Record consumption
  python3 knowledge_tracker.py report           # Impact report for Director
  python3 knowledge_tracker.py report --json    # JSON for Director agent
  python3 knowledge_tracker.py stats            # Raw statistics
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
TRACKER_DB = CEO_DIR / "state" / "knowledge_tracker.db"
ROUTER_DB = CEO_DIR / "state" / "knowledge_router.db"

(CEO_DIR / "state").mkdir(parents=True, exist_ok=True)


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS consumption_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            framework_id TEXT,
            system TEXT,
            action TEXT,       -- applied, ignored, queued, flagged_conflict
            parameter TEXT,    -- which parameter was affected (if applicable)
            old_value TEXT,    -- what it was before
            new_value TEXT,    -- what it became
            notes TEXT,
            recorded_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_cons_system ON consumption_log(system);
        CREATE INDEX IF NOT EXISTS idx_cons_framework ON consumption_log(framework_id);
        CREATE INDEX IF NOT EXISTS idx_cons_action ON consumption_log(action);
    """)
    conn.commit()


def record(system: str, framework_id: str, action: str,
           parameter: str = "", old_value: str = "", new_value: str = "",
           notes: str = ""):
    """Record a framework consumption event."""
    conn = sqlite3.connect(str(TRACKER_DB))
    init_db(conn)
    conn.execute("""
        INSERT INTO consumption_log
        (framework_id, system, action, parameter, old_value, new_value, notes, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (framework_id, system, action, parameter, old_value, new_value, notes,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_director_report() -> dict:
    """Generate a report for the Director agent.
    
    Answers: what domains should we hunt more? What's being used vs ignored?
    """
    conn = sqlite3.connect(str(TRACKER_DB))
    init_db(conn)
    
    # What systems are consuming?
    system_stats = {}
    for row in conn.execute("""
        SELECT system, action, COUNT(*) FROM consumption_log
        GROUP BY system, action ORDER BY system, COUNT(*) DESC
    """).fetchall():
        if row[0] not in system_stats:
            system_stats[row[0]] = {}
        system_stats[row[0]][row[1]] = row[2]
    
    # What parameters are being changed?
    param_changes = conn.execute("""
        SELECT system, parameter, COUNT(*) FROM consumption_log
        WHERE action = 'applied' AND parameter != ''
        GROUP BY system, parameter ORDER BY COUNT(*) DESC
    """).fetchall()
    
    conn.close()
    
    # Cross-reference with router data to find domain effectiveness
    domain_effectiveness = {}
    try:
        rconn = sqlite3.connect(str(ROUTER_DB))
        # Frameworks that were routed
        routed = rconn.execute("""
            SELECT framework_id, system, relevance_score FROM route_log
        """).fetchall()
        
        # Build framework → domain map from route log
        fw_domains = {}
        for row in rconn.execute("""
            SELECT DISTINCT framework_id, framework_path FROM route_log
        """).fetchall():
            path = row[1] or ""
            domain = path.split("/")[0] if "/" in path else "unknown"
            fw_domains[row[0]] = domain
        
        rconn.close()
        
        # Count routed vs consumed by domain
        tconn = sqlite3.connect(str(TRACKER_DB))
        init_db(tconn)
        consumed_fws = set()
        for row in tconn.execute("SELECT DISTINCT framework_id FROM consumption_log WHERE action = 'applied'").fetchall():
            consumed_fws.add(row[0])
        tconn.close()
        
        domain_routed = defaultdict(int)
        domain_consumed = defaultdict(int)
        for fw_id, domain in fw_domains.items():
            domain_routed[domain] += 1
            if fw_id in consumed_fws:
                domain_consumed[domain] += 1
        
        for domain in domain_routed:
            routed_ct = domain_routed[domain]
            consumed_ct = domain_consumed.get(domain, 0)
            domain_effectiveness[domain] = {
                "routed": routed_ct,
                "consumed": consumed_ct,
                "rate": round(consumed_ct / max(routed_ct, 1), 3),
            }
    except:
        pass
    
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system_consumption": system_stats,
        "parameter_changes": [
            {"system": r[0], "parameter": r[1], "count": r[2]}
            for r in param_changes
        ],
        "domain_effectiveness": domain_effectiveness,
        "recommendation": _generate_recommendation(system_stats, domain_effectiveness),
    }


def _generate_recommendation(system_stats: dict, domain_eff: dict) -> str:
    """Generate a plain-text recommendation for the Director."""
    parts = []
    
    # Most active systems
    total_applied = 0
    for sys, actions in system_stats.items():
        applied = actions.get("applied", 0)
        total_applied += applied
        if applied > 0:
            parts.append(f"{sys} applied {applied} frameworks")
    
    if total_applied == 0:
        return ("No frameworks have been consumed yet. Systems have inboxes populated "
                "but adapters haven't run 'apply' yet. This is expected on first deployment.")
    
    # Most effective domains
    if domain_eff:
        top_domains = sorted(domain_eff.items(), key=lambda x: x[1]["rate"], reverse=True)[:3]
        if top_domains:
            domain_parts = [f"{d} ({info['rate']:.0%} consumption rate)" for d, info in top_domains]
            parts.append(f"Most impactful domains: {', '.join(domain_parts)}")
        
        # Least effective (wasted research)
        bottom = [d for d, info in domain_eff.items() if info["rate"] == 0 and info["routed"] >= 10]
        if bottom:
            parts.append(f"Low-impact domains (routed but never consumed): {', '.join(bottom[:5])}")
    
    return ". ".join(parts) + "."


def cmd_record(args):
    """Record a consumption event."""
    record(args.system, args.framework_id, args.action,
           parameter=args.parameter or "", notes=args.notes or "")
    print(f"  Recorded: {args.system} {args.action} {args.framework_id}")


def cmd_report(args):
    """Impact report for Director."""
    report = get_director_report()
    
    if args.json:
        print(json.dumps(report, indent=2))
        return
    
    print(f"\n{'='*80}")
    print(f"  KNOWLEDGE IMPACT REPORT (for Director)")
    print(f"{'='*80}\n")
    
    # System consumption
    print(f"  System Consumption:")
    for sys, actions in report["system_consumption"].items():
        total = sum(actions.values())
        applied = actions.get("applied", 0)
        ignored = actions.get("ignored", 0)
        print(f"    {sys:15s}: {total} total ({applied} applied, {ignored} ignored)")
    
    # Parameter changes
    if report["parameter_changes"]:
        print(f"\n  Parameter Changes:")
        for pc in report["parameter_changes"][:10]:
            print(f"    {pc['system']:15s} → {pc['parameter']:25s} ({pc['count']}x)")
    
    # Domain effectiveness
    if report["domain_effectiveness"]:
        print(f"\n  Domain Effectiveness:")
        for domain, info in sorted(report["domain_effectiveness"].items(),
                                     key=lambda x: -x[1]["rate"])[:10]:
            rate_bar = "█" * int(info["rate"] * 10) + "░" * (10 - int(info["rate"] * 10))
            print(f"    {domain:30s} {rate_bar} {info['rate']:.0%} ({info['consumed']}/{info['routed']})")
    
    # Recommendation
    print(f"\n  💡 Director Recommendation:")
    print(f"     {report['recommendation']}")
    print()


def cmd_stats(args):
    """Raw statistics."""
    conn = sqlite3.connect(str(TRACKER_DB))
    init_db(conn)
    
    total = conn.execute("SELECT COUNT(*) FROM consumption_log").fetchone()[0]
    print(f"\n  Knowledge Tracker: {total} total events")
    
    if total == 0:
        print("  (no consumption events recorded yet)")
        conn.close()
        return
    
    for row in conn.execute("""
        SELECT system, action, COUNT(*) FROM consumption_log
        GROUP BY system, action ORDER BY COUNT(*) DESC
    """).fetchall():
        print(f"    {row[0]:15s} {row[1]:15s} {row[2]}")
    
    conn.close()
    print()


def main():
    parser = argparse.ArgumentParser(description="Knowledge Tracker")
    sub = parser.add_subparsers(dest="command")
    
    p_record = sub.add_parser("record", help="Record consumption event")
    p_record.add_argument("system", type=str)
    p_record.add_argument("framework_id", type=str)
    p_record.add_argument("action", choices=["applied", "ignored", "queued", "flagged_conflict"])
    p_record.add_argument("--parameter", type=str, default="")
    p_record.add_argument("--notes", type=str, default="")
    
    p_report = sub.add_parser("report", help="Director impact report")
    p_report.add_argument("--json", action="store_true")
    
    sub.add_parser("stats", help="Raw statistics")
    
    args = parser.parse_args()
    
    if args.command == "record": cmd_record(args)
    elif args.command == "report": cmd_report(args)
    elif args.command == "stats": cmd_stats(args)
    else: parser.print_help()


if __name__ == "__main__":
    main()
