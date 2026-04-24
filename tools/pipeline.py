#!/usr/bin/env python3
"""
pipeline.py — Full Pipeline Orchestrator

Chains the Agentic CEO system in sequence:
  1. Hunter — picks top Nexus recommendation (or custom question), runs the hunt
  2. Nexus  — analyzes all knowledge including new hunt results
  3. Barrier Cycle — Dissolve → Equalizer → Bridge
  4. Summary — generates a concise blurb of what changed

Usage:
    python3 pipeline.py                          # Full pipeline
    python3 pipeline.py --question "your q"      # Custom hunt question
    python3 pipeline.py --skip-hunt              # Nexus + Barrier only
    python3 pipeline.py --skip-barrier           # Hunter + Nexus only
    python3 pipeline.py --summary-only           # Regenerate summary
    python3 pipeline.py --status                 # Last pipeline run info
"""

import argparse
import json
import os
import sys
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
NEXUS_DIR = STATE_DIR / "nexus"
PIPELINE_DIR = STATE_DIR / "pipeline"
PIPELINE_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "claude-sonnet-4-5-20250929"


from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str) -> str:
    return _call_claude_base(system, user, model=MODEL, max_tokens=4096)


def run_stage(name: str, cmd: list[str], cwd: str) -> dict:
    """Run a subprocess stage, stream output, return result dict."""
    print(f"\n{'='*70}", flush=True)
    print(f"🚀 STAGE: {name}", flush=True)
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'='*70}\n", flush=True)

    start = time.time()
    try:
        result = subprocess.run(cmd, cwd=cwd, timeout=1800)
        elapsed = time.time() - start
        success = result.returncode == 0
        if not success:
            print(f"\n⚠️  {name} exited with code {result.returncode}", flush=True)
        else:
            print(f"\n✅ {name} completed in {elapsed:.0f}s", flush=True)
        return {"stage": name, "success": success, "elapsed": elapsed, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"\n⚠️  {name} timed out after 15 minutes", flush=True)
        return {"stage": name, "success": False, "elapsed": elapsed, "error": "timeout"}
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n❌ {name} failed: {e}", flush=True)
        return {"stage": name, "success": False, "elapsed": elapsed, "error": str(e)}


def pick_top_recommendation() -> str | None:
    """Pick the top recommendation question from Nexus recommendations."""
    rec_path = NEXUS_DIR / "recommendations.json"
    if not rec_path.exists():
        return None
    try:
        recs = json.loads(rec_path.read_text())
        if not recs:
            return None
        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recs.sort(key=lambda r: priority_order.get(r.get("priority", "medium"), 2))
        top = recs[0]
        print(f"📋 Top recommendation: [{top.get('priority', '?').upper()}]", flush=True)
        print(f"   {top.get('question', '?')}", flush=True)
        print(f"   Reason: {top.get('reason', '')[:120]}", flush=True)
        return top.get("question")
    except Exception:
        return None


def load_file_text(path: Path, max_chars: int = 6000) -> str:
    """Load a text file, truncated."""
    if not path.exists():
        return ""
    try:
        text = path.read_text()
        return text[:max_chars] if len(text) > max_chars else text
    except Exception:
        return ""


def latest_file(directory: Path, pattern: str) -> Path | None:
    """Find latest file matching glob pattern."""
    matches = sorted(directory.glob(pattern))
    return matches[-1] if matches else None


def generate_summary(stages: list[dict]) -> str:
    """Generate a summary blurb from today's pipeline outputs."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Gather all available outputs
    context_parts = []

    # Nexus brief
    brief = latest_file(NEXUS_DIR, f"brief-{today}.md") or latest_file(NEXUS_DIR, "brief-*.md")
    if brief:
        context_parts.append(f"## Nexus Brief\n{load_file_text(brief)}")

    # Connections
    conn = latest_file(NEXUS_DIR, f"connections-{today}.md") or latest_file(NEXUS_DIR, "connections-*.md")
    if conn:
        context_parts.append(f"## Connections\n{load_file_text(conn, 4000)}")

    # Emerging patterns
    emg = latest_file(NEXUS_DIR, f"emerging-{today}.md") or latest_file(NEXUS_DIR, "emerging-*.md")
    if emg:
        context_parts.append(f"## Emerging Patterns\n{load_file_text(emg, 4000)}")

    # Barrier outputs
    for subdir in ["dissolved", "equalized", "bridged"]:
        d = CEO_DIR / "knowledge" / subdir
        if d.exists():
            files = sorted(d.glob("*.json"))
            if files:
                latest = files[-1]
                context_parts.append(f"## Barrier: {subdir}\n{load_file_text(latest, 2000)}")

    # Signal layer output
    signal_latest = PIPELINE_DIR.parent / "signals" / "latest.json"
    if signal_latest.exists():
        try:
            sig = json.loads(signal_latest.read_text())
            sig_summary = sig.get("summary", "")
            if sig_summary:
                context_parts.append(f"## Signal Layer: {sig.get('topic', '?')}\n{sig_summary[:2000]}")
        except Exception:
            pass

    # Stage results
    stage_summary = "\n".join(
        f"- {s['stage']}: {'✅' if s['success'] else '❌'} ({s['elapsed']:.0f}s)"
        for s in stages
    )
    context_parts.append(f"## Pipeline Stages\n{stage_summary}")

    if not context_parts:
        return "No data available to summarize."

    system = """You are summarizing what an autonomous research and analysis system accomplished today.
