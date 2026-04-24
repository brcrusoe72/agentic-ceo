#!/usr/bin/env python3
"""
barrier_cycle.py — Barrier-Breaking Orchestrator

Runs all three barrier-breaking agents in sequence:
  1. Dissolve (strip complexity theater)
  2. Equalize (democratize insider knowledge)
  3. Bridge (close participation gaps)

Order matters: Dissolve and Equalize outputs feed into Bridge.

Usage:
    python3 barrier_cycle.py              # Full cycle: all three agents
    python3 barrier_cycle.py --scan-only  # Just scan all three, no action
    python3 barrier_cycle.py --status     # Status of all three agents
    python3 barrier_cycle.py --cost-estimate  # Combined cost estimate
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).parent


def run_agent(name: str, script: str, args: list[str] = None) -> bool:
    """Run an agent script and stream output."""
    cmd = [sys.executable, str(TOOLS_DIR / script)] + (args or [])
    print(f"\n{'#'*70}", flush=True)
    print(f"# 🚀 LAUNCHING: {name}", flush=True)
    print(f"# {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'#'*70}\n", flush=True)

    try:
        result = subprocess.run(cmd, cwd=str(TOOLS_DIR.parent), timeout=600)
        success = result.returncode == 0
        if not success:
            print(f"\n⚠️ {name} exited with code {result.returncode}", flush=True)
        return success
    except subprocess.TimeoutExpired:
        print(f"\n⚠️ {name} timed out after 10 minutes", flush=True)
        return False
    except Exception as e:
        print(f"\n❌ {name} failed: {e}", flush=True)
        return False


def run_full_cycle():
    print(f"\n{'='*70}", flush=True)
    print("🎯 BARRIER-BREAKING CYCLE", flush=True)
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", flush=True)
    print(f"{'='*70}", flush=True)
    print("\nSequence: Dissolve → Equalize → Bridge", flush=True)
    print("(Order matters: Dissolve and Equalize feed into Bridge)\n", flush=True)

    start = time.time()
    results = {}

    results["dissolve"] = run_agent("Complexity Dissolver", "dissolve.py")
    results["equalize"] = run_agent("Knowledge Equalizer", "equalizer.py")
    results["bridge"] = run_agent("Participation Bridge", "bridge.py")

    elapsed = time.time() - start

    print(f"\n{'='*70}", flush=True)
    print("📊 BARRIER CYCLE RESULTS", flush=True)
    print(f"{'='*70}", flush=True)
    for agent, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {agent}", flush=True)
    print(f"\n  ⏱️ Total time: {elapsed:.0f}s", flush=True)
    print(f"{'='*70}", flush=True)


def run_scan_only():
    print("📡 SCANNING ALL BARRIER AGENTS...\n", flush=True)
    run_agent("Dissolve Scan", "dissolve.py", ["--scan"])
    run_agent("Equalizer Scan", "equalizer.py", ["--scan"])
    run_agent("Bridge Scan", "bridge.py", ["--scan"])


def show_status():
    print("📊 BARRIER AGENT STATUS\n", flush=True)
    run_agent("Dissolve Status", "dissolve.py", ["--status"])
    run_agent("Equalizer Status", "equalizer.py", ["--status"])
    run_agent("Bridge Status", "bridge.py", ["--status"])


def show_cost_estimate():
    print("💰 COMBINED COST ESTIMATE\n", flush=True)
    run_agent("Dissolve Cost", "dissolve.py", ["--cost-estimate"])
    run_agent("Equalizer Cost", "equalizer.py", ["--cost-estimate"])
    run_agent("Bridge Cost", "bridge.py", ["--cost-estimate"])
    print(f"\n💰 Total estimated: <$3.00 for full barrier cycle", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Barrier-Breaking Orchestrator")
    parser.add_argument("--scan-only", action="store_true", help="Just scan, don't dissolve/equalize/bridge")
    parser.add_argument("--status", action="store_true", help="Show status of all agents")
    parser.add_argument("--cost-estimate", action="store_true", help="Combined cost estimate")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.scan_only:
        run_scan_only()
    elif args.cost_estimate:
        show_cost_estimate()
    else:
        run_full_cycle()


if __name__ == "__main__":
    main()
