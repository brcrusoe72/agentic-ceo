#!/usr/bin/env python3
"""
executor.py — The Action Agent

Takes CEO pipeline output (summaries, recommendations, knowledge) and
DOES things with it. Not reports. Actions.

Action Types:
  1. JOB_APPLY    — Found a relevant job? Apply to it.
  2. LINKEDIN     — Insight worth sharing? Draft and queue a post.
  3. OUTREACH     — Found a person/company to contact? Draft the message.
  4. BUILD        — Identified a tool/prototype opportunity? Create a build prompt.
  5. MEMORY       — Learned something about the operator's strategy? Update memory files.

Usage:
    python3 executor.py                    # Analyze latest cycle, execute actions
    python3 executor.py --dry-run          # Show what would be done, don't do it
    python3 executor.py --cycle YYYY-MM-DD # Execute from specific cycle
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
WORKSPACE = CEO_DIR.parent.parent
STATE_DIR = CEO_DIR / "state"
PIPELINE_DIR = STATE_DIR / "pipeline"
NEXUS_DIR = STATE_DIR / "nexus"
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
EXECUTOR_DIR = STATE_DIR / "executor"
EXECUTOR_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "claude-sonnet-4-5-20250929"

from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str) -> str:
    return _call_claude_base(system, user, model=MODEL, max_tokens=4096)


# ---------------------------------------------------------------------------
# Context Loading
# ---------------------------------------------------------------------------

def load_latest_summary(date: str | None = None) -> str:
    """Load the latest pipeline summary."""
    if date:
        p = PIPELINE_DIR / f"summary-{date}.md"
    else:
        summaries = sorted(PIPELINE_DIR.glob("summary-*.md"), reverse=True)
        p = summaries[0] if summaries else None
    
    if p and p.exists():
        return p.read_text()
    return ""


def load_user_context() -> str:
    """Load USER.md and recent memory for decision context."""
    parts = []
    
    user_md = WORKSPACE / "USER.md"
    if user_md.exists():
        parts.append(f"## USER PROFILE\n{user_md.read_text()}")
    
    memory_md = WORKSPACE / "MEMORY.md"
    if memory_md.exists():
        # Just the first 3000 chars for context
        content = memory_md.read_text()[:3000]
        parts.append(f"## MEMORY (truncated)\n{content}")
    
    # Recent daily notes
    today = datetime.now().strftime("%Y-%m-%d")
    daily = WORKSPACE / "memory" / f"{today}.md"
    if daily.exists():
        parts.append(f"## TODAY'S NOTES\n{daily.read_text()}")
    
    return "\n\n".join(parts)


def load_nexus_brief() -> str:
    """Load Nexus brief if available."""
    brief = NEXUS_DIR / "brief.md"
    if brief.exists():
        return brief.read_text()[:2000]
    return ""


def load_recent_knowledge() -> str:
    """Load the 5 most recent knowledge entries."""
    entries = []
    for domain_dir in sorted(KNOWLEDGE_DIR.iterdir()):
        if domain_dir.is_dir() and not domain_dir.name.startswith("_"):
            for f in sorted(domain_dir.glob("*.json"), reverse=True)[:2]:
                try:
                    data = json.loads(f.read_text())
                    title = data.get("title", f.stem)
                    summary = data.get("summary", "")[:200]
                    entries.append(f"- [{domain_dir.name}] {title}: {summary}")
                except Exception:
                    pass
    return "\n".join(entries[:10])


# ---------------------------------------------------------------------------
# Action Planning
# ---------------------------------------------------------------------------

def plan_actions(summary: str, user_ctx: str, nexus_brief: str, knowledge: str) -> list[dict]:
    """Use Claude to identify executable actions from the cycle output."""
    
    system = """You are the Executor — the action arm of an autonomous intelligence system.

You receive the output of a research/analysis cycle and decide what to DO with it.
Not what to recommend. What to DO. Right now.

You serve the operator — a manufacturing data engineer / MES analytics expert who is:
- Job hunting ($115K-$155K target)
- Building consulting/revenue streams in manufacturing AI
- Positioned as "Manufacturing Data Engineer | MES Analytics & AI Systems"

AVAILABLE ACTIONS (pick 0-5 per cycle, only if genuinely actionable):

1. JOB_APPLY — A specific company/role was identified that matches the operator's profile
   Required: company, role_title, why_match, apply_url (if found)
   
2. LINKEDIN_POST — An insight emerged that positions the operator as a thought leader
   Required: hook, body, hashtags
   Only if the insight is genuinely novel and relevant to manufacturing/MES/OEE audience
   
3. OUTREACH — A specific person or company was identified for networking
   Required: target_name, platform, message_draft, reason
   
4. BUILD_PROMPT — A concrete tool/prototype opportunity was identified
   Required: tool_name, problem_it_solves, spec (brief), estimated_effort
   Only if it directly helps the operator's goals, revenue, or positioning
   
