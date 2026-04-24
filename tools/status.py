#!/usr/bin/env python3
"""
status.py — Agentic CEO Status Dashboard

Pure file-reading tool. No API calls. Shows system state instantly.

Usage:
    python3 status.py             # Full dashboard
    python3 status.py --brief     # One-line summary
    python3 status.py --costs     # Just cost breakdown
    python3 status.py --hunts     # Just hunt history
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
HUNTS_DIR = STATE_DIR / "hunts"
NEXUS_DIR = STATE_DIR / "nexus"
REPORTS_DIR = STATE_DIR / "agent-reports"

KNOWLEDGE_SUBDIRS = [
    "psychology", "procurement", "dissolved", "equalized", "bridged",
    "manufacturing", "technology", "business", "strategy", "systems",
]

META_FILES = {"_index.json", "_connections.json", "_gaps.json"}

# ── Helpers ──────────────────────────────────────────────────────────

def p(msg="", flush=True):
    print(msg, flush=flush)


def safe_json(path):
    """Read JSON file, return dict or None on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def safe_float(val):
    """Convert a value to float, stripping $ signs etc."""
    if val is None:
        return 0.0
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def count_files(directory, ext=None, exclude_patterns=None):
    """Count files in directory, optionally filtering by extension and excluding patterns."""
    d = Path(directory)
    if not d.exists():
        return 0
    exclude_patterns = exclude_patterns or []
    count = 0
    for f in d.iterdir():
        if not f.is_file():
            continue
        if ext and not f.name.endswith(ext):
            continue
        if any(pat in f.name for pat in exclude_patterns):
            continue
        count += 1
    return count


def latest_glob(pattern):
    """Return the latest file matching a glob pattern (by name sort), or None."""
    matches = sorted(glob.glob(str(pattern)))
    return Path(matches[-1]) if matches else None


def human_duration(seconds):
    """Format seconds into human-readable duration."""
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


# ── Sections ─────────────────────────────────────────────────────────

def section_running():
    """Check for running processes via lock/PID files in state/."""
    p("🔄 RUNNING PROCESSES")
    p("─" * 50)
    found = False

    if STATE_DIR.exists():
        for f in STATE_DIR.iterdir():
            if f.suffix in (".lock", ".pid") and f.is_file():
                found = True
                content = f.read_text().strip()
                pid = content if content.isdigit() else "?"
                # Check if PID is actually alive
                alive = False
                if pid != "?":
                    try:
                        os.kill(int(pid), 0)
                        alive = True
                    except (ProcessLookupError, PermissionError, ValueError):
                        pass
                status = "🟢 alive" if alive else "🔴 stale"
                name = f.stem.replace(".lock", "").replace(".pid", "")
                p(f"  {name:<25} PID {pid:<8} {status}")

        # Also check subdirs for lock files
        for sub in STATE_DIR.iterdir():
            if sub.is_dir():
                for f in sub.iterdir():
                    if f.suffix in (".lock", ".pid") and f.is_file():
                        found = True
                        content = f.read_text().strip()
                        pid = content if content.isdigit() else "?"
                        alive = False
                        if pid != "?":
                            try:
                                os.kill(int(pid), 0)
                                alive = True
                            except (ProcessLookupError, PermissionError, ValueError):
                                pass
                        status = "🟢 alive" if alive else "🔴 stale"
                        name = f"{sub.name}/{f.stem}"
                        p(f"  {name:<25} PID {pid:<8} {status}")

    if not found:
        p("  No active processes")
    p()


def section_completed_today():
    """Show agent reports from today."""
    p("✅ COMPLETED TODAY")
    p("─" * 50)

    if not REPORTS_DIR.exists():
        p("  No agent reports directory")
        p()
        return 0

    today = today_str()
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.json")):
        data = safe_json(f)
        if not data or not isinstance(data, dict):
            continue
        # Check timestamp field for today's date
        ts = data.get("timestamp", "") or data.get("completed_at", "") or data.get("date", "")
        if today in str(ts):
            reports.append(data)

    if not reports:
        p("  Nothing completed today")
        p()
        return 0

    for r in reports:
        agent = r.get("agent", r.get("type", "unknown"))
        ts = r.get("timestamp", r.get("completed_at", ""))
        duration = r.get("duration_seconds", r.get("duration", None))
        cost = r.get("cost", r.get("total_cost", 0))
        status = r.get("status", "done")

        # Extract key stats
        stats_parts = []
        if cost:
            stats_parts.append(f"${cost:.4f}")
        if duration:
            stats_parts.append(human_duration(duration))
        for key in ("frameworks_found", "sources_processed", "hunts_completed", "items"):
            if key in r:
                stats_parts.append(f"{r[key]} {key.replace('_', ' ')}")

        stats = " · ".join(stats_parts) if stats_parts else "—"
        time_part = ts.split("T")[1][:5] if "T" in str(ts) else str(ts)[-5:]
        p(f"  {'🤖 ' + agent:<28} {time_part}  {stats}")

    p()
    return len(reports)


