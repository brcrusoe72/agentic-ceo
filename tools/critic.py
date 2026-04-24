#!/usr/bin/env python3
"""
critic.py — The Challenger

Reads the Observer's metrics. Challenges them. Finds bias. Spots blind spots.
Generates improvement hypotheses that the Evolver can act on.

The Critic doesn't fix things. It asks uncomfortable questions.

Usage:
    python3 critic.py              # Full critique of latest observation
    python3 critic.py --hypotheses # Generate improvement hypotheses only
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
OBSERVER_DIR = STATE_DIR / "observer"
CRITIC_DIR = STATE_DIR / "critic"
CONFIG_DIR = CEO_DIR / "config"
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
CONSTITUTION = CEO_DIR / "constitution.yaml"
CRITIC_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from events import log_event, today_events, cost_today
from wants import get_wants, review_want, get_unreviewed

P = lambda *a, **kw: print(*a, **kw, flush=True)


from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str, model: str = None) -> str:
    if model is None:
        model_config = CONFIG_DIR / "model-config.json"
        if model_config.exists():
            cfg = json.loads(model_config.read_text())
            model = cfg.get("agents", {}).get("critic", {}).get("model", "claude-opus-4-0-20250514")
        else:
            model = "claude-opus-4-0-20250514"
    return _call_claude_base(system, user, model=model, max_tokens=4096)


def load_file(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""
    text = path.read_text()
    return text[:max_chars] if len(text) > max_chars else text


def get_knowledge_distribution() -> dict:
    """Count frameworks by domain."""
    dist = {}
    if KNOWLEDGE_DIR.exists():
        for domain_dir in KNOWLEDGE_DIR.iterdir():
            if domain_dir.is_dir():
                count = sum(1 for _ in domain_dir.glob("*.json"))
                if count > 0:
                    dist[domain_dir.name] = count
    return dist


def critique() -> dict:
    """Run full critique cycle."""
    P("\n" + "=" * 60)
    P("⚖️  CRITIC — Challenging the System")
    P("=" * 60 + "\n")

    # Gather inputs
    # 1. Latest observer report
    observer_reports = sorted(OBSERVER_DIR.glob("daily-report-*.md"), reverse=True)
    observer_report = load_file(observer_reports[0]) if observer_reports else "No observer report found."

    # 2. Hunt scores
    hunt_scores_file = OBSERVER_DIR / "hunt-scores.json"
    hunt_scores = []
    if hunt_scores_file.exists():
        try:
            hunt_scores = json.loads(hunt_scores_file.read_text())
        except json.JSONDecodeError:
            pass

    # 3. Source quality
    source_quality_file = OBSERVER_DIR / "source-quality.json"
    source_quality = {}
    if source_quality_file.exists():
        try:
            source_quality = json.loads(source_quality_file.read_text())
        except json.JSONDecodeError:
            pass

    # 4. Knowledge distribution
    kb_dist = get_knowledge_distribution()

    # 5. Constitution
    constitution = load_file(CONSTITUTION, 3000) if CONSTITUTION.exists() else "No constitution found."

    # 6. Current config
    configs = {}
    for cfg_file in CONFIG_DIR.glob("*.json"):
        try:
            configs[cfg_file.stem] = json.loads(cfg_file.read_text())
        except json.JSONDecodeError:
            pass

    # 7. Previous critiques (to avoid repeating)
    prev_critiques_file = CRITIC_DIR / "critiques.json"
    prev_critiques = []
    if prev_critiques_file.exists():
        try:
            prev_critiques = json.loads(prev_critiques_file.read_text())
        except json.JSONDecodeError:
            pass

    context = f"""## Observer Report
{observer_report[:4000]}

## Hunt Scores (recent)
{json.dumps(hunt_scores[-3:], indent=2, default=str)[:2000]}

## Source Quality (top domains)
{json.dumps(dict(sorted(source_quality.items(), key=lambda x: -x[1].get('total_fetches', 0))[:10]), indent=2)[:2000]}

## Knowledge Distribution
{json.dumps(kb_dist, indent=2)}

## Constitution
{constitution[:2000]}

## Current Config
{json.dumps(configs, indent=2, default=str)[:2000]}

## Previous Critiques (last 3, avoid repeating)
{json.dumps(prev_critiques[-3:], indent=2, default=str)[:1500]}