5. MEMORY_UPDATE — A strategic insight that changes the operator's playbook
   Required: category, insight, action_implication

6. SKIP — Nothing from this cycle warrants immediate action
   Required: reason (be honest — "no actionable signal" is fine)

Rules:
- Be ruthlessly practical. "Interesting research" ≠ action.
- A job must be SPECIFIC (company + title) to trigger JOB_APPLY.
- A LinkedIn post must be genuinely insightful, not generic thought leadership fluff.
- BUILD_PROMPT only for things that ship in <4 hours and solve a real problem.
- Better to return SKIP than force weak actions.

Return JSON array of action objects: [{"type": "JOB_APPLY", ...}, ...]
Return [{"type": "SKIP", "reason": "..."}] if nothing warrants action."""

    user = f"""## LATEST CYCLE SUMMARY
{summary}

## NEXUS BRIEF
{nexus_brief}

## RECENT KNOWLEDGE
{knowledge}

## USER CONTEXT
{user_ctx}

What actions should be executed RIGHT NOW based on this cycle's output?
Return ONLY a JSON array."""

    response = call_claude(system, user)
    
    # Parse JSON from response
    try:
        # Try to find JSON array in response
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        
        # Find array bounds
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except (json.JSONDecodeError, IndexError):
        pass
    
    return [{"type": "SKIP", "reason": "Failed to parse action plan"}]


# ---------------------------------------------------------------------------
# Action Execution
# ---------------------------------------------------------------------------

def execute_job_apply(action: dict, dry_run: bool = False) -> dict:
    """Search for and apply to a job."""
    company = action.get("company", "Unknown")
    role = action.get("role_title", "Unknown")
    why = action.get("why_match", "")
    url = action.get("apply_url", "")
    
    result = {
        "type": "JOB_APPLY",
        "company": company,
        "role": role,
        "status": "planned"
    }
    
    if dry_run:
        result["status"] = "dry_run"
        return result
    
    # Log to job tracker
    tracker_path = WORKSPACE / "job-applications.json"
    try:
        if tracker_path.exists():
            jobs = json.loads(tracker_path.read_text())
        else:
            jobs = []
        
        # Check for duplicates
        for job in jobs:
            if job.get("company", "").lower() == company.lower() and \
               job.get("role", "").lower() == role.lower():
                result["status"] = "already_tracked"
                return result
        
        jobs.append({
            "company": company,
            "role": role,
            "url": url,
            "why_match": why,
            "source": "ceo_executor",
            "status": "identified",
            "date_found": datetime.now().strftime("%Y-%m-%d"),
            "date_applied": None
        })
        
        tracker_path.write_text(json.dumps(jobs, indent=2))
        result["status"] = "logged_to_tracker"
        
        # Write apply instruction for main session to pick up
        apply_queue = EXECUTOR_DIR / "apply-queue.json"
        queue = []
        if apply_queue.exists():
            try:
                queue = json.loads(apply_queue.read_text())
            except Exception:
                queue = []
        
        queue.append({
            "company": company,
            "role": role,
            "url": url,
            "why_match": why,
            "queued_at": datetime.now(timezone.utc).isoformat()
        })
        apply_queue.write_text(json.dumps(queue, indent=2))
        result["status"] = "queued_for_application"
        
    except Exception as e:
        result["status"] = f"error: {e}"
    
    return result


def execute_linkedin_post(action: dict, dry_run: bool = False) -> dict:
    """Draft a LinkedIn post and save it for review/posting."""
    hook = action.get("hook", "")
    body = action.get("body", "")
    hashtags = action.get("hashtags", [])
    
    result = {"type": "LINKEDIN_POST", "status": "planned"}
    
    if dry_run:
        result["status"] = "dry_run"
        result["preview"] = f"{hook}\n\n{body}"
        return result
    
    # Save to LinkedIn drafts
    drafts_dir = WORKSPACE / "linkedin" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    draft_path = drafts_dir / f"draft-{ts}.md"
    
    tags = " ".join(f"#{t}" for t in hashtags) if hashtags else ""
    content = f"""# LinkedIn Draft — {datetime.now().strftime("%Y-%m-%d")}
Source: CEO Executor (auto-generated)

---

{hook}

{body}

{tags}

