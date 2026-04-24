#!/usr/bin/env python3
"""
sentinel.py — The Immune System

Checks system health. Detects failures. Auto-heals what it can.
No LLM needed for most checks — pure logic.

Usage:
    python3 sentinel.py              # Full health check
    python3 sentinel.py --heal       # Check + auto-fix
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
CONFIG_DIR = CEO_DIR / "config"
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
IMMUNE_DIR = STATE_DIR / "immune"
IMMUNE_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from events import log_event, today_events, read_events_since

P = lambda *a, **kw: print(*a, **kw, flush=True)


def check_agentsearch() -> dict:
    """Is AgentSearch alive?"""
    import requests
    try:
        r = requests.get("http://localhost:3939/health", timeout=10)
        if r.ok:
            data = r.json()
            return {"status": "healthy", "detail": data}
        return {"status": "degraded", "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"status": "down", "detail": str(e)}


def check_api_key() -> dict:
    """Is the Anthropic key valid?"""
    auth_path = Path.home() / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
    if not auth_path.exists():
        return {"status": "missing", "detail": "auth-profiles.json not found"}
    try:
        data = json.loads(auth_path.read_text())
        for name, prof in data.get("profiles", {}).items():
            if "anthropic" in name and prof.get("token"):
                return {"status": "healthy", "detail": "key present"}
        return {"status": "missing", "detail": "no anthropic profile found"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_knowledge_base() -> dict:
    """Is the KB growing? Any corruption?"""
    if not KNOWLEDGE_DIR.exists():
        return {"status": "empty", "detail": "knowledge directory missing"}

    total = 0
    corrupt = 0
    domains = {}
    for json_file in KNOWLEDGE_DIR.rglob("*.json"):
        total += 1
        domain = json_file.parent.name
        domains[domain] = domains.get(domain, 0) + 1
        try:
            json.loads(json_file.read_text())
        except (json.JSONDecodeError, Exception):
            corrupt += 1

    status = "healthy" if corrupt == 0 else "degraded" if corrupt < total * 0.05 else "critical"
    return {
        "status": status,
        "total_frameworks": total,
        "corrupt_files": corrupt,
        "domains": len(domains),
        "top_domains": dict(sorted(domains.items(), key=lambda x: -x[1])[:5]),
    }


def check_config_integrity() -> dict:
    """Are all config files valid JSON?"""
    issues = []
    for cfg_file in CONFIG_DIR.glob("*.json"):
        try:
            json.loads(cfg_file.read_text())
        except json.JSONDecodeError as e:
            issues.append(f"{cfg_file.name}: {e}")

    return {
        "status": "healthy" if not issues else "degraded",
        "issues": issues,
    }


def check_disk_space() -> dict:
    """Enough disk space?"""
    try:
        stat = os.statvfs(str(CEO_DIR))
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        total_gb = (stat.f_blocks * stat.f_frsize) / (1024 ** 3)
        pct_free = free_gb / total_gb * 100
        status = "healthy" if pct_free > 10 else "degraded" if pct_free > 5 else "critical"
        return {"status": status, "free_gb": round(free_gb, 1), "pct_free": round(pct_free, 1)}
    except Exception as e:
        return {"status": "unknown", "detail": str(e)}


def check_recent_activity() -> dict:
    """Has the system been active recently?"""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    events = read_events_since(yesterday)

    if not events:
        return {"status": "stale", "detail": "no events in 24h"}

    agent_activity = {}
    for e in events:
        agent = e.get("agent", "unknown")
        agent_activity[agent] = agent_activity.get(agent, 0) + 1

    return {
        "status": "healthy",
        "events_24h": len(events),
        "active_agents": agent_activity,
    }


def check_cost_budget() -> dict:
    """Are we within budget?"""
    budget_config = CONFIG_DIR / "budget-config.json"
    if not budget_config.exists():
        return {"status": "unknown", "detail": "no budget config"}

    config = json.loads(budget_config.read_text())
    daily_cap = config.get("daily_cap_usd", 1.00)

    from events import cost_today as get_cost
    spent = get_cost()
    pct_used = spent / daily_cap * 100 if daily_cap > 0 else 0

    status = "healthy" if pct_used < 80 else "warning" if pct_used < 100 else "exceeded"
    return {
        "status": status,
        "spent_today": round(spent, 4),
        "daily_cap": daily_cap,
        "pct_used": round(pct_used, 1),
    }


# ---------------------------------------------------------------------------
# Healing
# ---------------------------------------------------------------------------

def heal_agentsearch() -> bool:
    """Try to restart AgentSearch containers."""
    P("   🔧 Attempting to restart AgentSearch...")
    try:
        result = subprocess.run(
            ["sudo", "docker-compose", "up", "-d"],
            cwd=str(Path.home() / ".openclaw" / "workspace" / "agent-search"),
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            P("   ✅ AgentSearch containers restarted")
            log_event("sentinel", "healed", {"target": "agentsearch", "action": "docker-compose up -d"})
            return True
        P(f"   ❌ Failed: {result.stderr[:200]}")
    except Exception as e:
        P(f"   ❌ Failed: {e}")
    return False


def heal_corrupt_files() -> int:
    """Remove corrupt JSON files from knowledge base."""
    removed = 0
    for json_file in KNOWLEDGE_DIR.rglob("*.json"):
        try:
            json.loads(json_file.read_text())
        except (json.JSONDecodeError, Exception):
            P(f"   🗑️ Removing corrupt: {json_file.name}")
            json_file.unlink()
            removed += 1
    if removed:
        log_event("sentinel", "healed", {"target": "knowledge_base", "corrupt_removed": removed})
    return removed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def health_check(heal: bool = False) -> dict:
    """Run all health checks."""
    P("\n" + "=" * 60)
    P("🛡️ SENTINEL — System Health Check")
    P("=" * 60 + "\n")

    checks = {
        "agentsearch": check_agentsearch(),
        "api_key": check_api_key(),
        "knowledge_base": check_knowledge_base(),
        "config_integrity": check_config_integrity(),
        "disk_space": check_disk_space(),
        "recent_activity": check_recent_activity(),
        "cost_budget": check_cost_budget(),
    }

    # Print results
    overall = "healthy"
    for name, result in checks.items():
        status = result.get("status", "unknown")
        emoji = {
            "healthy": "🟢", "degraded": "🟡", "warning": "🟡",
            "down": "🔴", "critical": "🔴", "exceeded": "🔴",
            "missing": "🔴", "stale": "🟡", "empty": "🟡",
        }.get(status, "⚪")
        P(f"   {emoji} {name}: {status}")

        # Track worst status
        if status in ("down", "critical", "exceeded", "missing"):
            overall = "critical"
        elif status in ("degraded", "warning", "stale", "empty") and overall != "critical":
            overall = "degraded"

    P(f"\n   Overall: {'🟢' if overall == 'healthy' else '🟡' if overall == 'degraded' else '🔴'} {overall}")

    # Auto-heal if requested
    if heal:
        P("\n🔧 Auto-heal enabled:")
        if checks["agentsearch"].get("status") == "down":
            heal_agentsearch()
        if checks["knowledge_base"].get("corrupt_files", 0) > 0:
            heal_corrupt_files()

    # Save health state
    health = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "checks": checks,
    }
    health_file = IMMUNE_DIR / "health.json"
    health_file.write_text(json.dumps(health, indent=2))

    log_event("sentinel", "health_check", {"overall": overall, "checks": len(checks)})

    P("\n" + "=" * 60)
    P("🛡️ SENTINEL COMPLETE")
    P("=" * 60)

    return health


def main():
    parser = argparse.ArgumentParser(description="Sentinel — System Health")
    parser.add_argument("--heal", action="store_true", help="Auto-heal detected issues")
    args = parser.parse_args()

    health_check(heal=args.heal)


if __name__ == "__main__":
    main()
