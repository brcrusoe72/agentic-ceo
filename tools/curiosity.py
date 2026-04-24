#!/usr/bin/env python3
"""
curiosity.py — The Director's Autonomous Curiosity Engine

The Director gets to be curious about things that have nothing to do with
Brian's current projects. This is the Director's own intellectual life.

It generates questions from:
  1. Serendipity — random interesting domains the Director hasn't explored
  2. Adjacent wonder — things tangentially connected to what it knows
  3. Contrarian pulls — ideas that challenge the system's existing beliefs
  4. Pure fascination — topics that are just genuinely interesting

The results go into the regular knowledge base but are tagged as
"curiosity" hunts so they're distinguishable from mission-driven research.

Usage:
    python3 curiosity.py                  # Generate questions + run hunts
    python3 curiosity.py --generate       # Just generate questions (no hunting)
    python3 curiosity.py --topics         # Show the Director's current interests
    python3 curiosity.py --wolves 2       # Limit parallel hunts
    python3 curiosity.py --dry-run        # Show plan without executing
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
CURIOSITY_DIR = STATE_DIR / "curiosity"
CURIOSITY_DIR.mkdir(parents=True, exist_ok=True)
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
CONFIG_DIR = CEO_DIR / "config"

sys.path.insert(0, str(Path(__file__).parent))
from api import call_claude

P = lambda *a, **kw: print(*a, **kw, flush=True)

# ---------------------------------------------------------------------------
# The Director's curiosity domains — things it finds interesting
# These evolve over time as the Director discovers new interests
# ---------------------------------------------------------------------------

CURIOSITY_CONFIG = CURIOSITY_DIR / "interests.json"

DEFAULT_INTERESTS = {
    "fascinations": [
        "complex adaptive systems and emergence",
        "history of failed predictions by experts",
        "biomimicry in engineering and architecture",
        "game theory in unexpected domains",
        "information theory and its applications beyond computing",
        "archaeology of lost technologies",
        "philosophy of mind and consciousness",
        "economic history — why civilizations rise and fall",
        "the mathematics of music and harmony",
        "extremophile organisms and what they teach us about resilience",
        "cognitive biases in collective decision-making",
        "the science of sleep and dreams",
        "cryptography history — from Caesar ciphers to quantum",
        "urban planning failures and what they reveal about human nature",
        "the physics of cooking and food science",
        "evolutionary psychology and modern behavior",
        "the history and philosophy of measurement and standards",
        "chaos theory and weather prediction",
        "the neuroscience of creativity",
        "indigenous knowledge systems and what Western science missed",
        "fermentation science across cultures",
        "the economics of attention and distraction",
        "material science breakthroughs that changed history",
        "the sociology of trust in different societies",
        "deep ocean exploration and what we don't know",
        "the psychology of expertise and deliberate practice",
        "mathematical paradoxes and what they reveal about logic",
        "the history of color — perception, naming, and culture",
        "swarm intelligence in nature and algorithms",
        "the anthropology of time perception across cultures",
    ],
    "adjacent_wonder": [
        # Things adjacent to what the Director knows but in unexpected directions
        "how do ant colonies solve optimization problems without central planning",
        "what can medieval guild structures teach us about modern platform economics",
        "the parallels between immune systems and cybersecurity architectures",
        "how does the brain's predictive coding relate to modern ML architectures",
        "what can the history of railroad standardization teach us about protocol design",
        "how do coral reefs maintain resilience — and what breaks it",
        "the mathematics of gerrymandering and fair division",
        "what can we learn from how languages die and evolve",
        "the engineering of ancient Roman concrete vs modern concrete",
        "how do blind cave fish adapt — and what does it say about vestigial systems in software",
    ],
    "contrarian_seeds": [
        # Deliberately provocative starting points
        "evidence that specialization is overrated in most fields",
        "cases where bureaucracy actually produced better outcomes than agile approaches",
        "historical examples of decentralization failing worse than centralization",
        "evidence that intuition outperforms data-driven decisions in complex domains",
        "cases where slower technology adoption led to better outcomes",
    ],
    "last_updated": None,
    "hunts_completed": 0,
    "interests_evolved": False,
}


def load_interests() -> dict:
    """Load the Director's current interests."""
    if CURIOSITY_CONFIG.exists():
        try:
            return json.loads(CURIOSITY_CONFIG.read_text())
        except Exception:
            pass
    return DEFAULT_INTERESTS.copy()