---
Status: DRAFT — Review before posting
"""
    draft_path.write_text(content)
    result["status"] = "drafted"
    result["path"] = str(draft_path)
    
    return result


def execute_outreach(action: dict, dry_run: bool = False) -> dict:
    """Draft an outreach message."""
    target = action.get("target_name", "Unknown")
    platform = action.get("platform", "unknown")
    message = action.get("message_draft", "")
    reason = action.get("reason", "")
    
    result = {"type": "OUTREACH", "target": target, "status": "planned"}
    
    if dry_run:
        result["status"] = "dry_run"
        return result
    
    # Save to outreach queue
    outreach_dir = EXECUTOR_DIR / "outreach"
    outreach_dir.mkdir(parents=True, exist_ok=True)
    
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    outreach_path = outreach_dir / f"outreach-{ts}.json"
    outreach_path.write_text(json.dumps({
        "target": target,
        "platform": platform,
        "message": message,
        "reason": reason,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending_review"
    }, indent=2))
    
    result["status"] = "queued"
    result["path"] = str(outreach_path)
    return result


def execute_build_prompt(action: dict, dry_run: bool = False) -> dict:
    """Create a build prompt for a tool/prototype."""
    name = action.get("tool_name", "unnamed")
    problem = action.get("problem_it_solves", "")
    spec = action.get("spec", "")
    effort = action.get("estimated_effort", "unknown")
    
    result = {"type": "BUILD_PROMPT", "tool": name, "status": "planned"}
    
    if dry_run:
        result["status"] = "dry_run"
        return result
    
    # Save build prompt
    build_dir = EXECUTOR_DIR / "build-queue"
    build_dir.mkdir(parents=True, exist_ok=True)
    
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    prompt_path = build_dir / f"build-{ts}-{name.lower().replace(' ', '-')[:30]}.md"
    prompt_path.write_text(f"""# Build Prompt: {name}
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
Estimated Effort: {effort}
Source: CEO Executor

## Problem
{problem}

## Spec
{spec}

## Acceptance Criteria
- [ ] Tool runs end-to-end without manual intervention
- [ ] Output is actionable (not a report)
- [ ] Tested with real data
""")
    
    result["status"] = "queued"
    result["path"] = str(prompt_path)
    return result


def execute_memory_update(action: dict, dry_run: bool = False) -> dict:
    """Update memory/strategy files with new insight."""
    category = action.get("category", "general")
    insight = action.get("insight", "")
    implication = action.get("action_implication", "")
    
    result = {"type": "MEMORY_UPDATE", "category": category, "status": "planned"}
    
    if dry_run:
        result["status"] = "dry_run"
        return result
    
    # Append to today's memory file
    today = datetime.now().strftime("%Y-%m-%d")
    daily = WORKSPACE / "memory" / f"{today}.md"
    
    entry = f"\n- **CEO Executor [{category}]:** {insight}"
    if implication:
        entry += f" → Action: {implication}"
    
    if daily.exists():
        content = daily.read_text()
        content += entry + "\n"
    else:
        content = entry + "\n"
    
    daily.write_text(content)
    result["status"] = "written"
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

EXECUTORS = {
    "JOB_APPLY": execute_job_apply,
    "LINKEDIN_POST": execute_linkedin_post,
    "OUTREACH": execute_outreach,
    "BUILD_PROMPT": execute_build_prompt,
    "MEMORY_UPDATE": execute_memory_update,
}


def run_executor(date: str | None = None, dry_run: bool = False) -> dict:
    """Full executor cycle."""
    print(f"\n{'='*60}", flush=True)
    print(f"⚡ EXECUTOR — {'DRY RUN' if dry_run else 'LIVE'}", flush=True)
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
    print(f"{'='*60}\n", flush=True)
    
    # Load context
    summary = load_latest_summary(date)
    if not summary:
        print("❌ No summary found. Run the pipeline first.", flush=True)
        return {"status": "no_summary", "actions": []}
    
    user_ctx = load_user_context()
    nexus_brief = load_nexus_brief()
    knowledge = load_recent_knowledge()
    
    print("📋 Planning actions...", flush=True)
    actions = plan_actions(summary, user_ctx, nexus_brief, knowledge)
    
    print(f"📋 {len(actions)} action(s) planned\n", flush=True)
    
    results = []
    for action in actions:
        action_type = action.get("type", "UNKNOWN")
        print(f"  → {action_type}", end="", flush=True)
        
        if action_type == "SKIP":
            print(f" — {action.get('reason', 'no reason')}", flush=True)
            results.append(action)
            continue
        
        executor = EXECUTORS.get(action_type)
        if executor:
            result = executor(action, dry_run=dry_run)
            print(f" — {result.get('status', '?')}", flush=True)
            results.append(result)
        else:
            print(f" — unknown action type", flush=True)
            results.append({"type": action_type, "status": "unknown_type"})
    
    # Save execution log
    log_path = EXECUTOR_DIR / f"execution-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    log_path.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "actions_planned": len(actions),
        "results": results
    }, indent=2))
    
    print(f"\n{'='*60}", flush=True)
    print(f"✅ Executor complete — {len(results)} action(s) processed", flush=True)
    print(f"   Log: {log_path}", flush=True)
    print(f"{'='*60}\n", flush=True)
    
    return {"status": "complete", "results": results, "log": str(log_path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CEO Executor — Action Agent")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without executing")
    parser.add_argument("--cycle", type=str, default=None, help="Date of cycle to execute (YYYY-MM-DD)")
    args = parser.parse_args()
    
    result = run_executor(date=args.cycle, dry_run=args.dry_run)
    
    if result["status"] == "complete":
        sys.exit(0)
    else:
        sys.exit(1)