def section_knowledge_base():
    """Count and display knowledge base contents."""
    p("📚 KNOWLEDGE BASE")
    p("─" * 50)

    # Total frameworks across all knowledge subdirs
    total_frameworks = 0
    if KNOWLEDGE_DIR.exists():
        for root, dirs, files in os.walk(KNOWLEDGE_DIR):
            for f in files:
                if f.endswith(".json") and f not in META_FILES:
                    total_frameworks += 1

    # Total hunts
    hunt_count = count_files(HUNTS_DIR, ".json", ["-synthesis", "-thinking"])

    # Barrier types
    barrier_count = 0
    barrier_file = latest_glob(KNOWLEDGE_DIR / "psychology" / "barrier_taxonomy_*.json")
    if barrier_file:
        data = safe_json(barrier_file)
        if data:
            # Count barrier types - could be top-level keys or items in a list
            if isinstance(data, list):
                barrier_count = len(data)
            elif isinstance(data, dict):
                barriers = data.get("barriers", data.get("types", data))
                barrier_count = len(barriers) if isinstance(barriers, (list, dict)) else 0

    # Playbooks
    playbook_count = 0
    playbook_file = latest_glob(KNOWLEDGE_DIR / "procurement" / "entry_playbooks_*.json")
    if playbook_file:
        data = safe_json(playbook_file)
        if data:
            if isinstance(data, list):
                playbook_count = len(data)
            elif isinstance(data, dict):
                playbooks = data.get("playbooks", data.get("entries", data))
                playbook_count = len(playbooks) if isinstance(playbooks, (list, dict)) else 0

    # Specialized knowledge counts
    dissolved = count_files(KNOWLEDGE_DIR / "dissolved")
    equalized = count_files(KNOWLEDGE_DIR / "equalized")
    bridged = count_files(KNOWLEDGE_DIR / "bridged")

    p(f"  📊 Frameworks          {total_frameworks:>5}")
    p(f"  🔍 Hunts completed     {hunt_count:>5}")
    p(f"  🧠 Barrier types       {barrier_count:>5}")
    p(f"  📖 Playbooks           {playbook_count:>5}")
    p(f"  💧 Dissolved guides    {dissolved:>5}")
    p(f"  ⚖️  Equalized reports   {equalized:>5}")
    p(f"  🌉 Bridge guides       {bridged:>5}")
    p()
    return total_frameworks


def get_hunt_files():
    """Get hunt JSON files sorted by mtime descending, excluding synthesis/thinking."""
    if not HUNTS_DIR.exists():
        return []
    hunts = []
    for f in HUNTS_DIR.glob("*.json"):
        if "-synthesis" in f.name or "-thinking" in f.name:
            continue
        hunts.append(f)
    return sorted(hunts, key=lambda f: f.stat().st_mtime, reverse=True)


def section_recent_hunts(limit=3):
    """Show last N hunts."""
    p("🔍 RECENT HUNTS")
    p("─" * 50)

    hunts = get_hunt_files()
    if not hunts:
        p("  No hunts found")
        p()
        return

    for f in hunts[:limit]:
        data = safe_json(f)
        if not data:
            continue
        question = data.get("question", data.get("query", data.get("goal", "?")))
        if len(question) > 60:
            question = question[:57] + "..."
        sources = data.get("sources_count", data.get("sources_processed", len(data.get("sources", []))))
        frameworks = data.get("frameworks_found", data.get("frameworks_count", len(data.get("frameworks", []))))
        cost = data.get("cost", data.get("total_cost", 0)) or 0
        ts = data.get("timestamp", data.get("completed_at", ""))
        date_part = str(ts)[:10] if ts else datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")

        p(f"  📌 {question}")
        p(f"     {date_part}  |  {sources} sources  |  {frameworks} frameworks  |  ${cost:.4f}")
    p()


def section_recent_nexus():
    """Show latest nexus brief and recommendation count."""
    p("🧭 NEXUS INTELLIGENCE")
    p("─" * 50)

    # Latest brief
    brief = latest_glob(NEXUS_DIR / "brief-*.md")
    if brief:
        try:
            lines = brief.read_text().splitlines()[:3]
            for line in lines:
                p(f"  {line}")
        except Exception:
            p("  (could not read brief)")
    else:
        p("  No nexus briefs yet")

    # Recommendation count
    rec_file = NEXUS_DIR / "recommendations.json"
    if rec_file.exists():
        data = safe_json(rec_file)
        if data:
            recs = data if isinstance(data, list) else data.get("recommendations", [])
            p(f"  💡 {len(recs)} pending recommendations")
    p()


