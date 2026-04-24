#!/usr/bin/env python3
"""
evolver.py — The Adapter

Reads the Critic's hypotheses. Decides which to implement. Changes system config.
Logs every change. Rolls back if metrics worsen.

The Evolver doesn't think — it acts on the Critic's thinking.

Usage:
    python3 evolver.py              # Review latest critique, implement approved changes
    python3 evolver.py --dry-run    # Show what would change without changing it
    python3 evolver.py --rollback   # Revert last change
"""

import argparse
import json
import os
import sys
import copy
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
CRITIC_DIR = STATE_DIR / "critic"
EVOLVER_DIR = STATE_DIR / "evolver"
CONFIG_DIR = CEO_DIR / "config"
EVOLVER_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from events import log_event, cost_today

P = lambda *a, **kw: print(*a, **kw, flush=True)


from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str) -> str:
    model_config = CONFIG_DIR / "model-config.json"
    model = "claude-sonnet-4-5-20250929"
    if model_config.exists():
        cfg = json.loads(model_config.read_text())
        model = cfg.get("agents", {}).get("evolver", {}).get("model", model)
    return _call_claude_base(system, user, model=model, max_tokens=4096)


def load_changes() -> list:
    """Load change history."""
    changes_file = EVOLVER_DIR / "changes.json"
    if changes_file.exists():
        try:
            return json.loads(changes_file.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_changes(changes: list):
    """Save change history."""
    changes_file = EVOLVER_DIR / "changes.json"
    changes_file.write_text(json.dumps(changes[-50:], indent=2, default=str))


def apply_config_change(config_file: str, key_path: str, new_value, reason: str, dry_run: bool = False) -> dict:
    """Apply a single config change. Returns change record."""
    config_path = CONFIG_DIR / config_file
    if not config_path.exists():
        return {"error": f"Config file not found: {config_file}"}

    config = json.loads(config_path.read_text())
    old_config = copy.deepcopy(config)

    # Navigate to the key
    keys = key_path.split(".")
    target = config
    for k in keys[:-1]:
        if k not in target:
            target[k] = {}
        target = target[k]

    old_value = target.get(keys[-1])
    
    change_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_file": config_file,
        "key_path": key_path,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
        "dry_run": dry_run,
        "rolled_back": False,
    }

    if dry_run:
        P(f"   [DRY RUN] {config_file}.{key_path}: {old_value} → {new_value}")
        P(f"   Reason: {reason}")
        return change_record

    # Apply change
    target[keys[-1]] = new_value
    config["_updated_by"] = "evolver"
    config["_updated_at"] = datetime.now().strftime("%Y-%m-%d")

    config_path.write_text(json.dumps(config, indent=2))
    P(f"   ✅ {config_file}.{key_path}: {old_value} → {new_value}")
    P(f"   Reason: {reason}")

    log_event("evolver", "config_change", {
        "config_file": config_file,
        "key_path": key_path,
        "old_value": str(old_value),
        "new_value": str(new_value),
        "reason": reason,
    })

    return change_record