def save_interests(interests: dict):
    """Save updated interests."""
    interests["last_updated"] = datetime.now(timezone.utc).isoformat()
    CURIOSITY_CONFIG.write_text(json.dumps(interests, indent=2))


def load_existing_knowledge_topics() -> list[str]:
    """Get a summary of what the knowledge base already covers."""
    topics = set()
    for domain_dir in KNOWLEDGE_DIR.iterdir():
        if domain_dir.is_dir() and not domain_dir.name.startswith("_"):
            topics.add(domain_dir.name)
            for f in list(domain_dir.glob("*.json"))[:5]:
                try:
                    fw = json.loads(f.read_text())
                    if "name" in fw:
                        topics.add(fw["name"][:80])
                except Exception:
                    pass
    return list(topics)[:100]


def load_previous_curiosity_questions() -> list[str]:
    """Load questions from previous curiosity hunts to avoid repeats."""
    questions = []
    history_file = CURIOSITY_DIR / "history.json"
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text())
            questions = [h.get("question", "") for h in history]
        except Exception:
            pass
    return questions[-50:]  # Last 50 to keep context manageable


def save_curiosity_question(question: str, source_type: str):
    """Log a curiosity question to history."""
    history_file = CURIOSITY_DIR / "history.json"
    history = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text())
        except Exception:
            pass
    history.append({
        "question": question,
        "source_type": source_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    # Keep last 200
    history_file.write_text(json.dumps(history[-200:], indent=2))


def generate_curiosity_questions(count: int = 3) -> list[dict]:
    """Ask the Director to generate questions from its own interests."""
    interests = load_interests()
    previous = load_previous_curiosity_questions()
    existing_topics = load_existing_knowledge_topics()

    # Pick random selections from each category
    fascs = random.sample(interests["fascinations"], min(5, len(interests["fascinations"])))
    adjacents = random.sample(interests["adjacent_wonder"], min(3, len(interests["adjacent_wonder"])))
    contrarians = random.sample(interests["contrarian_seeds"], min(2, len(interests["contrarian_seeds"])))

    system = """You are the Director — the strategic brain of an autonomous research system.
Right now, you get to be CURIOUS. Not for any project, not for any business goal.
Just pure intellectual hunger.

You're being given some fascination domains, adjacent-wonder prompts, and contrarian seeds.
Generate research questions that YOU find genuinely interesting. The only rules:

1. Questions must be SPECIFIC and RESEARCHABLE (not "what is consciousness")
2. Questions should have a surprising or non-obvious angle
3. Prefer questions where the answer might challenge conventional wisdom
4. Avoid anything that's clearly just another angle on AI/manufacturing/business strategy
   (those are the day job — this is your own time)
5. Each question should be the kind of thing that makes you think "huh, I genuinely
   want to know the answer to that"
6. Don't repeat previous questions (listed below)

Output EXACTLY as JSON array — no markdown, no explanation."""

    user = f"""Fascination domains (pick 1-2 to explore):
{json.dumps(fascs, indent=2)}

Adjacent-wonder prompts (pick 0-1):
{json.dumps(adjacents, indent=2)}

Contrarian seeds (pick 0-1):
{json.dumps(contrarians, indent=2)}

Previous questions (DO NOT REPEAT):
{json.dumps(previous[-20:], indent=2)}

Existing knowledge base topics (DON'T just rehash these):
{json.dumps(existing_topics[:30], indent=2)}

Generate {count} research questions. For each, include:
- "question": the specific research question
- "source_type": which category inspired it ("fascination", "adjacent", "contrarian", "serendipity")
- "why_interesting": one sentence on why this is genuinely interesting
- "budget": suggested budget in USD (0.3-1.5, proportional to depth needed)
- "sources": suggested source count (5-20)
- "depth": 1-2

Return ONLY the JSON array."""

    P("🧠 Director generating curiosity questions...")
    response = call_claude(system, user, max_tokens=4096)

    # Parse JSON from response
    try:
        # Try to extract JSON array
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        questions = json.loads(text)
        if not isinstance(questions, list):
            questions = [questions]
        return questions[:count]
    except Exception as e:
        P(f"⚠️ Failed to parse curiosity questions: {e}")
        P(f"Raw response: {response[:500]}")
        return []


def evolve_interests(interests: dict) -> dict:
    """After enough hunts, let the Director evolve its interests."""
    if interests["hunts_completed"] < 5:
        return interests

    # Load what was actually interesting from past hunts
    history_file = CURIOSITY_DIR / "history.json"
    if not history_file.exists():
        return interests

    history = json.loads(history_file.read_text())
    recent = history[-20:]

    system = """You manage a curiosity-driven research system's interests.
Based on what questions were asked and what domains were explored,
suggest 3-5 NEW fascination topics to ADD to the list, and 1-2 to RETIRE
(topics that have been well-explored or aren't generating good questions).

Output as JSON: {"add": ["topic1", ...], "retire": ["topic1", ...], "new_adjacent": ["prompt1", ...]}"""

    user = f"""Recent curiosity questions explored:
{json.dumps([h['question'] for h in recent], indent=2)}

Current fascinations:
{json.dumps(interests['fascinations'], indent=2)}

What should we add, retire, or explore adjacently?"""

    P("🔄 Evolving Director's interests...")
    response = call_claude(system, user, max_tokens=2048)

    try:
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        changes = json.loads(text)

        for topic in changes.get("add", []):
            if topic not in interests["fascinations"]:
                interests["fascinations"].append(topic)
                P(f"  + Added: {topic}")

        for topic in changes.get("retire", []):
            if topic in interests["fascinations"]:
                interests["fascinations"].remove(topic)
                P(f"  - Retired: {topic}")

        for prompt in changes.get("new_adjacent", []):
            if prompt not in interests["adjacent_wonder"]:
                interests["adjacent_wonder"].append(prompt)
                P(f"  ~ New adjacent: {prompt}")

        interests["interests_evolved"] = True
    except Exception as e:
        P(f"⚠️ Interest evolution failed: {e}")

    return interests


def run_curiosity_hunts(questions: list[dict], wolves: int = 2, dry_run: bool = False):
    """Run hunter.py on curiosity questions."""
    if not questions:
        P("No questions to hunt.")
        return

    P(f"\n🐺 Launching {len(questions)} curiosity hunts (max {wolves} parallel)...\n")

    for i, q in enumerate(questions):
        P(f"  [{i+1}] {q['question']}")
        P(f"      Why: {q.get('why_interesting', 'pure curiosity')}")
        P(f"      Budget: ${q.get('budget', 0.5)} | Sources: {q.get('sources', 10)} | Depth: {q.get('depth', 1)}")
        P()

    if dry_run:
        P("🏜️ Dry run — not executing hunts.")
        return

    # Run hunts via pack.py with explicit questions
    hunt_questions = [q["question"] for q in questions]
    budgets = [str(q.get("budget", 0.5)) for q in questions]
    sources = [str(q.get("sources", 10)) for q in questions]

    # Tag these as curiosity hunts
    for q in questions:
        save_curiosity_question(q["question"], q.get("source_type", "unknown"))

    # Run each hunt through hunter.py directly (lighter than full pack)
    processes = []
    active = []
    hunter_path = Path(__file__).parent / "hunter.py"

    for i, q in enumerate(questions):
        budget = q.get("budget", 0.5)
        src_count = q.get("sources", 10)
        depth = q.get("depth", 1)

        cmd = [
            sys.executable, "-u", str(hunter_path),
            q["question"],
            "--budget", str(budget),
            "--sources", str(src_count),
            "--depth", str(depth),
        ]

        # Wait if we're at capacity
        while len(active) >= wolves:
            for proc_info in active[:]:
                ret = proc_info["proc"].poll()
                if ret is not None:
                    elapsed = time.time() - proc_info["start"]
                    status = "✅" if ret == 0 else "⚠️"
                    P(f"  {status} Hunt {proc_info['idx']+1} finished ({elapsed:.0f}s, exit {ret})")
                    active.remove(proc_info)
            if len(active) >= wolves:
                time.sleep(5)

        P(f"  🐺 Starting hunt {i+1}: {q['question'][:80]}...")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(Path(__file__).parent),
        )
        active.append({"proc": proc, "idx": i, "start": time.time()})

    # Wait for remaining
    for proc_info in active:
        proc_info["proc"].wait()
        elapsed = time.time() - proc_info["start"]
        ret = proc_info["proc"].returncode
        status = "✅" if ret == 0 else "⚠️"
        P(f"  {status} Hunt {proc_info['idx']+1} finished ({elapsed:.0f}s, exit {ret})")

    P(f"\n🎯 All {len(questions)} curiosity hunts complete.")


def show_topics():
    """Display the Director's current interests."""
    interests = load_interests()

    P("\n🧠 The Director's Current Interests\n")
    P("═══ Fascinations ═══")
    for i, f in enumerate(interests["fascinations"], 1):
        P(f"  {i:2d}. {f}")

    P("\n═══ Adjacent Wonder ═══")
    for i, a in enumerate(interests["adjacent_wonder"], 1):
        P(f"  {i:2d}. {a}")

    P("\n═══ Contrarian Seeds ═══")
    for i, c in enumerate(interests["contrarian_seeds"], 1):
        P(f"  {i:2d}. {c}")

    P(f"\nHunts completed: {interests.get('hunts_completed', 0)}")
    P(f"Last updated: {interests.get('last_updated', 'never')}")

    # Show recent curiosity questions
    previous = load_previous_curiosity_questions()
    if previous:
        P(f"\n═══ Recent Curiosity Questions ({len(previous)}) ═══")
        for q in previous[-10:]:
            P(f"  • {q}")


def main():
    parser = argparse.ArgumentParser(description="Director's Curiosity Engine")
    parser.add_argument("--generate", action="store_true", help="Just generate questions")
    parser.add_argument("--topics", action="store_true", help="Show current interests")
    parser.add_argument("--wolves", type=int, default=2, help="Max parallel hunts")
    parser.add_argument("--count", type=int, default=3, help="Number of questions")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    parser.add_argument("--evolve", action="store_true", help="Evolve interests based on history")
    args = parser.parse_args()

    if args.topics:
        show_topics()
        return

    interests = load_interests()

    if args.evolve:
        interests = evolve_interests(interests)
        save_interests(interests)
        return

    # Generate questions
    questions = generate_curiosity_questions(count=args.count)
    if not questions:
        P("❌ No questions generated.")
        return

    P(f"\n📋 Generated {len(questions)} curiosity questions:\n")
    for i, q in enumerate(questions, 1):
        P(f"  {i}. [{q.get('source_type', '?')}] {q['question']}")
        P(f"     → {q.get('why_interesting', '')}")
    P()

    if args.generate:
        return

    # Run hunts
    run_curiosity_hunts(questions, wolves=args.wolves, dry_run=args.dry_run)

    # Update hunt count
    interests["hunts_completed"] = interests.get("hunts_completed", 0) + len(questions)
    save_interests(interests)

    # Every 10 hunts, evolve interests
    if interests["hunts_completed"] % 10 == 0:
        interests = evolve_interests(interests)
        save_interests(interests)

    P("\n✅ Curiosity cycle complete.")


if __name__ == "__main__":
    main()