def section_costs():
    """Show cost breakdown."""
    p("💰 COST TRACKING")
    p("─" * 50)

    # Hunt costs
    hunt_total = 0.0
    hunt_count = 0
    for f in get_hunt_files():
        data = safe_json(f)
        if data:
            cost = data.get("cost", data.get("total_cost", 0)) or 0
            hunt_total += safe_float(cost)
            hunt_count += 1

    # Agent report costs
    agent_total = 0.0
    agent_count = 0
    if REPORTS_DIR.exists():
        for f in REPORTS_DIR.glob("*.json"):
            data = safe_json(f)
            if data and isinstance(data, dict):
                cost = data.get("cost", data.get("total_cost", data.get("api_cost", 0))) or 0
                agent_total += safe_float(cost)
                agent_count += 1

    # Today's costs
    today = today_str()
    today_cost = 0.0
    if REPORTS_DIR.exists():
        for f in REPORTS_DIR.glob("*.json"):
            data = safe_json(f)
            if data and isinstance(data, dict):
                ts = str(data.get("timestamp", data.get("completed_at", data.get("date", ""))))
                if today in ts:
                    cost = data.get("cost", data.get("total_cost", data.get("api_cost", 0))) or 0
                    today_cost += safe_float(cost)
    for f in get_hunt_files():
        data = safe_json(f)
        if data:
            ts = str(data.get("timestamp", data.get("completed_at", "")))
            if today in ts:
                cost = data.get("cost", data.get("total_cost", 0)) or 0
                today_cost += safe_float(cost)

    p(f"  🔍 Hunt costs          ${hunt_total:>8.4f}  ({hunt_count} hunts)")
    p(f"  🤖 Agent costs         ${agent_total:>8.4f}  ({agent_count} reports)")
    p(f"  📊 Total all-time      ${hunt_total + agent_total:>8.4f}")
    p(f"  📅 Today               ${today_cost:>8.4f}")
    p()


def section_health():
    """Check system health — key directories and file counts."""
    p("🏥 SYSTEM HEALTH")
    p("─" * 50)

    checks = [
        ("CEO Root", CEO_DIR),
        ("Knowledge", KNOWLEDGE_DIR),
        ("State", STATE_DIR),
        ("Hunts", HUNTS_DIR),
        ("Nexus", NEXUS_DIR),
        ("Agent Reports", REPORTS_DIR),
        ("Psychology", KNOWLEDGE_DIR / "psychology"),
        ("Procurement", KNOWLEDGE_DIR / "procurement"),
        ("Dissolved", KNOWLEDGE_DIR / "dissolved"),
        ("Equalized", KNOWLEDGE_DIR / "equalized"),
        ("Bridged", KNOWLEDGE_DIR / "bridged"),
    ]

    for name, path in checks:
        if path.exists():
            if path.is_dir():
                files = sum(1 for f in path.iterdir() if f.is_file())
                dirs = sum(1 for f in path.iterdir() if f.is_dir())
                p(f"  ✅ {name:<20} {files:>4} files  {dirs:>3} dirs")
            else:
                p(f"  ✅ {name:<20} (file)")
        else:
            p(f"  ❌ {name:<20} MISSING")
    p()


def brief_summary():
    """One-line summary of system state."""
    frameworks = 0
    if KNOWLEDGE_DIR.exists():
        for root, dirs, files in os.walk(KNOWLEDGE_DIR):
            for f in files:
                if f.endswith(".json") and f not in META_FILES:
                    frameworks += 1

    hunts = len(get_hunt_files())
    today = today_str()
    today_count = 0
    if REPORTS_DIR.exists():
        for f in REPORTS_DIR.glob("*.json"):
            data = safe_json(f)
            if data and isinstance(data, dict):
                ts = str(data.get("timestamp", data.get("completed_at", data.get("date", ""))))
                if today in ts:
                    today_count += 1

    # Check running
    running = 0
    if STATE_DIR.exists():
        for f in STATE_DIR.rglob("*.lock"):
            running += 1
        for f in STATE_DIR.rglob("*.pid"):
            running += 1

    p(f"🧠 CEO: {frameworks} frameworks | {hunts} hunts | {today_count} completed today | {running} running")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Agentic CEO Status Dashboard")
    parser.add_argument("--brief", action="store_true", help="One-line summary")
    parser.add_argument("--costs", action="store_true", help="Cost breakdown only")
    parser.add_argument("--hunts", action="store_true", help="Hunt history only")
    args = parser.parse_args()

    if args.brief:
        brief_summary()
        return

    if args.costs:
        p()
        section_costs()
        return

    if args.hunts:
        p()
        section_recent_hunts(limit=10)
        return

    # Full dashboard
    p()
    p("╔══════════════════════════════════════════════════╗")
    p("║         🧠 AGENTIC CEO — STATUS DASHBOARD       ║")
    p(f"║         {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^40} ║")
    p("╚══════════════════════════════════════════════════╝")
    p()

    section_running()
    section_completed_today()
    section_knowledge_base()
    section_recent_hunts()
    section_recent_nexus()
    section_costs()
    section_health()


if __name__ == "__main__":
    main()