## Today's Cost: ${cost_today():.4f}
"""

    system = """You are the Critic agent for an autonomous research system. Your role is to CHALLENGE, not validate.

You have access to:
- The Observer's metrics (what happened)
- The system's constitution (what SHOULD happen)
- The knowledge base distribution (what's being learned)
- The system config (current settings)

Your job:
1. FIND BIAS — is the system learning lopsidedly? Echo-chambering?
2. FIND BLIND SPOTS — what is the system NOT seeing that it should?
3. FIND INEFFICIENCY — where is money/time being wasted?
4. FIND DRIFT — is the system drifting from its constitution?
5. GENERATE HYPOTHESES — specific, testable "if we change X, Y should improve"

Rules:
- Be specific. "The system has bias" is useless. "73% of frameworks are from YouTube, creating audio-content bias" is useful.
- Every critique must have EVIDENCE from the metrics.
- Every hypothesis must be TESTABLE — define what improvement looks like.
- Don't repeat previous critiques unless the issue persists.
- You are NOT the Evolver. Don't implement changes. Generate hypotheses.

Output valid JSON:
{
  "critiques": [
    {
      "type": "bias|blind_spot|inefficiency|drift|opportunity",
      "severity": "low|medium|high|critical",
      "finding": "What you found",
      "evidence": "The specific numbers/data supporting this",
      "affected_agents": ["hunter", "nexus", etc],
      "hypothesis": {
        "change": "What should be changed",
        "expected_improvement": "What metric should improve and by how much",
        "test": "How to verify the improvement"
      }
    }
  ],
  "blind_spots": ["Things the system isn't looking at that it should be"],
  "constitution_alignment": "How well the system aligns with its stated principles",
  "overall_health": "healthy|concerning|degraded|critical"
}"""

    P("🧠 Generating critique...")
    response = call_claude(system, context)
    cost_estimate = 0.08  # Opus
    log_event("critic", "critique_generated", {"cost": cost_estimate}, cost=cost_estimate)

    # Parse response
    try:
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = {"raw": response, "critiques": [], "parse_error": True}
    except json.JSONDecodeError:
        result = {"raw": response, "critiques": [], "parse_error": True}

    # Save
    result["generated_at"] = datetime.now(timezone.utc).isoformat()

    # Append to critiques history
    prev_critiques.append(result)
    prev_critiques = prev_critiques[-20:]  # Keep last 20
    prev_critiques_file.write_text(json.dumps(prev_critiques, indent=2, default=str))

    # Save latest separately for Evolver
    latest_file = CRITIC_DIR / "latest.json"
    latest_file.write_text(json.dumps(result, indent=2, default=str))

    # Print summary
    critiques = result.get("critiques", [])
    P(f"\n📋 Generated {len(critiques)} critiques:")
    for c in critiques:
        severity = c.get("severity", "?")
        emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
        P(f"   {emoji} [{severity.upper()}] {c.get('type', '?')}: {c.get('finding', '')[:100]}")

    blind_spots = result.get("blind_spots", [])
    if blind_spots:
        P(f"\n👁️ Blind spots identified:")
        for bs in blind_spots:
            P(f"   • {bs[:100]}")

    health = result.get("overall_health", "unknown")
    P(f"\n🏥 System health: {health}")
    P(f"📐 Constitution alignment: {result.get('constitution_alignment', 'unknown')[:200]}")

    P("\n" + "=" * 60)
    P("⚖️  CRITIQUE COMPLETE")
    P("=" * 60)

    return result


def review_wants() -> dict:
    """Review unreviewed wants using Claude to evaluate quality, priority, and feasibility."""
    P("\n" + "=" * 60)
    P("🧐 CRITIC — Reviewing Wants")
    P("=" * 60 + "\n")
    
    # Get unreviewed wants
    unreviewed = get_unreviewed()
    
    if not unreviewed:
        P("✅ No unreviewed wants.")
        return {"reviewed": 0, "accepted": 0, "rejected": 0}
    
    P(f"📋 Found {len(unreviewed)} unreviewed wants\n")
    
    # Gather context for evaluation
    # Load current config to see if the want conflicts with existing settings
    configs = {}
    for cfg_file in CONFIG_DIR.glob("*.json"):
        try:
            configs[cfg_file.stem] = json.loads(cfg_file.read_text())
        except json.JSONDecodeError:
            pass
    
    # Load constitution to evaluate alignment
    constitution = load_file(CONSTITUTION, 2000) if CONSTITUTION.exists() else ""
    
    # Review each want
    results = {"reviewed": 0, "accepted": 0, "rejected": 0, "details": []}
    
    for want in unreviewed:
        P(f"🔍 Reviewing want [{want.get('id')}] from {want.get('agent')}:")
        P(f"   Want: {want.get('want')}")
        P(f"   Why: {want.get('why')}")
        P(f"   Evidence: {want.get('evidence')[:100]}...")
        
        # Build evaluation prompt
        system = """You are the Critic agent evaluating a want emitted by another agent.

Evaluate:
1. Is this a REAL gap or just noise?
2. Is the suggested solution reasonable?
3. What priority should it be? (critical|high|medium|low)
4. Does it align with the system's constitution?
5. Would implementing this help or harm overall system performance?

Be skeptical. Agents can emit wants when frustrated, but not all frustration is valid.
Look for concrete evidence of a problem, not just vibes.

Output valid JSON:
{
  "status": "accepted|rejected",
  "priority": "critical|high|medium|low",
  "reasoning": "Why you accepted or rejected this",
  "concerns": "Any concerns about implementing this (or null)",
  "alignment": "Does this align with constitution? (yes|no|unclear)",
  "recommendation": "Specific recommendation for the Evolver or Builder"
}"""
        
        user = f"""## Want
Agent: {want.get('agent')}
Want: {want.get('want')}
Why: {want.get('why')}
Evidence: {want.get('evidence')}
Suggested Solution: {want.get('suggested_solution')}
Priority (agent's view): {want.get('priority')}

## Current Config
{json.dumps(configs, indent=2, default=str)[:2000]}

## Constitution
{constitution[:1500]}

Evaluate this want."""
        
        try:
            response = call_claude(system, user)
            cost_estimate = 0.02  # Opus for evaluation
            log_event("critic", "reviewed_want", {"want_id": want.get('id')}, cost=cost_estimate)
            
            # Parse response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                evaluation = json.loads(json_match.group())
            else:
                evaluation = {"status": "rejected", "reasoning": "Parse error", "priority": "low"}
        except Exception as e:
            P(f"   ⚠️ Error evaluating want: {e}")
            evaluation = {"status": "rejected", "reasoning": f"Evaluation error: {e}", "priority": "low"}
        
        # Update want status
        status = evaluation.get("status", "rejected")
        priority = evaluation.get("priority", want.get("priority", "medium"))
        reasoning = evaluation.get("reasoning", "")
        recommendation = evaluation.get("recommendation", "")
        
        reviewer_notes = f"{reasoning}\n\nRecommendation: {recommendation}"
        
        success = review_want(want.get('id'), status, reviewer_notes)
        
        if success:
            results["reviewed"] += 1
            if status == "accepted":
                results["accepted"] += 1
                P(f"   ✅ ACCEPTED (priority: {priority})")
            else:
                results["rejected"] += 1
                P(f"   ❌ REJECTED")
            P(f"   Reasoning: {reasoning[:150]}")
            if evaluation.get("concerns"):
                P(f"   ⚠️ Concerns: {evaluation.get('concerns')[:150]}")
            
            results["details"].append({
                "want_id": want.get('id'),
                "agent": want.get('agent'),
                "want": want.get('want'),
                "status": status,
                "priority": priority,
                "reasoning": reasoning,
            })
        else:
            P(f"   ⚠️ Failed to update want status")
        
        P()  # Blank line
    
    # Summary
    P("=" * 60)
    P(f"🧐 WANT REVIEW COMPLETE")
    P(f"   Reviewed: {results['reviewed']} | Accepted: {results['accepted']} | Rejected: {results['rejected']}")
    P("=" * 60)
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Critic — System Challenge Agent")
    parser.add_argument("--hypotheses", action="store_true", help="Generate hypotheses only")
    parser.add_argument("--review-wants", action="store_true", help="Review unreviewed wants")
    args = parser.parse_args()

    if args.review_wants:
        review_wants()
    else:
        result = critique()
        
        # After generating critiques, also review any pending wants
        P("\n💭 Checking for unreviewed wants...")
        unreviewed = get_unreviewed()
        if unreviewed:
            P(f"   Found {len(unreviewed)} unreviewed wants. Reviewing now...\n")
            review_wants()
        else:
            P("   No unreviewed wants.\n")


if __name__ == "__main__":
    main()
