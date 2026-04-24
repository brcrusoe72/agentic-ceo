#!/usr/bin/env python3
"""
CEO Knowledge Cleanup & Enhancement
1. Archive low-relevance items (< 0.3 score) from all inboxes
2. Widen adapter categories to catch high-relevance unconsumed items
3. Build consulting/revenue system adapter
4. Re-run all adapters to consume the good stuff
"""

import json
import os
import shutil
import sqlite3
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone

WORKSPACE = Path(__file__).parent.parent.parent.parent
CEO_DIR = WORKSPACE / "systems" / "ceo"
ARCHIVE_DIR = CEO_DIR / "archive" / "low-relevance"
ROUTER_DB = CEO_DIR / "state" / "knowledge_router.db"

INBOXES = {
    "axelrod": WORKSPACE / "systems" / "market-intel" / "ceo_inbox",
    "trueaicost": CEO_DIR / "builds" / "ai-cost-calculator" / "ceo_inbox",
    "oee-tool": WORKSPACE / "oee-website" / "ceo_inbox",
    "agent-cafe": WORKSPACE / "systems" / "agent-cafe" / "ceo_inbox",
    "geopolitical": WORKSPACE / "systems" / "geopolitical-analyst" / "ceo_inbox",
}


def archive_low_relevance():
    """Move items with relevance < 0.3 AND not consumed by any system to archive."""
    db = sqlite3.connect(str(ROUTER_DB))
    db.row_factory = sqlite3.Row

    # Get all consumed framework IDs (by any system)
    consumed_ids = set()
    for row in db.execute("SELECT DISTINCT framework_id FROM route_log WHERE consumed=1"):
        consumed_ids.add(row["framework_id"])

    # Get low-relevance items
    low_rel = {}
    for row in db.execute("SELECT framework_id, framework_name, system, relevance_score FROM route_log WHERE consumed=0 AND relevance_score < 0.3"):
        fid = row["framework_id"]
        if fid not in consumed_ids:
            if fid not in low_rel:
                low_rel[fid] = {"name": row["framework_name"], "systems": [], "score": row["relevance_score"]}
            low_rel[fid]["systems"].append(row["system"])

    print(f"\n{'='*60}")
    print(f"  ARCHIVING LOW-RELEVANCE ITEMS (score < 0.3, unconsumed)")
    print(f"{'='*60}")
    print(f"  Found {len(low_rel)} unique frameworks to archive")

    # Create archive directory
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    archived = 0
    archived_per_system = Counter()

    for system, inbox_path in INBOXES.items():
        if not inbox_path.exists():
            continue
        system_archive = ARCHIVE_DIR / system
        system_archive.mkdir(parents=True, exist_ok=True)

        for f in inbox_path.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                fw = data.get("framework", {})
                fid = fw.get("id", "")

                if fid in low_rel and not data.get("consumed"):
                    # Move to archive
                    shutil.move(str(f), str(system_archive / f.name))
                    archived += 1
                    archived_per_system[system] += 1
            except Exception as e:
                continue

    # Mark archived items in DB
    for fid in low_rel:
        db.execute("UPDATE route_log SET consumed=1, consumed_at=? WHERE framework_id=? AND consumed=0 AND relevance_score < 0.3",
                   (datetime.now(timezone.utc).isoformat(), fid))
    db.commit()
    db.close()

    print(f"  Archived {archived} files:")
    for sys, count in archived_per_system.most_common():
        print(f"    {sys}: {count}")
    print(f"  Archive location: {ARCHIVE_DIR}")
    return archived


def get_high_relevance_unconsumed():
    """Get high-relevance (>=0.3) unconsumed items per system."""
    db = sqlite3.connect(str(ROUTER_DB))
    db.row_factory = sqlite3.Row

    results = {}
    for system in INBOXES:
        rows = db.execute(
            "SELECT framework_id, framework_name, relevance_score, matched_tags "
            "FROM route_log WHERE system=? AND consumed=0 AND relevance_score >= 0.3 "
            "ORDER BY relevance_score DESC",
            (system,)
        ).fetchall()
        results[system] = rows

    db.close()
    return results


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"

    if cmd == "report":
        remaining = get_high_relevance_unconsumed()
        print(f"\n{'='*60}")
        print(f"  HIGH-RELEVANCE UNCONSUMED (score >= 0.3)")
        print(f"{'='*60}")
        for system, rows in remaining.items():
            print(f"\n  {system}: {len(rows)} items")
            for r in rows[:5]:
                print(f"    [{r['relevance_score']:.2f}] {r['framework_name'][:70]}")
            if len(rows) > 5:
                print(f"    ... and {len(rows)-5} more")

    elif cmd == "archive":
        archived = archive_low_relevance()
        remaining = get_high_relevance_unconsumed()
        total = sum(len(v) for v in remaining.values())
        print(f"\n  After archive: {total} high-relevance items remain to be consumed")

    elif cmd == "full":
        # Archive + report
        archived = archive_low_relevance()
        remaining = get_high_relevance_unconsumed()
        total = sum(len(v) for v in remaining.values())
        print(f"\n  After archive: {total} high-relevance items remain to be consumed")
        print(f"  Next step: run enhanced adapters to consume these")
