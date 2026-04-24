#!/usr/bin/env python3
"""
events.py — The Nervous System

Append-only event log. Every agent writes here. Observer reads here.
This is how the system knows what happened.

Usage:
    from events import log_event, read_events, read_events_since, today_events, agent_events

    # Write
    log_event("hunter", "hunt_complete", {"hunt_id": "abc", "sources": 15, "frameworks": 64, "cost": 0.31})
    log_event("observer", "scored_hunt", {"hunt_id": "abc", "signal_ratio": 0.73})
    log_event("sentinel", "health_check", {"status": "healthy", "degraded": []})

    # Read
    events = today_events()
    hunter_events = agent_events("hunter", days=7)
    recent = read_events_since("2026-03-05T00:00:00Z")
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
EVENTS_FILE = STATE_DIR / "events.jsonl"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def log_event(agent: str, event_type: str, data: dict = None, cost: float = None) -> dict:
    """Append an event to the log. Returns the event dict."""
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "event": event_type,
    }
    if data:
        event["data"] = data
    if cost is not None:
        event["cost"] = cost

    with open(EVENTS_FILE, "a") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")

    return event


def read_events(limit: int = None) -> list[dict]:
    """Read all events, optionally limited to last N."""
    if not EVENTS_FILE.exists():
        return []
    events = []
    with open(EVENTS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if limit:
        return events[-limit:]
    return events


def read_events_since(iso_timestamp: str) -> list[dict]:
    """Read events since a given ISO timestamp."""
    events = read_events()
    return [e for e in events if e.get("ts", "") >= iso_timestamp]


def today_events() -> list[dict]:
    """Read today's events."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return read_events_since(f"{today}T00:00:00")


def agent_events(agent: str, days: int = 1) -> list[dict]:
    """Read events for a specific agent within the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    events = read_events_since(cutoff)
    return [e for e in events if e.get("agent") == agent]


def event_summary(days: int = 1) -> dict:
    """Quick summary of recent events."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    events = read_events_since(cutoff)

    summary = {
        "total_events": len(events),
        "by_agent": {},
        "by_type": {},
        "total_cost": 0.0,
    }

    for e in events:
        agent = e.get("agent", "unknown")
        etype = e.get("event", "unknown")
        cost = e.get("cost", 0) or 0

        summary["by_agent"][agent] = summary["by_agent"].get(agent, 0) + 1
        summary["by_type"][etype] = summary["by_type"].get(etype, 0) + 1
        summary["total_cost"] += cost

    return summary


def cost_today() -> float:
    """Total cost logged today."""
    events = today_events()
    return sum(e.get("cost", 0) or 0 for e in events)


def cost_check(agent: str, proposed_cost: float) -> tuple[bool, str]:
    """Check if an agent can spend this much. Returns (allowed, reason)."""
    config_path = CEO_DIR / "config" / "budget-config.json"
    if not config_path.exists():
        return True, "no budget config"

    config = json.loads(config_path.read_text())
    daily_cap = config.get("daily_cap_usd", 1.00)
    agent_cap = config.get("per_agent_caps", {}).get(agent, daily_cap)

    # Check daily total
    spent_today = cost_today()
    if spent_today + proposed_cost > daily_cap:
        return False, f"daily cap exceeded: ${spent_today:.2f} + ${proposed_cost:.2f} > ${daily_cap:.2f}"

    # Check per-agent total
    agent_spent = sum(e.get("cost", 0) or 0 for e in today_events() if e.get("agent") == agent)
    if agent_spent + proposed_cost > agent_cap:
        return False, f"agent cap exceeded: ${agent_spent:.2f} + ${proposed_cost:.2f} > ${agent_cap:.2f}"

    return True, "ok"


# CLI
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        s = event_summary(days)
        print(f"\n📊 Event Summary (last {days} day{'s' if days > 1 else ''}):")
        print(f"   Total events: {s['total_events']}")
        print(f"   Total cost: ${s['total_cost']:.4f}")
        print(f"\n   By agent:")
        for agent, count in sorted(s["by_agent"].items(), key=lambda x: -x[1]):
            print(f"     {agent}: {count}")
        print(f"\n   By type:")
        for etype, count in sorted(s["by_type"].items(), key=lambda x: -x[1]):
            print(f"     {etype}: {count}")
    elif len(sys.argv) > 1 and sys.argv[1] == "tail":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        for e in read_events(limit=n):
            agent = e.get("agent", "?")
            etype = e.get("event", "?")
            cost = f" ${e['cost']:.4f}" if e.get("cost") else ""
            print(f"  [{e.get('ts', '?')[:19]}] {agent}.{etype}{cost}")
    elif len(sys.argv) > 1 and sys.argv[1] == "cost":
        print(f"Today's cost: ${cost_today():.4f}")
    else:
        print("Usage: python3 events.py [summary|tail|cost] [days|count]")
