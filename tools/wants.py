#!/usr/bin/env python3
"""
wants.py — Agent Desire System

Agents emit wants — structured gaps between what they have and what they need.
Critic reviews wants. Builder prioritizes them alongside Nexus recommendations.

This is how the system develops preferences.

Usage:
    from wants import emit_want, get_wants, review_want, get_unreviewed
    
    # Emit a want
    emit_want("hunter", "Better search quality filter", "too many low-quality sources", 
              "5 garbage domains in last hunt", "domain quality pre-filter", "high")
    
    # Query wants
    wants = get_wants(agent="hunter", status="open")
    unreviewed = get_unreviewed()
    
    # Review a want
    review_want(want_id, "accepted", "Good idea, will implement")
"""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
WANTS_FILE = STATE_DIR / "wants.json"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_wants() -> dict:
    """Load wants from disk."""
    if not WANTS_FILE.exists():
        return {"wants": []}
    try:
        return json.loads(WANTS_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return {"wants": []}


def _save_wants(data: dict) -> None:
    """Save wants to disk."""
    WANTS_FILE.write_text(json.dumps(data, indent=2))


def emit_want(agent: str, want: str, why: str, evidence: str, 
              suggested_solution: str, priority: str = "medium") -> str:
    """
    Emit a want. Returns the want ID.
    
    Priority: critical|high|medium|low
    
    Deduplication: if identical agent+want exists and is open, update evidence instead.
    """
    if priority not in ("critical", "high", "medium", "low"):
        priority = "medium"
    
    data = _load_wants()
    
    # Check for duplicate
    for w in data["wants"]:
        if (w.get("agent") == agent and 
            w.get("want") == want and 
            w.get("status") == "open"):
            # Update evidence
            w["evidence"] = evidence
            w["suggested_solution"] = suggested_solution
            w["priority"] = priority
            w["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save_wants(data)
            return w["id"]
    
    # Create new want
    want_id = str(uuid.uuid4())[:8]
    new_want = {
        "id": want_id,
        "agent": agent,
        "want": want,
        "why": why,
        "evidence": evidence,
        "suggested_solution": suggested_solution,
        "priority": priority,
        "status": "open",
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_at": None,
        "reviewer_notes": None,
    }
    
    data["wants"].append(new_want)
    _save_wants(data)
    return want_id


def get_wants(agent: str = None, priority: str = None, status: str = None) -> list[dict]:
    """
    Query wants with optional filters.
    
    Args:
        agent: Filter by agent name
        priority: Filter by priority (critical|high|medium|low)
        status: Filter by status (open|reviewed|accepted|rejected|building|built)
    """
    data = _load_wants()
    wants = data["wants"]
    
    if agent:
        wants = [w for w in wants if w.get("agent") == agent]
    if priority:
        wants = [w for w in wants if w.get("priority") == priority]
    if status:
        wants = [w for w in wants if w.get("status") == status]
    
    return wants


def review_want(want_id: str, status: str, reviewer_notes: str = None) -> bool:
    """
    Review a want and update its status.
    
    Status: reviewed|accepted|rejected|building|built
    Returns True if want was found and updated.
    """
    valid_statuses = ("reviewed", "accepted", "rejected", "building", "built")
    if status not in valid_statuses:
        raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")
    
    data = _load_wants()
    for w in data["wants"]:
        if w.get("id") == want_id:
            w["status"] = status
            w["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            w["reviewer_notes"] = reviewer_notes
            _save_wants(data)
            return True
    
    return False


def get_unreviewed() -> list[dict]:
    """Get wants that Critic hasn't reviewed yet (status=open)."""
    return get_wants(status="open")


def _print_want(want: dict, verbose: bool = False) -> None:
    """Pretty print a want."""
    priority_emoji = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🟢",
    }
    status_emoji = {
        "open": "⏳",
        "reviewed": "👁️",
        "accepted": "✅",
        "rejected": "❌",
        "building": "🔨",
        "built": "🎉",
    }
    
    emoji_p = priority_emoji.get(want.get("priority", "medium"), "⚪")
    emoji_s = status_emoji.get(want.get("status", "open"), "❓")
    
    print(f"{emoji_p} {emoji_s} [{want.get('id')}] {want.get('agent')}: {want.get('want')}")
    if verbose:
        print(f"     Why: {want.get('why')}")
        print(f"     Evidence: {want.get('evidence')}")
        print(f"     Solution: {want.get('suggested_solution')}")
        if want.get("reviewer_notes"):
            print(f"     Review: {want.get('reviewer_notes')}")
        print(f"     Emitted: {want.get('emitted_at', 'unknown')[:19]}")
        print()


# CLI
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent Want System")
    parser.add_argument("--emit", action="store_true", help="Emit a new want")
    parser.add_argument("--agent", type=str, help="Agent name")
    parser.add_argument("--want", type=str, help="What the agent wants")
    parser.add_argument("--why", type=str, help="Why this is needed")
    parser.add_argument("--evidence", type=str, help="Evidence of the gap")
    parser.add_argument("--solution", type=str, help="Suggested solution")
    parser.add_argument("--priority", type=str, default="medium", 
                        choices=["critical", "high", "medium", "low"],
                        help="Priority level")
    parser.add_argument("--review", type=str, help="Review want by ID")
    parser.add_argument("--status", type=str, 
                        choices=["open", "reviewed", "accepted", "rejected", "building", "built"],
                        help="Status for review or filter")
    parser.add_argument("--notes", type=str, help="Reviewer notes")
    parser.add_argument("--unreviewed", action="store_true", help="Show unreviewed wants")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    if args.emit:
        if not all([args.agent, args.want, args.why, args.evidence, args.solution]):
            print("Error: --emit requires --agent, --want, --why, --evidence, --solution")
            parser.print_help()
            exit(1)
        
        want_id = emit_want(args.agent, args.want, args.why, args.evidence, 
                            args.solution, args.priority)
        print(f"✨ Want emitted: {want_id}")
    
    elif args.review:
        if not args.status:
            print("Error: --review requires --status")
            parser.print_help()
            exit(1)
        
        success = review_want(args.review, args.status, args.notes)
        if success:
            print(f"✅ Want {args.review} updated to {args.status}")
        else:
            print(f"❌ Want {args.review} not found")
    
    elif args.unreviewed:
        wants = get_unreviewed()
        if not wants:
            print("No unreviewed wants.")
        else:
            print(f"\n⏳ Unreviewed Wants ({len(wants)}):\n")
            for w in wants:
                _print_want(w, verbose=args.verbose)
    
    else:
        # List wants with optional filters
        wants = get_wants(agent=args.agent, priority=args.priority, status=args.status)
        
        if not wants:
            print("No wants match the filters.")
        else:
            filters = []
            if args.agent:
                filters.append(f"agent={args.agent}")
            if args.priority:
                filters.append(f"priority={args.priority}")
            if args.status:
                filters.append(f"status={args.status}")
            
            filter_str = f" ({', '.join(filters)})" if filters else ""
            print(f"\n📋 Wants{filter_str} ({len(wants)}):\n")
            
            for w in wants:
                _print_want(w, verbose=args.verbose)
