#!/usr/bin/env python3
"""
orchestrator.py — Runs the full Agentic CEO cycle.

Coordinates all agents in the correct order:
  1. Director plans (reads state, sets missions)
  2. Scout discovers (finds new content based on missions + gaps)
  3. Analyst ingests (processes queued sources)
  4. Librarian organizes (indexes, finds connections, identifies gaps)
  5. Critic reviews (challenges high-confidence frameworks)

Usage:
    python3 orchestrator.py                 # Full daily cycle
    python3 orchestrator.py --phase plan    # Just Director planning
    python3 orchestrator.py --phase discover # Just Scout
    python3 orchestrator.py --phase ingest   # Just Analyst (process queue)
    python3 orchestrator.py --phase organize # Just Librarian
    python3 orchestrator.py --phase critique # Just Critic
    python3 orchestrator.py --quick          # Scout + Analyst only (fast cycle)
    python3 orchestrator.py --status         # Show system state
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
TOOLS_DIR = CEO_DIR / "tools"
STATE_DIR = CEO_DIR / "state"
KNOWLEDGE_DIR = CEO_DIR / "knowledge"


def run_agent(name: str, script: str, args: list[str] = None) -> bool:
    """Run an agent script and return success/failure."""
    script_path = TOOLS_DIR / script
    if not script_path.exists():
        print(f"  ❌ {name}: {script} not found")
        return False

    cmd = [sys.executable, str(script_path)] + (args or [])
    print(f"\n{'='*60}")
    print(f"🤖 Running {name}...")
    print(f"{'='*60}")

    start = datetime.now()
    result = subprocess.run(cmd, cwd=str(CEO_DIR))
    elapsed = (datetime.now() - start).total_seconds()

    if result.returncode == 0:
        print(f"  ✅ {name} completed in {elapsed:.1f}s")
        return True
    else:
        print(f"  ❌ {name} failed (exit {result.returncode}) after {elapsed:.1f}s")
        return False


def show_status():
    """Display current system state."""
    print("\n📊 AGENTIC CEO — System Status")
    print("=" * 60)

    # Knowledge base stats
    index_path = KNOWLEDGE_DIR / "_index.json"
    if index_path.exists():
        idx = json.loads(index_path.read_text())
        total = idx.get("total_frameworks", 0)
        domains = idx.get("domains", {})
        print(f"\n📚 Knowledge Base: {total} frameworks")
        for domain, count in sorted(domains.items(), key=lambda x: -x[1]):
            print(f"   {domain}: {count}")
    else:
        print("\n📚 Knowledge Base: empty")

    # Source queue
    queue_path = STATE_DIR / "source-queue.json"
    if queue_path.exists():
        q = json.loads(queue_path.read_text())
        queued = len(q.get("queued", []))
        print(f"\n📋 Source Queue: {queued} pending")
        for item in q.get("queued", [])[:5]:
            print(f"   [{item.get('priority', '?')}] {item.get('title', item.get('url', '?'))}")

    # Missions
    missions_path = STATE_DIR / "missions.json"
    if missions_path.exists():
        m = json.loads(missions_path.read_text())
        focus = m.get("focus", "No focus set")
        missions = m.get("missions", [])
        pending = [x for x in missions if x.get("status") == "pending"]
        print(f"\n🎯 Director Focus: {focus}")
        print(f"   Missions: {len(pending)} pending / {len(missions)} total")

    # Gaps
    gaps_path = KNOWLEDGE_DIR / "_gaps.json"
    if gaps_path.exists():
        g = json.loads(gaps_path.read_text())
        gaps = g.get("gaps", []) if isinstance(g, dict) else g
        print(f"\n🕳️  Knowledge Gaps: {len(gaps)}")
        for gap in gaps[:3]:
            print(f"   [{gap.get('priority', '?')}] {gap.get('description', '?')[:80]}")

    # Ingest log
    log_path = STATE_DIR / "ingest-log.json"
    if log_path.exists():
        log = json.loads(log_path.read_text())
        print(f"\n💰 Total ingested: {log.get('total_ingested', 0)} sources")
        print(f"   Total frameworks: {log.get('total_frameworks', 0)}")
        print(f"   Total cost: ${log.get('total_cost', 0):.4f}")

    # Recent agent reports
    reports_dir = STATE_DIR / "agent-reports"
    if reports_dir.exists():
        reports = sorted(reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if reports:
            print(f"\n📝 Recent Agent Reports:")
            for r in reports[:5]:
                try:
                    data = json.loads(r.read_text())
                    agent = data.get("agent", r.stem)
                    ts = data.get("timestamp", "?")
                    print(f"   {agent} — {ts}")
                except Exception:
                    print(f"   {r.name}")

    print(f"\n{'='*60}")


def run_hunts():
    """Execute hunts assigned by the Director."""
    missions_path = STATE_DIR / "missions.json"
    if not missions_path.exists():
        return {}

    missions = json.loads(missions_path.read_text())
    hunts = missions.get("hunts", [])
    results = {}

    if not hunts:
        print("\n🎯 No hunts assigned by Director")
        return results

    for hunt in hunts:
        question = hunt.get("question", "")
        budget = hunt.get("budget", 2.0)
        max_sources = hunt.get("max_sources", 50)
        max_depth = hunt.get("max_depth", 3)
        priority = hunt.get("priority", "medium")

        if not question:
            continue

        print(f"\n{'='*60}")
        print(f"🏹 HUNT [{priority.upper()}]: {question[:70]}")
        print(f"   Budget: ${budget:.2f} | Sources: {max_sources} | Depth: {max_depth}")
        print(f"{'='*60}")

        args = [question, "--budget", str(budget), "--sources", str(max_sources), "--depth", str(max_depth)]
        results[f"hunt:{question[:40]}"] = run_agent(f"Hunter → {question[:50]}", "hunter.py", args)

    return results


def full_cycle():
    """Run the complete daily cycle."""
    print("🧠 AGENTIC CEO — Full Daily Cycle")
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    results = {}

    # 1. Director plans (assigns hunts + missions)
    results["director"] = run_agent("Director", "director.py")

    # 2. Execute Director-assigned hunts (the core intelligence gathering)
    hunt_results = run_hunts()
    results.update(hunt_results)

    # 3. Scout discovers additional sources
    results["scout"] = run_agent("Scout", "scout.py")

    # 4. Analyst ingests queued sources (from Scout)
    queue_path = STATE_DIR / "source-queue.json"
    if queue_path.exists():
        q = json.loads(queue_path.read_text())
        queued = q.get("queued", [])
        if queued:
            high = [x for x in queued if x.get("priority") == "high"][:5]
            medium = [x for x in queued if x.get("priority") == "medium"][:3]
            to_process = high + medium

            for item in to_process:
                url = item.get("url", "")
                domain = item.get("domain_hint", "")
                args = [url]
                if domain:
                    args += ["--domain", domain]
                results[f"analyst:{url[:50]}"] = run_agent(
                    f"Analyst → {item.get('title', url)[:40]}",
                    "analyst.py",
                    args
                )

                q["queued"] = [x for x in q["queued"] if x.get("url") != url]
                q.setdefault("completed", []).append({**item, "processed_at": datetime.now(timezone.utc).isoformat()})

            queue_path.write_text(json.dumps(q, indent=2))
        else:
            print("\n📋 Source queue empty — nothing to ingest")

    # 5. Librarian organizes (reindex only — no O(n²) connection scan)
    results["librarian"] = run_agent("Librarian", "librarian.py", ["--reindex"])

    # 6. Critic reviews
    results["critic"] = run_agent("Critic", "critic.py")

    # 7. Self-improvement analysis (if evolve.py exists)
    evolve_path = TOOLS_DIR / "evolve.py"
    if evolve_path.exists():
        results["evolve"] = run_agent("Evolve (self-analysis)", "evolve.py", ["--metrics"])

    # Summary
    print(f"\n{'='*60}")
    print("📊 CYCLE COMPLETE")
    print(f"{'='*60}")
    succeeded = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    print(f"  ✅ {succeeded} succeeded")
    if failed:
        print(f"  ❌ {failed} failed")
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")


def main():
    parser = argparse.ArgumentParser(description="Agentic CEO Orchestrator")
    parser.add_argument("--phase", choices=["plan", "discover", "ingest", "organize", "critique"],
                        help="Run a single phase")
    parser.add_argument("--quick", action="store_true", help="Quick cycle: scout + ingest only")
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument("--hunt", help="Launch a hunt with a research question")
    parser.add_argument("--budget", type=float, help="Hunt budget in dollars")
    parser.add_argument("--sources", type=int, help="Max sources for hunt")
    parser.add_argument("--depth", type=int, help="Max recursion depth for hunt")
    parser.add_argument("--url", help="Ingest a specific URL immediately")
    parser.add_argument("--domain", help="Domain hint for --url")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.hunt:
        hunt_args = [args.hunt, "--budget", str(args.budget or 2.0),
                     "--sources", str(args.sources or 50), "--depth", str(args.depth or 3)]
        run_agent("Hunter", "hunter.py", hunt_args)
        run_agent("Librarian", "librarian.py", ["--reindex"])
        return

    if args.url:
        ingest_args = [args.url]
        if args.domain:
            ingest_args += ["--domain", args.domain]
        run_agent("Analyst", "analyst.py", ingest_args)
        run_agent("Librarian", "librarian.py", ["--reindex"])
        return

    if args.phase:
        phase_map = {
            "plan": ("Director", "director.py", []),
            "discover": ("Scout", "scout.py", []),
            "ingest": ("Analyst", "analyst.py", []),  # processes queue
            "organize": ("Librarian", "librarian.py", []),
            "critique": ("Critic", "critic.py", []),
        }
        name, script, extra_args = phase_map[args.phase]
        run_agent(name, script, extra_args)
        return

    if args.quick:
        run_agent("Scout", "scout.py")
        # Then ingest top queued items
        run_agent("Analyst", "analyst.py")
        return

    full_cycle()


if __name__ == "__main__":
    main()