Write ONE concise paragraph (4-6 sentences). Cover:
- What the system learned today
- What changed or shifted in understanding
- What's now buildable or actionable
Be specific and direct. No filler. No hedging."""

    user = "\n\n".join(context_parts)

    print("\n📝 Generating pipeline summary...", flush=True)
    return call_claude(system, user)


def run_pipeline(question: str = None, skip_hunt: bool = False,
                 skip_barrier: bool = False, summary_only: bool = False):
    """Run the full pipeline."""
    today = datetime.now().strftime("%Y-%m-%d")
    pipeline_start = time.time()
    stages = []
    cwd = str(CEO_DIR)
    tools = str(Path(__file__).parent)

    print(f"\n{'#'*70}", flush=True)
    print(f"#  🧠 AGENTIC CEO — FULL PIPELINE", flush=True)
    print(f"#  📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    if skip_hunt:
        print(f"#  ⏭️  Skipping Hunter", flush=True)
    if skip_barrier:
        print(f"#  ⏭️  Skipping Barrier Cycle", flush=True)
    if summary_only:
        print(f"#  📝 Summary only", flush=True)
    print(f"{'#'*70}\n", flush=True)

    if summary_only:
        summary = generate_summary([])
        summary_path = PIPELINE_DIR / f"summary-{today}.md"
        summary_path.write_text(f"# Pipeline Summary — {today}\n\n{summary}\n")
        print(f"\n💾 Summary saved to {summary_path}", flush=True)
        print(f"\n{summary}", flush=True)
        save_last_run([], time.time() - pipeline_start, summary_path)
        return

    # Stage 1: Hunter
    if not skip_hunt:
        hunt_question = question
        if not hunt_question:
            hunt_question = pick_top_recommendation()
        if hunt_question:
            result = run_stage("Hunter", [
                sys.executable, "-u", os.path.join(tools, "hunter.py"),
                hunt_question,
                "--budget", "0.50",
                "--sources", "15",
                "--depth", "2",
            ], cwd)
            stages.append(result)
        else:
            print("\n⚠️  No hunt question available (no recommendations and no --question). Skipping hunter.", flush=True)
            stages.append({"stage": "Hunter", "success": False, "elapsed": 0, "error": "no question"})

    # Stage 1.5: Signal — Framing analysis on the hunt topic
    signal_topic = question or hunt_question if not skip_hunt else None
    if signal_topic:
        result = run_stage("Signal", [
            sys.executable, "-u", os.path.join(tools, "signal.py"),
            signal_topic, "--no-news",
        ], cwd)
        stages.append(result)
    else:
        print("\n⚠️  No topic for Signal stage. Skipping.", flush=True)

    # Stage 2: Nexus
    result = run_stage("Nexus", [
        sys.executable, "-u", os.path.join(tools, "nexus.py")
    ], cwd)
    stages.append(result)

    # Stage 3: Barrier Cycle
    if not skip_barrier:
        result = run_stage("Barrier Cycle", [
            sys.executable, "-u", os.path.join(tools, "barrier_cycle.py")
        ], cwd)
        stages.append(result)

    # Stage 3.5: Knowledge Router — push new frameworks to downstream systems
    result = run_stage("Knowledge Router", [
        sys.executable, "-u", os.path.join(tools, "knowledge_router.py"),
        "route",
    ], cwd)
    stages.append(result)

    # Stage 3.6: Apply adapters — update downstream systems with new knowledge
    if result["success"]:
        # TrueAICost adapter — update calculator overlay
        calc_adapter = str(CEO_DIR / "builds" / "ai-cost-calculator" / "ceo_adapter.py")
        if os.path.exists(calc_adapter):
            result = run_stage("Adapter: TrueAICost", [
                sys.executable, "-u", calc_adapter, "apply",
            ], cwd)
            stages.append(result)

    # Stage 4: Inward Cycle — Observer
    result = run_stage("Observer", [
        sys.executable, "-u", os.path.join(tools, "observer.py")
    ], cwd)
    stages.append(result)

    # Stage 5: Inward Cycle — Critic
    result = run_stage("Critic", [
        sys.executable, "-u", os.path.join(tools, "critic.py")
    ], cwd)
    stages.append(result)

    # Stage 6: Inward Cycle — Evolver
    result = run_stage("Evolver", [
        sys.executable, "-u", os.path.join(tools, "evolver.py")
    ], cwd)
    stages.append(result)

    # Stage 7: Immune System — Sentinel
    result = run_stage("Sentinel", [
        sys.executable, "-u", os.path.join(tools, "sentinel.py"), "--heal"
    ], cwd)
    stages.append(result)

    # Stage 8: Revenue Pipeline — Score opportunities + write specs
    result = run_stage("Revenue: Opportunity Scorer", [
        sys.executable, "-u", os.path.join(tools, "opportunity_scorer.py")
    ], cwd)
    stages.append(result)

    # If scorer succeeded, write spec for top opportunity
    if result["success"]:
        opps_path = STATE_DIR / "revenue" / "opportunities.json"
        if opps_path.exists():
            try:
                opps = json.loads(opps_path.read_text())
                if opps:
                    top = opps[0]
                    top_name = top.get("name", "unknown")
                    # Check if spec already exists
                    spec_slug = top_name.lower().replace(" ", "-").replace("/", "-")[:40]
                    spec_path = STATE_DIR / "revenue" / "specs" / f"spec-{spec_slug}.md"
                    if not spec_path.exists():
                        result = run_stage("Revenue: Spec Writer", [
                            sys.executable, "-u", os.path.join(tools, "spec_writer.py"),
                            "--opportunity", top_name,
                        ], cwd)
                        stages.append(result)
                    else:
                        print(f"\n  ℹ️  Spec already exists for '{top_name}', skipping writer", flush=True)
            except Exception as e:
                print(f"\n  ⚠️  Could not read opportunities: {e}", flush=True)

    # Stage 9: Summary
    total_elapsed = time.time() - pipeline_start
    summary = generate_summary(stages)
    summary_path = PIPELINE_DIR / f"summary-{today}.md"
    summary_path.write_text(f"# Pipeline Summary — {today}\n\n{summary}\n")
    print(f"\n💾 Summary saved to {summary_path}", flush=True)

    # Save last-run metadata
    save_last_run(stages, total_elapsed, summary_path)

    # Final report
    print(f"\n{'='*70}", flush=True)
    print(f"📊 PIPELINE COMPLETE", flush=True)
    print(f"{'='*70}", flush=True)
    for s in stages:
        icon = "✅" if s["success"] else "❌"
        print(f"  {icon} {s['stage']:<20} {s['elapsed']:.0f}s", flush=True)
    print(f"\n  ⏱️  Total: {total_elapsed:.0f}s", flush=True)
    print(f"\n📝 Summary:\n{summary}", flush=True)
    print(f"{'='*70}", flush=True)


def save_last_run(stages: list[dict], total_elapsed: float, summary_path: Path):
    """Save last-run metadata."""
    today = datetime.now().strftime("%Y-%m-%d")
    last_run = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "total_elapsed_seconds": round(total_elapsed, 1),
        "stages": [
            {
                "name": s["stage"],
                "success": s["success"],
                "elapsed_seconds": round(s["elapsed"], 1),
                "error": s.get("error"),
            }
            for s in stages
        ],
        "outputs": {
            "summary": str(summary_path),
        },
    }

    # Collect any output files produced today
    for name, pattern in [
        ("nexus_brief", f"brief-{today}.md"),
        ("connections", f"connections-{today}.md"),
        ("emerging", f"emerging-{today}.md"),
    ]:
        f = latest_file(NEXUS_DIR, pattern)
        if f:
            last_run["outputs"][name] = str(f)

    last_run_path = PIPELINE_DIR / "last-run.json"
    last_run_path.write_text(json.dumps(last_run, indent=2))
    print(f"💾 Last-run metadata saved to {last_run_path}", flush=True)


def validate_tools():
    """Validate all shipped tools — run --help and basic smoke tests."""
    manifest_path = STATE_DIR / "builder" / "shipped" / "manifest.json"
    if not manifest_path.exists():
        print("No shipped tools to validate.", flush=True)
        return
    
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        print("Failed to load manifest.", flush=True)
        return
    
    print(f"\n{'='*70}", flush=True)
    print(f"🔍 VALIDATING SHIPPED TOOLS ({len(manifest)} tools)", flush=True)
    print(f"{'='*70}\n", flush=True)
    
    results = []
    
    for entry in manifest:
        tool_name = entry.get("tool_name", "")
        files = entry.get("files", [])
        
        # Find the main tool file
        main_file = None
        for f in files:
            if tool_name.replace("-", "_") in f and f.endswith(".py") and "test" not in f.lower():
                main_file = Path(f)
                break
        
        if not main_file or not main_file.exists():
            print(f"❌ {tool_name}: main file not found", flush=True)
            results.append({"tool": tool_name, "status": "missing", "help_ok": False, "smoke_ok": False})
            continue
        
        print(f"🔧 {tool_name}:", flush=True)
        
        # Test --help
        help_ok = False
        try:
            result = subprocess.run(
                [sys.executable, str(main_file), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=main_file.parent
            )
            if result.returncode == 0:
                print(f"   ✅ --help works", flush=True)
                help_ok = True
            else:
                print(f"   ⚠️ --help failed (exit {result.returncode})", flush=True)
        except subprocess.TimeoutExpired:
            print(f"   ⚠️ --help timed out", flush=True)
        except Exception as e:
            print(f"   ⚠️ --help error: {e}", flush=True)
        
        # Try smoke test with common flags
        smoke_ok = False
        for flag in ["--status", "--dry-run", "--list"]:
            try:
                result = subprocess.run(
                    [sys.executable, str(main_file), flag],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=main_file.parent
                )
                if result.returncode == 0:
                    print(f"   ✅ {flag} works", flush=True)
                    smoke_ok = True
                    break
            except Exception:
                pass
        
        if not smoke_ok:
            print(f"   ℹ️  No smoke test flags available", flush=True)
        
        results.append({
            "tool": tool_name,
            "status": "ok" if help_ok else "error",
            "help_ok": help_ok,
            "smoke_ok": smoke_ok,
        })
    
    # Summary
    print(f"\n{'='*70}", flush=True)
    print(f"📊 VALIDATION SUMMARY", flush=True)
    print(f"{'='*70}", flush=True)
    ok_count = sum(1 for r in results if r["status"] == "ok")
    print(f"  ✅ Passed: {ok_count}/{len(results)}", flush=True)
    print(f"  ❌ Failed: {len(results) - ok_count}/{len(results)}", flush=True)
    
    # Save results
    validation_path = PIPELINE_DIR / f"tool-validation-{datetime.now().strftime('%Y-%m-%d')}.json"
    validation_path.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_tools": len(results),
        "passed": ok_count,
        "failed": len(results) - ok_count,
        "results": results,
    }, indent=2))
    print(f"\n💾 Validation results saved to {validation_path}", flush=True)
    print(f"{'='*70}\n", flush=True)


def show_status():
    """Show last pipeline run info."""
    last_run_path = PIPELINE_DIR / "last-run.json"
    if not last_run_path.exists():
        print("No pipeline runs yet.", flush=True)
        return

    data = json.loads(last_run_path.read_text())
    print(f"\n📊 LAST PIPELINE RUN", flush=True)
    print(f"{'='*50}", flush=True)
    print(f"  📅 {data.get('date', '?')}", flush=True)
    print(f"  🕐 {data.get('timestamp', '?')}", flush=True)
    print(f"  ⏱️  {data.get('total_elapsed_seconds', 0):.0f}s total", flush=True)
    print(flush=True)

    for s in data.get("stages", []):
        icon = "✅" if s.get("success") else "❌"
        err = f" — {s['error']}" if s.get("error") else ""
        print(f"  {icon} {s['name']:<20} {s.get('elapsed_seconds', 0):.0f}s{err}", flush=True)

    print(flush=True)
    outputs = data.get("outputs", {})
    if outputs:
        print("  📁 Outputs:", flush=True)
        for name, path in outputs.items():
            print(f"     {name}: {path}", flush=True)

    # Show latest summary content
    summary_path = outputs.get("summary")
    if summary_path and Path(summary_path).exists():
        print(f"\n  📝 Summary:", flush=True)
        text = Path(summary_path).read_text().strip()
        for line in text.split("\n"):
            print(f"     {line}", flush=True)
    print(flush=True)


def main():
    parser = argparse.ArgumentParser(description="Agentic CEO — Full Pipeline Orchestrator")
    parser.add_argument("--question", type=str, help="Custom hunt question")
    parser.add_argument("--skip-hunt", action="store_true", help="Skip Hunter stage")
    parser.add_argument("--skip-barrier", action="store_true", help="Skip Barrier Cycle stage")
    parser.add_argument("--summary-only", action="store_true", help="Just regenerate summary")
    parser.add_argument("--status", action="store_true", help="Show last pipeline run")
    parser.add_argument("--validate-tools", action="store_true", help="Validate all shipped tools")
    args = parser.parse_args()

    if args.status:
        show_status()
        return
    
    if args.validate_tools:
        validate_tools()
        return

    run_pipeline(
        question=args.question,
        skip_hunt=args.skip_hunt,
        skip_barrier=args.skip_barrier,
        summary_only=args.summary_only,
    )


if __name__ == "__main__":
    main()