def evolve(dry_run: bool = False):
    """Read Critic's latest output, decide what to implement."""
    P("\n" + "=" * 60)
    P(f"🧬 EVOLVER — {'DRY RUN' if dry_run else 'Implementing Changes'}")
    P("=" * 60 + "\n")

    # Load latest critique
    latest_file = CRITIC_DIR / "latest.json"
    if not latest_file.exists():
        P("❌ No critic output found. Run critic.py first.")
        return

    critique = json.loads(latest_file.read_text())
    critiques = critique.get("critiques", [])

    if not critiques:
        P("✅ No critiques to act on.")
        return

    # Load current configs for context
    configs = {}
    for cfg_file in CONFIG_DIR.glob("*.json"):
        try:
            configs[cfg_file.stem] = json.loads(cfg_file.read_text())
        except json.JSONDecodeError:
            pass

    # Use LLM to translate critiques into specific config changes
    system = """You are the Evolver agent. You receive critiques with hypotheses and must translate them
into SPECIFIC config changes.

Available config files and their keys:
- hunt-config.json: default_budget, default_max_sources, default_max_depth, relevance_threshold, youtube_weight, web_weight
- search-config.json: blocked_domains (list), preferred_domains (list), domain_weights (dict), max_results_per_query
- budget-config.json: daily_cap_usd, per_agent_caps (dict with agent names)
- model-config.json: agents.{name}.model, agents.{name}.max_tokens

Rules:
1. Only change config values. Never modify code.
2. Make SMALL changes. Nudge, don't overhaul.
3. Skip critiques that are too vague to translate into config changes.
4. Skip critiques where the change could make things worse and we can't easily verify.
5. NEVER change model-config unless explicitly about model selection.
6. NEVER exceed daily budget cap of $1.00.

Output valid JSON:
{
  "changes": [
    {
      "config_file": "hunt-config.json",
      "key_path": "youtube_weight",
      "new_value": 0.7,
      "reason": "Critic found YouTube bias (73% of sources). Reducing weight to diversify.",
      "critique_index": 0
    }
  ],
  "skipped": [
    {"critique_index": 1, "reason": "Too vague to translate into config change"}
  ]
}"""

    user = f"""## Critiques to Consider
{json.dumps(critiques, indent=2, default=str)[:4000]}

## Current Config
{json.dumps(configs, indent=2, default=str)[:3000]}

Translate applicable critiques into specific config changes."""

    P("🧠 Analyzing critiques and planning changes...")
    response = call_claude(system, user)
    cost_estimate = 0.03
    log_event("evolver", "analysis", {"cost": cost_estimate}, cost=cost_estimate)

    # Parse response
    try:
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            plan = json.loads(json_match.group())
        else:
            P("❌ Could not parse Evolver's plan")
            return
    except json.JSONDecodeError:
        P("❌ JSON parse error in Evolver's plan")
        return

    changes = plan.get("changes", [])
    skipped = plan.get("skipped", [])

    P(f"\n📋 Plan: {len(changes)} changes, {len(skipped)} skipped\n")

    # Apply changes
    change_history = load_changes()
    for change in changes:
        record = apply_config_change(
            config_file=change["config_file"],
            key_path=change["key_path"],
            new_value=change["new_value"],
            reason=change.get("reason", ""),
            dry_run=dry_run,
        )
        change_history.append(record)

    for skip in skipped:
        P(f"   ⏭️  Skipped critique #{skip.get('critique_index', '?')}: {skip.get('reason', '')[:80]}")

    save_changes(change_history)

    P(f"\n{'🏁 DRY RUN COMPLETE' if dry_run else '🏁 EVOLUTION COMPLETE'}")
    P(f"   Total changes in history: {len(change_history)}")
    P("=" * 60)


