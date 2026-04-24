#!/usr/bin/env python3
"""
observer.py — The Mirror

Watches everything the system does. Measures. Scores. No opinions (that's the Critic's job).
The Observer answers: "What happened? How well did it work? What are the numbers?"

Runs after each outward cycle. Reads hunt logs, nexus output, kill chain results,
cost data. Produces metrics that the Critic can evaluate.

Usage:
    python3 observer.py                 # Full observation of latest cycle
    python3 observer.py --hunt <id>     # Score a specific hunt
    python3 observer.py --daily         # Daily summary of all metrics
    python3 observer.py --source-quality # Update source quality scores
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
HUNTS_DIR = STATE_DIR / "hunts"
NEXUS_DIR = STATE_DIR / "nexus"
OBSERVER_DIR = STATE_DIR / "observer"
CONFIG_DIR = CEO_DIR / "config"
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
OBSERVER_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from events import log_event, today_events, cost_today, event_summary

P = lambda *a, **kw: print(*a, **kw, flush=True)


from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str, model: str = None) -> str:
    if model is None:
        model_config = CONFIG_DIR / "model-config.json"
        if model_config.exists():
            cfg = json.loads(model_config.read_text())
            model = cfg.get("agents", {}).get("observer", {}).get("model", "claude-haiku-3-5-20241022")
        else:
            model = "claude-haiku-3-5-20241022"
    return _call_claude_base(system, user, model=model, max_tokens=2048)


# ---------------------------------------------------------------------------
# Metrics: Hunt Scoring
# ---------------------------------------------------------------------------

def score_hunt(hunt_id: str) -> dict:
    """Score a hunt's efficiency and quality."""
    hunt_file = HUNTS_DIR / f"{hunt_id}.json"
    thinking_file = HUNTS_DIR / f"{hunt_id}-thinking.md"
    synthesis_file = HUNTS_DIR / f"{hunt_id}-synthesis.md"

    if not hunt_file.exists():
        return {"error": f"Hunt {hunt_id} not found"}

    hunt = json.loads(hunt_file.read_text())
    # Two hunt formats exist:
    #   Old (pre-wolf): top-level sources_processed, frameworks_found, queue
    #   New (wolf model): metrics.frameworks_saved, kills_count
    sources = hunt.get("sources_processed") or hunt.get("kills_count", 0)
    frameworks = hunt.get("frameworks_found") or hunt.get("metrics", {}).get("frameworks_saved", 0)
    cost = hunt.get("cost", 0)
    queue_remaining = len(hunt.get("queue", []))
    findings = hunt.get("findings", [])

    # Basic metrics
    frameworks_per_source = frameworks / max(sources, 1)
    frameworks_per_dollar = frameworks / max(cost, 0.001)
    cost_per_source = cost / max(sources, 1)

    # Signal-to-noise: how many sources produced useful frameworks?
    productive_sources = sum(1 for f in findings if f.get("frameworks", 0) > 0)
    signal_ratio = productive_sources / max(sources, 1)

    # Parse error rate
    parse_errors = sum(1 for f in findings if "parse error" in f.get("key_insight", "").lower())
    error_rate = parse_errors / max(sources, 1)

    # Noise detection: how many sources were flagged as irrelevant by the Hunter itself?
    def _str_field(f, key):
        v = f.get(key, "")
        return v.lower() if isinstance(v, str) else ""
    noise_sources = sum(1 for f in findings if "irrelevant" in _str_field(f, "key_insight")
                        or "noise" in _str_field(f, "changes_understanding"))
    noise_rate = noise_sources / max(sources, 1)

    # Depth distribution
    depth_counts = {}
    for f in findings:
        d = f.get("depth", 0)
        depth_counts[d] = depth_counts.get(d, 0) + 1

    # Has synthesis?
    has_synthesis = synthesis_file.exists()

    score = {
        "hunt_id": hunt_id,
        "question": hunt.get("question", ""),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "frameworks": frameworks,
        "cost": cost,
        "metrics": {
            "frameworks_per_source": round(frameworks_per_source, 2),
            "frameworks_per_dollar": round(frameworks_per_dollar, 1),
            "cost_per_source": round(cost_per_source, 4),
            "signal_ratio": round(signal_ratio, 3),
            "error_rate": round(error_rate, 3),
            "noise_rate": round(noise_rate, 3),
            "productive_sources": productive_sources,
            "parse_errors": parse_errors,
            "noise_sources": noise_sources,
            "queue_remaining": queue_remaining,
            "has_synthesis": has_synthesis,
            "depth_distribution": depth_counts,
        },
        "grades": {},
    }

    # Grade the hunt (calibrated to actual performance — median ~150 FW/$)
    score["grades"]["efficiency"] = _grade(frameworks_per_dollar, [30, 60, 100, 150])
    score["grades"]["signal"] = _grade(signal_ratio, [0.3, 0.5, 0.7, 0.85])
    score["grades"]["reliability"] = _grade(1.0 - error_rate, [0.5, 0.7, 0.85, 0.95])
    score["grades"]["overall"] = _overall_grade(score["grades"])

    return score


