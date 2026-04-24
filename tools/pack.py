#!/usr/bin/env python3
"""
pack.py — Wolf Pack (Parallel Hunter)

Every hunt goes through the pack. No lone wolves.
Each wolf gets its own full budget ($3 default from config).

Coordination:
  - Each wolf is an independent subprocess running hunter.py
  - Shared URL dedup file (atomic writes, checked at stalk phase)
  - Single post-hunt observer/critic/evolver after all wolves finish

Usage:
    python3 pack.py                          # Pack from nexus recommendations
    python3 pack.py --wolves 3               # Limit pack size
    python3 pack.py --questions "Q1" "Q2"    # Explicit questions
    python3 pack.py --dry-run                # Show plan without executing
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
HUNTS_DIR = STATE_DIR / "hunts"
NEXUS_DIR = STATE_DIR / "nexus"
CONFIG_DIR = CEO_DIR / "config"
PACK_DIR = STATE_DIR / "pack"
PACK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from events import log_event

P = lambda *a, **kw: print(*a, **kw, flush=True)


def load_config() -> tuple[dict, dict]:
    """Load budget and hunt configs."""
    budget = {}
    hunt = {}
    try:
        budget = json.loads((CONFIG_DIR / "budget-config.json").read_text())
    except Exception:
        pass
    try:
        hunt = json.loads((CONFIG_DIR / "hunt-config.json").read_text())
    except Exception:
        pass
    return budget, hunt


def load_nexus_questions(max_questions: int = 5) -> list[dict]:
    """Load questions from nexus recommendations."""
    recs_file = NEXUS_DIR / "recommendations.json"
    if not recs_file.exists():
        return []
    try:
        recs = json.loads(recs_file.read_text())
    except Exception:
        return []

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recs.sort(key=lambda r: priority_order.get(r.get("priority", "medium"), 2))
    return recs[:max_questions]


def run_post_hunt(hunt_ids: list[str]):
    """Run Observer → Critic → Evolver once for the whole pack."""
    P("\n🔄 Pack Post-Hunt: Observer → Critic → Evolver\n")

    for hid in hunt_ids:
        if hid:
            try:
                proc = subprocess.run(
                    ["python3", str(CEO_DIR / "tools" / "observer.py"), "--hunt", hid],
                    timeout=120, capture_output=True, text=True, cwd=str(CEO_DIR),
                )
                for line in proc.stdout.strip().split("\n")[:3]:
                    if line.strip():
                        P(f"   [Observer:{hid[:8]}] {line.strip()}")
            except Exception as e:
                P(f"   ⚠️ Observer failed for {hid}: {e}")

    for name, script in [("Critic", "critic.py"), ("Evolver", "evolver.py")]:
        try:
            proc = subprocess.run(
                ["python3", str(CEO_DIR / "tools" / script)],
                timeout=300, capture_output=True, text=True, cwd=str(CEO_DIR),
            )
            for line in proc.stdout.strip().split("\n")[:5]:
                if line.strip():
                    P(f"   [{name}] {line.strip()}")
        except Exception as e:
            P(f"   ⚠️ {name} failed: {e}")


def run_pack(
    questions: list[dict] = None,
    max_wolves: int = 4,
    dry_run: bool = False,
):
    """Run a wolf pack — multiple parallel hunts, each with full budget."""

    budget_config, hunt_config = load_config()
    wolf_budget = budget_config.get("per_agent_caps", {}).get("hunter", 3.00)
    default_sources = hunt_config.get("default_max_sources", 15)
    default_depth = hunt_config.get("default_max_depth", 2)

    # Load questions from nexus if not provided
    if not questions:
        recs = load_nexus_questions(max_wolves)
        questions = [
            {
                "question": r["question"],
                "sources": r.get("sources", default_sources),
                "depth": r.get("depth", default_depth),
                "priority": r.get("priority", "medium"),
            }
            for r in recs
        ]

    if not questions:
        P("❌ No questions to hunt. Nexus recommendations empty.")
        return

    # Cap to max wolves
    questions = questions[:max_wolves]
    n_wolves = len(questions)
    total_budget = wolf_budget * n_wolves

    # Print pack plan
    P(f"\n{'='*60}")
    P(f"🐺 WOLF PACK — {n_wolves} {'wolf' if n_wolves == 1 else 'wolves'}")
    P(f"   Budget: ${wolf_budget:.2f}/wolf × {n_wolves} = ${total_budget:.2f}")
    P(f"   Sources: {default_sources}/wolf  |  Depth: {default_depth}")
    P(f"{'='*60}\n")

    for i, q in enumerate(questions):
        P(f"   Wolf {i+1}: [{q.get('priority','?')}] ${wolf_budget:.2f} — {q['question'][:70]}")
    P()

    if dry_run:
        P("🏁 DRY RUN — would launch the above. Exiting.")
        return

    # Launch all wolves in parallel
    pack_start = time.time()
    WOLF_TIMEOUT = 3600  # 1 hour per wolf — matches pipeline timeout

    P(f"🚀 Launching {n_wolves} {'wolf' if n_wolves == 1 else 'wolves'}...\n")

    wolves = []
    for i, q in enumerate(questions):
        cmd = [
            "python3", "-u", str(CEO_DIR / "tools" / "hunter.py"),
            q["question"],
            "--budget", str(wolf_budget),
            "--sources", str(q.get("sources", default_sources)),
            "--depth", str(q.get("depth", default_depth)),
        ]
        log_file = PACK_DIR / f"wolf-{i+1}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        fh = open(log_file, "w")
        proc = subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            cwd=str(CEO_DIR),
            env={**os.environ, "WOLF_ID": str(i + 1)},
        )
        wolves.append({
            "proc": proc,
            "log_file": log_file,
            "fh": fh,
            "question": q["question"],
            "wolf_id": i + 1,
            "start": time.time(),
        })
        P(f"   🐺 Wolf {i+1} launched (PID {proc.pid})")

    # Wait for all wolves
    for w in wolves:
        remaining = max(1, WOLF_TIMEOUT - (time.time() - w["start"]))
        try:
            w["proc"].wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            w["proc"].kill()
            w["proc"].wait()
        w["fh"].close()

    # Collect results
    results = []
    for w in wolves:
        elapsed = time.time() - w["start"]
        exit_code = w["proc"].returncode

        hunt_id = None
        frameworks = 0
        cost = 0.0
        try:
            log_text = w["log_file"].read_text()
            for line in log_text.split("\n"):
                if "ID:" in line and "|" in line:
                    parts = line.split("ID:")[1].split("|")[0].strip()
                    hunt_id = parts
                if "Frameworks:" in line and "Kills:" in line:
                    try:
                        fw_part = line.split("Frameworks:")[1].split("|")[0].strip()
                        frameworks = int(fw_part) if fw_part.isdigit() else 0
                    except (IndexError, ValueError):
                        pass
                if "Cost: $" in line and "/" in line:
                    try:
                        cost_part = line.split("Cost: $")[1].split("/")[0].strip()
                        cost = float(cost_part)
                    except (IndexError, ValueError):
                        pass
        except Exception:
            pass

        result = {
            "wolf_id": w["wolf_id"],
            "question": w["question"][:80],
            "hunt_id": hunt_id,
            "exit_code": exit_code,
            "elapsed": round(elapsed, 1),
            "frameworks": frameworks,
            "cost": cost,
            "budget": wolf_budget,
            "log_file": str(w["log_file"]),
        }
        results.append(result)
        status = "✅" if exit_code == 0 else "❌"
        P(f"   {status} Wolf {w['wolf_id']}: {frameworks} fw, "
          f"${cost:.2f}/${wolf_budget:.2f}, {elapsed:.0f}s — {w['question'][:50]}")

    pack_elapsed = time.time() - pack_start

    # Summary
    total_fw = sum(r.get("frameworks", 0) for r in results)
    total_cost = sum(r.get("cost", 0) for r in results)
    successful = sum(1 for r in results if r.get("exit_code") == 0)
    hunt_ids = [r.get("hunt_id") for r in results if r.get("hunt_id")]

    P(f"\n{'='*60}")
    P(f"🐺 PACK COMPLETE")
    P(f"   Wolves: {successful}/{n_wolves} successful")
    P(f"   Frameworks: {total_fw}")
    P(f"   Cost: ${total_cost:.2f} / ${total_budget:.2f}")
    P(f"   Time: {pack_elapsed:.0f}s ({pack_elapsed/60:.1f}min)")
    if n_wolves > 1:
        total_sequential = sum(r.get("elapsed", 0) for r in results)
        if total_sequential > 0:
            P(f"   Speedup: {total_sequential/pack_elapsed:.1f}x vs sequential ({total_sequential:.0f}s → {pack_elapsed:.0f}s)")
    P(f"{'='*60}")

    # Save pack run metadata
    pack_meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "wolves": n_wolves,
        "successful": successful,
        "wolf_budget": wolf_budget,
        "total_frameworks": total_fw,
        "total_cost": total_cost,
        "elapsed_seconds": round(pack_elapsed, 1),
        "results": results,
    }
    pack_file = PACK_DIR / f"pack-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    pack_file.write_text(json.dumps(pack_meta, indent=2))

    log_event("pack", "hunt_complete", {
        "wolves": n_wolves,
        "successful": successful,
        "frameworks": total_fw,
        "cost": total_cost,
        "elapsed": round(pack_elapsed, 1),
    })

    # Post-hunt cycle (once for all wolves)
    if hunt_ids:
        run_post_hunt(hunt_ids)

    return pack_meta


def main():
    parser = argparse.ArgumentParser(description="Wolf Pack — Parallel Research Hunts")
    parser.add_argument("--questions", nargs="+", help="Explicit questions to hunt")
    parser.add_argument("--wolves", type=int, default=4, help="Max wolves in pack (default: 4)")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    args = parser.parse_args()

    if args.questions:
        questions = [
            {"question": q, "sources": 15, "depth": 2, "priority": "manual"}
            for q in args.questions
        ]
    else:
        questions = None

    run_pack(
        questions=questions,
        max_wolves=args.wolves,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