def rollback():
    """Revert the most recent change."""
    P("\n⏪ ROLLBACK — Reverting last change\n")

    change_history = load_changes()
    if not change_history:
        P("❌ No changes to roll back.")
        return

    # Find last non-rolled-back change
    last_change = None
    for change in reversed(change_history):
        if not change.get("rolled_back") and not change.get("dry_run"):
            last_change = change
            break

    if not last_change:
        P("❌ No applicable changes to roll back.")
        return

    # Restore old value
    config_path = CONFIG_DIR / last_change["config_file"]
    if not config_path.exists():
        P(f"❌ Config file missing: {last_change['config_file']}")
        return

    config = json.loads(config_path.read_text())
    keys = last_change["key_path"].split(".")
    target = config
    for k in keys[:-1]:
        target = target.get(k, {})

    P(f"   Reverting {last_change['config_file']}.{last_change['key_path']}")
    P(f"   {last_change['new_value']} → {last_change['old_value']}")

    target[keys[-1]] = last_change["old_value"]
    config["_updated_by"] = "evolver-rollback"
    config["_updated_at"] = datetime.now().strftime("%Y-%m-%d")
    config_path.write_text(json.dumps(config, indent=2))

    last_change["rolled_back"] = True
    last_change["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    save_changes(change_history)

    log_event("evolver", "rollback", {
        "config_file": last_change["config_file"],
        "key_path": last_change["key_path"],
        "restored_value": str(last_change["old_value"]),
    })

    P("   ✅ Rolled back successfully.")


def check_patterns():
    """Analyze recent hunt scores for patterns and generate config recommendations."""
    P("\n" + "=" * 60)
    P("🔍 EVOLVER — Pattern Analysis")
    P("=" * 60 + "\n")
    
    # Load hunt scores
    scores_path = OBSERVER_DIR / "hunt-scores.json"
    if not scores_path.exists():
        P("❌ No hunt scores found. Run observer.py first.")
        return
    
    try:
        all_scores = json.loads(scores_path.read_text())
    except json.JSONDecodeError:
        P("❌ Failed to load hunt scores")
        return
    
    # Get last 5 hunts
    recent_scores = all_scores[-5:] if len(all_scores) >= 5 else all_scores
    
    if len(recent_scores) < 3:
        P(f"⚠️ Need at least 3 hunts for pattern analysis (have {len(recent_scores)})")
        return
    
    P(f"📊 Analyzing {len(recent_scores)} recent hunts...\n")
    
    # Extract metrics
    efficiencies = [s["metrics"]["frameworks_per_dollar"] for s in recent_scores]
    signal_ratios = [s["metrics"]["signal_ratio"] for s in recent_scores]
    error_rates = [s["metrics"]["error_rate"] for s in recent_scores]
    noise_rates = [s["metrics"]["noise_rate"] for s in recent_scores]
    
    # Calculate averages
    avg_efficiency = sum(efficiencies) / len(efficiencies)
    avg_signal = sum(signal_ratios) / len(signal_ratios)
    avg_error = sum(error_rates) / len(error_rates)
    avg_noise = sum(noise_rates) / len(noise_rates)
    
    P(f"   Avg efficiency: {avg_efficiency:.0f} frameworks/$")
    P(f"   Avg signal ratio: {avg_signal:.1%}")
    P(f"   Avg error rate: {avg_error:.1%}")
    P(f"   Avg noise rate: {avg_noise:.1%}\n")
    
    # Detect patterns
    patterns_found = []
    
    # Pattern 1: Consistent low efficiency
    if avg_efficiency < 50:
        patterns_found.append({
            "type": "low_efficiency",
            "severity": "high",
            "description": f"Efficiency is consistently low ({avg_efficiency:.0f} frameworks/$, target >100)",
            "evidence": f"Last {len(recent_scores)} hunts: {', '.join(f'{e:.0f}' for e in efficiencies)}",
            "recommendation": "Reduce max_sources or increase relevance_threshold to avoid processing low-value sources",
            "config_change": {
                "file": "hunt-config.json",
                "key": "max_results_per_query",
                "current": _CONFIG.get("max_results_per_query", 6),
                "proposed": max(3, _CONFIG.get("max_results_per_query", 6) - 1),
            }
        })
    
    # Pattern 2: High skip/noise rate
    if avg_noise > 0.4 or avg_signal < 0.5:
        patterns_found.append({
            "type": "high_noise",
            "severity": "high",
            "description": f"Too many sources are noise (noise: {avg_noise:.0%}, signal: {avg_signal:.0%})",
            "evidence": f"Signal ratios: {', '.join(f'{s:.0%}' for s in signal_ratios)}",
            "recommendation": "Increase relevance_threshold to filter out more low-quality sources",
            "config_change": {
                "file": "hunt-config.json",
                "key": "relevance_threshold",
                "current": _CONFIG.get("relevance_threshold", 0.15),
                "proposed": min(0.25, _CONFIG.get("relevance_threshold", 0.15) + 0.03),
            }
        })
    
    # Pattern 3: High error rate
    if avg_error > 0.1:
        patterns_found.append({
            "type": "high_errors",
            "severity": "medium",
            "description": f"Parse error rate is high ({avg_error:.0%})",
            "evidence": f"Error rates: {', '.join(f'{e:.0%}' for e in error_rates)}",
            "recommendation": "This indicates content extraction is failing. Check fetch.py and kill chain.",
            "config_change": None,  # No config change for this - it's a code issue
        })
    
    # Pattern 4: Check for domain-specific patterns
    domain_stats = {}
    for score in recent_scores:
        for finding in score.get("findings", []):
            url = finding.get("url", "")
            if url:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain not in domain_stats:
                    domain_stats[domain] = {"total": 0, "productive": 0}
                domain_stats[domain]["total"] += 1
                if finding.get("frameworks", 0) > 0:
                    domain_stats[domain]["productive"] += 1
    
    # Find domains with >3 attempts and 0% success
    failing_domains = [
        domain for domain, stats in domain_stats.items()
        if stats["total"] >= 3 and stats["productive"] == 0
    ]
    
    if failing_domains:
        patterns_found.append({
            "type": "failing_domains",
            "severity": "medium",
            "description": f"{len(failing_domains)} domains consistently fail",
            "evidence": f"Domains: {', '.join(failing_domains[:5])}",
            "recommendation": f"Add these domains to blocked_domains in search-config.json",
            "config_change": {
                "file": "search-config.json",
                "key": "blocked_domains",
                "current": _CONFIG.get("blocked_domains", []),
                "proposed": _CONFIG.get("blocked_domains", []) + failing_domains,
            }
        })
    
    # Report patterns
    if not patterns_found:
        P("✅ No concerning patterns detected. System is performing well.\n")
        return
    
    P(f"⚠️ Found {len(patterns_found)} patterns:\n")
    
    for i, pattern in enumerate(patterns_found, 1):
        severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(pattern["severity"], "⚪")
        P(f"{severity_emoji} [{i}] {pattern['type'].upper()}: {pattern['description']}")
        P(f"   Evidence: {pattern['evidence']}")
        P(f"   Recommendation: {pattern['recommendation']}")
        
        if pattern.get("config_change"):
            change = pattern["config_change"]
            P(f"   Config: {change['file']}.{change['key']}")
            P(f"   Current: {change['current']} → Proposed: {change['proposed']}")
        P()
    
    # Generate a critique-style output that Evolver can act on
    critique_file = CRITIC_DIR / "pattern-critique.json"
    critique_output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "evolver-pattern-analysis",
        "critiques": [
            {
                "type": "inefficiency" if p["type"] == "low_efficiency" else "bias" if p["type"] == "high_noise" else "blind_spot",
                "severity": p["severity"],
                "finding": p["description"],
                "evidence": p["evidence"],
                "affected_agents": ["hunter"],
                "hypothesis": {
                    "change": p["recommendation"],
                    "expected_improvement": f"Should improve {p['type']}",
                    "test": "Monitor next 3 hunt scores",
                }
            }
            for p in patterns_found if p.get("config_change")
        ]
    }
    
    critique_file.write_text(json.dumps(critique_output, indent=2, default=str))
    P(f"💾 Saved pattern critique to {critique_file}")
    
    log_event("evolver", "pattern_analysis", {
        "patterns_found": len(patterns_found),
        "recommendations": len([p for p in patterns_found if p.get("config_change")])
    })
    
    P("\n" + "=" * 60)
    P("🔍 PATTERN ANALYSIS COMPLETE")
    P("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Evolver — System Adaptation Agent")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--rollback", action="store_true", help="Revert last change")
    parser.add_argument("--check-patterns", action="store_true", help="Analyze hunt patterns and recommend changes")
    args = parser.parse_args()

    if args.rollback:
        rollback()
    elif args.check_patterns:
        check_patterns()
    else:
        evolve(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