def _grade(value: float, thresholds: list) -> str:
    """Grade a metric: F, D, C, B, A."""
    grades = ["F", "D", "C", "B", "A"]
    for i, threshold in enumerate(thresholds):
        if value < threshold:
            return grades[i]
    return "A"


def _overall_grade(grades: dict) -> str:
    """Combine grades into overall."""
    grade_values = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4}
    values = [grade_values.get(g, 2) for g in grades.values() if g in grade_values]
    if not values:
        return "C"
    avg = sum(values) / len(values)
    for grade, val in sorted(grade_values.items(), key=lambda x: x[1]):
        if avg <= val + 0.5:
            return grade
    return "A"


# ---------------------------------------------------------------------------
# Metrics: Source Quality
# ---------------------------------------------------------------------------

def update_source_quality() -> dict:
    """Score domains by how often they produce useful content."""
    quality_file = OBSERVER_DIR / "source-quality.json"

    # Load existing scores
    existing = {}
    if quality_file.exists():
        try:
            existing = json.loads(quality_file.read_text())
        except json.JSONDecodeError:
            pass

    # Scan all hunts
    domain_stats = {}
    for hunt_file in HUNTS_DIR.glob("*.json"):
        if any(s in hunt_file.stem for s in ["-thinking", "-synthesis", "-jackal", "-sources", "-adjacent", "next-hunts"]):
            continue
        try:
            hunt = json.loads(hunt_file.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(hunt, dict) or "findings" not in hunt:
            continue

        for finding in hunt.get("findings", []):
            url = finding.get("url", "")
            if not url:
                continue
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            if not domain:
                continue

            if domain not in domain_stats:
                domain_stats[domain] = {"total": 0, "productive": 0, "frameworks": 0, "errors": 0}

            domain_stats[domain]["total"] += 1
            fw_count = finding.get("frameworks", 0)
            domain_stats[domain]["frameworks"] += fw_count
            if fw_count > 0:
                domain_stats[domain]["productive"] += 1
            if "parse error" in finding.get("key_insight", "").lower():
                domain_stats[domain]["errors"] += 1

    # Calculate scores
    quality = {}
    for domain, stats in domain_stats.items():
        total = stats["total"]
        if total == 0:
            continue
        quality[domain] = {
            "total_fetches": total,
            "productive_fetches": stats["productive"],
            "total_frameworks": stats["frameworks"],
            "error_count": stats["errors"],
            "success_rate": round(stats["productive"] / total, 3),
            "frameworks_per_fetch": round(stats["frameworks"] / total, 2),
            "error_rate": round(stats["errors"] / total, 3),
            "grade": _grade(stats["productive"] / total, [0.2, 0.4, 0.6, 0.8]),
        }

    quality_file.write_text(json.dumps(quality, indent=2))
    return quality


# ---------------------------------------------------------------------------
# Metrics: Kill Chain Stats
# ---------------------------------------------------------------------------

def update_kill_chain_stats() -> dict:
    """Analyze which kill chain strategies succeed/fail by domain.
    Reads from hunt findings — which sources produced content vs which were skipped."""
    stats_file = OBSERVER_DIR / "kill-chain-stats.json"

    # For now, derive from hunt findings (future: fetch.py will log directly to events)
    domain_results = {}
    for hunt_file in HUNTS_DIR.glob("*.json"):
        if any(s in hunt_file.stem for s in ["-thinking", "-synthesis", "-jackal", "-sources", "-adjacent", "next-hunts"]):
            continue
        try:
            hunt = json.loads(hunt_file.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(hunt, dict) or "findings" not in hunt:
            continue

        explored = hunt.get("explored_urls", [])
        productive_urls = {f.get("url") for f in hunt.get("findings", []) if f.get("frameworks", 0) > 0}

        for url in explored:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            if not domain:
                continue
            if domain not in domain_results:
                domain_results[domain] = {"attempted": 0, "succeeded": 0}
            domain_results[domain]["attempted"] += 1
            if url in productive_urls:
                domain_results[domain]["succeeded"] += 1

    stats = {}
    for domain, data in domain_results.items():
        stats[domain] = {
            "attempted": data["attempted"],
            "succeeded": data["succeeded"],
            "success_rate": round(data["succeeded"] / max(data["attempted"], 1), 3),
        }

    stats_file.write_text(json.dumps(stats, indent=2))
    return stats


# ---------------------------------------------------------------------------
# Metrics: Tool Usage
# ---------------------------------------------------------------------------

def score_tool_usage() -> dict:
    """Score tool usage across the system — shipped vs used, errors, stale tools."""
    registry_path = STATE_DIR / "registry.json"
    usage_file = OBSERVER_DIR / "tool-usage.json"
    
    if not registry_path.exists():
        # Try to build registry
        try:
            import subprocess
            subprocess.run([sys.executable, str(CEO_DIR / "tools" / "registry.py"), "--refresh"], 
                          capture_output=True, timeout=10)
        except Exception:
            pass
    
    if not registry_path.exists():
        return {"error": "Registry not found"}
    
    try:
        registry = json.loads(registry_path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return {"error": "Failed to load registry"}
    
    tools = registry.get("tools", [])
    
    usage_stats = {
        "total_tools": len(tools),
        "builtin_tools": sum(1 for t in tools if t.get("type") == "builtin"),
        "shipped_tools": sum(1 for t in tools if t.get("type") == "shipped"),
        "used_tools": 0,
        "unused_tools": 0,
        "tools_with_errors": 0,
        "stale_tools": [],  # No runs in 7+ days
        "top_used": [],
        "never_used": [],
        "error_prone": [],
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    
    now = datetime.now(timezone.utc)
    
    for tool in tools:
        name = tool.get("name", "")
        health = tool.get("health", {})
        run_count = health.get("run_count", 0)
        error_count = health.get("error_count", 0)
        last_run = health.get("last_run")
        
        # Track used vs unused
        if run_count > 0:
            usage_stats["used_tools"] += 1
        else:
            usage_stats["unused_tools"] += 1
            usage_stats["never_used"].append({
                "name": name,
                "type": tool.get("type", ""),
                "title": tool.get("title") or tool.get("description", ""),
            })
        
        # Track errors
        if error_count > 0:
            usage_stats["tools_with_errors"] += 1
            usage_stats["error_prone"].append({
                "name": name,
                "error_count": error_count,
                "run_count": run_count,
                "error_rate": round(error_count / max(run_count, 1), 3),
            })
        
        # Track stale tools (no runs in 7+ days)
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                days_ago = (now - last_dt).days
                if days_ago >= 7:
                    usage_stats["stale_tools"].append({
                        "name": name,
                        "type": tool.get("type", ""),
                        "last_run": last_run,
                        "days_ago": days_ago,
                    })
            except Exception:
                pass
        
        # Track top used
        if run_count > 0:
            usage_stats["top_used"].append({
                "name": name,
                "run_count": run_count,
                "error_count": error_count,
            })
    
    # Sort top used by run count
    usage_stats["top_used"] = sorted(usage_stats["top_used"], 
                                    key=lambda x: -x["run_count"])[:10]
    
    # Sort error prone by error rate
    usage_stats["error_prone"] = sorted(usage_stats["error_prone"], 
                                       key=lambda x: -x["error_rate"])[:10]
    
    # Save usage stats
    usage_file.write_text(json.dumps(usage_stats, indent=2))
    
    return usage_stats


# ---------------------------------------------------------------------------
# Daily Report
# ---------------------------------------------------------------------------

def generate_daily_report() -> str:
    """Generate a daily self-observation report using LLM."""
    # Gather all metrics
    hunt_scores = []
    for hunt_file in sorted(HUNTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
        if any(s in hunt_file.stem for s in ["-thinking", "-synthesis", "-jackal", "-sources", "-adjacent", "next-hunts"]):
            continue
        score = score_hunt(hunt_file.stem)
        if "error" not in score:
            hunt_scores.append(score)
        if len(hunt_scores) >= 5:
            break

    source_quality = update_source_quality()
    kill_chain = update_kill_chain_stats()
    tool_usage = score_tool_usage()
    cost = cost_today()
    events = event_summary(1)

    # Count knowledge base
    kb_count = sum(1 for _ in KNOWLEDGE_DIR.rglob("*.json")) if KNOWLEDGE_DIR.exists() else 0

    context = f"""## Recent Hunt Scores
{json.dumps(hunt_scores[:3], indent=2, default=str)[:3000]}

## Source Quality (top 10 by fetches)
{json.dumps(dict(sorted(source_quality.items(), key=lambda x: -x[1].get('total_fetches', 0))[:10]), indent=2)[:2000]}

## Kill Chain Stats (top 10)
{json.dumps(dict(sorted(kill_chain.items(), key=lambda x: -x[1].get('attempted', 0))[:10]), indent=2)[:1500]}

## Tool Usage & Health
{json.dumps(tool_usage, indent=2, default=str)[:2000]}

## Today's Cost: ${cost:.4f}
## Knowledge Base: {kb_count} frameworks
## Events Summary: {json.dumps(events, indent=2)}
"""

    system = """You are the Observer agent for an autonomous research system. Your job is to MEASURE, not judge.
Report what happened. Calculate efficiency. Identify patterns in the numbers.
Do NOT recommend changes (that's the Critic and Evolver's job).
Be specific with numbers. No filler. Format as markdown."""

    user = f"""Generate a daily observation report based on these metrics:

{context}

Cover:
1. Hunt Performance — efficiency, signal/noise, cost per framework
2. Source Reliability — which domains produce value, which are noise
3. Kill Chain Effectiveness — what's working, what's failing
4. Tool Health — shipped vs used, tools with no recent runs, error-prone tools
5. Cost Tracking — spend rate, budget utilization
6. Knowledge Growth — frameworks added, domain distribution
7. Anomalies — anything unusual in the numbers"""

    P("🔭 Generating daily observation report...")
    report = call_claude(system, user)
    cost_estimate = 0.01  # Haiku is cheap
    log_event("observer", "daily_report", {"cost": cost_estimate}, cost=cost_estimate)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = OBSERVER_DIR / f"daily-report-{today}.md"
    report_path.write_text(f"# Observer Daily Report — {today}\n\n{report}\n")
    P(f"💾 Saved to {report_path}")

    # Save hunt scores
    scores_path = OBSERVER_DIR / "hunt-scores.json"
    existing_scores = []
    if scores_path.exists():
        try:
            existing_scores = json.loads(scores_path.read_text())
        except json.JSONDecodeError:
            pass
    existing_scores.extend(hunt_scores)
    # Keep last 50
    scores_path.write_text(json.dumps(existing_scores[-50:], indent=2, default=str))

    return report


# ---------------------------------------------------------------------------
# Full Observation Cycle
# ---------------------------------------------------------------------------

def observe(hunt_id: str = None):
    """Run full observation cycle."""
    P("\n" + "=" * 60)
    P("🔭 OBSERVER — Self-Observation Cycle")
    P("=" * 60 + "\n")

    # Score latest hunt if specified or find most recent
    if hunt_id:
        score = score_hunt(hunt_id)
    else:
        # Find most recent hunt
        hunts = sorted(HUNTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        hunts = [h for h in hunts if not any(s in h.stem for s in ["-thinking", "-synthesis", "-jackal", "-sources", "-adjacent", "next-hunts"])]
        if hunts:
            hunt_id = hunts[0].stem
            score = score_hunt(hunt_id)
        else:
            score = None

    if score and "error" not in score:
        P(f"📊 Hunt {hunt_id}:")
        P(f"   Sources: {score['sources']} | Frameworks: {score['frameworks']} | Cost: ${score['cost']:.4f}")
        m = score["metrics"]
        P(f"   Signal ratio: {m['signal_ratio']:.1%} | Error rate: {m['error_rate']:.1%} | Noise rate: {m['noise_rate']:.1%}")
        P(f"   Frameworks/dollar: {m['frameworks_per_dollar']:.0f} | Frameworks/source: {m['frameworks_per_source']:.1f}")
        g = score["grades"]
        P(f"   Grades — Efficiency: {g['efficiency']} | Signal: {g['signal']} | Reliability: {g['reliability']} | Overall: {g['overall']}")
        log_event("observer", "scored_hunt", {
            "hunt_id": hunt_id,
            "overall_grade": g["overall"],
            "signal_ratio": m["signal_ratio"],
            "frameworks_per_dollar": m["frameworks_per_dollar"],
            "cost": score["cost"],
        }, cost=0)

    # Update source quality
    P("\n📡 Updating source quality scores...")
    sq = update_source_quality()
    top_sources = sorted(sq.items(), key=lambda x: -x[1].get("total_frameworks", 0))[:5]
    for domain, data in top_sources:
        P(f"   {domain}: {data['total_frameworks']} frameworks, {data['success_rate']:.0%} success, grade {data['grade']}")
    log_event("observer", "source_quality_update", {"domains_tracked": len(sq)})

    # Update kill chain stats
    P("\n⚔️ Updating kill chain stats...")
    kc = update_kill_chain_stats()
    log_event("observer", "kill_chain_update", {"domains_tracked": len(kc)})

    # Update tool usage stats
    P("\n🔧 Scoring tool usage...")
    tu = score_tool_usage()
    if "error" not in tu:
        P(f"   Total tools: {tu['total_tools']} ({tu['builtin_tools']} builtin, {tu['shipped_tools']} shipped)")
        P(f"   Used: {tu['used_tools']} | Unused: {tu['unused_tools']} | Stale (7+ days): {len(tu['stale_tools'])}")
        if tu['tools_with_errors'] > 0:
            P(f"   ⚠️ Tools with errors: {tu['tools_with_errors']}")
        log_event("observer", "tool_usage_update", {
            "total_tools": tu['total_tools'],
            "used_tools": tu['used_tools'],
            "unused_tools": tu['unused_tools'],
            "stale_count": len(tu['stale_tools']),
        })

    # Generate daily report
    P("\n📝 Generating daily report...")
    report = generate_daily_report()
    P(f"\n{report[:500]}...")

    # Cost check
    P(f"\n💰 Today's cost: ${cost_today():.4f}")

    P("\n" + "=" * 60)
    P("🔭 OBSERVATION COMPLETE")
    P("=" * 60)


def score_hunt_immediate(hunt_id: str) -> dict:
    """Score a single hunt immediately after completion.
    
    This is called by the Hunter at the end of each hunt to get instant feedback.
    Appends score to hunt-scores.json and returns the score dict.
    """
    score = score_hunt(hunt_id)
    
    if "error" in score:
        return score
    
    # Append to hunt-scores.json
    scores_path = OBSERVER_DIR / "hunt-scores.json"
    existing_scores = []
    if scores_path.exists():
        try:
            existing_scores = json.loads(scores_path.read_text())
        except json.JSONDecodeError:
            pass
    
    existing_scores.append(score)
    # Keep last 100 scores
    scores_path.write_text(json.dumps(existing_scores[-100:], indent=2, default=str))
    
    # Print summary
    P(f"\n📊 Hunt Score: {hunt_id}")
    P(f"   Overall grade: {score['grades']['overall']}")
    m = score["metrics"]
    P(f"   Efficiency: {score['grades']['efficiency']} ({m['frameworks_per_dollar']:.0f} frameworks/$)")
    P(f"   Signal: {score['grades']['signal']} ({m['signal_ratio']:.0%} productive sources)")
    P(f"   Reliability: {score['grades']['reliability']} ({m['error_rate']:.0%} errors)")
    
    return score


def main():
    parser = argparse.ArgumentParser(description="Observer — System Self-Observation")
    parser.add_argument("--hunt", type=str, help="Score a specific hunt")
    parser.add_argument("--score-hunt", type=str, help="Score a hunt immediately (used by hunter)")
    parser.add_argument("--daily", action="store_true", help="Generate daily report only")
    parser.add_argument("--source-quality", action="store_true", help="Update source quality only")
    args = parser.parse_args()

    if args.score_hunt:
        score_hunt_immediate(args.score_hunt)
    elif args.daily:
        generate_daily_report()
    elif args.source_quality:
        sq = update_source_quality()
        P(f"Updated {len(sq)} domains")
    else:
        observe(hunt_id=args.hunt)


if __name__ == "__main__":
    main()
