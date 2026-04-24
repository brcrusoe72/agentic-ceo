#!/usr/bin/env python3
"""
nexus.py — The Pattern Agent

Lives in the knowledge base. Reads everything. Finds connections that
no single hunt could see. When it spots something promising, it writes
a recommendation for the Director to send the Hunter deeper.

This is not a librarian indexing files. This is an analyst staring at
a wall of evidence, connecting red strings between pins.

Usage:
    python3 nexus.py                    # Full analysis cycle
    python3 nexus.py --watch            # Continuous watch mode (runs every N minutes)
    python3 nexus.py --connections      # Just find cross-hunt connections
    python3 nexus.py --emerging         # Spot emerging patterns
    python3 nexus.py --recommendations  # Generate hunt recommendations
    python3 nexus.py --brief            # One-page brief of what we know
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
HUNTS_DIR = STATE_DIR / "hunts"
NEXUS_DIR = STATE_DIR / "nexus"
NEXUS_DIR.mkdir(parents=True, exist_ok=True)


from api import call_claude, get_api_key  # Shared retry-enabled client


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_all_frameworks() -> list[dict]:
    """Load every framework from the knowledge base."""
    frameworks = []
    for domain_dir in KNOWLEDGE_DIR.iterdir():
        if domain_dir.is_dir() and not domain_dir.name.startswith("_"):
            for f in domain_dir.glob("*.json"):
                try:
                    fw = json.loads(f.read_text())
                    fw["_path"] = str(f)
                    fw["_domain_dir"] = domain_dir.name
                    frameworks.append(fw)
                except Exception:
                    pass
    return frameworks


def load_all_hunts() -> list[dict]:
    """Load all hunt state files."""
    hunts = []
    for f in HUNTS_DIR.glob("*.json"):
        if f.stem.endswith("-synthesis") or f.stem.endswith("-thinking"):
            continue
        try:
            data = json.loads(f.read_text())
            if isinstance(data, dict):
                hunts.append(data)
        except Exception:
            pass
    return sorted(hunts, key=lambda h: h.get("started_at", ""), reverse=True)


def load_all_syntheses() -> list[str]:
    """Load all hunt synthesis markdown files."""
    syntheses = []
    for f in sorted(HUNTS_DIR.glob("*-synthesis.md")):
        try:
            syntheses.append(f.read_text())
        except Exception:
            pass
    return syntheses


def load_all_thinking() -> list[str]:
    """Load all thinking logs."""
    logs = []
    for f in sorted(HUNTS_DIR.glob("*-thinking.md")):
        try:
            content = f.read_text()
            # Truncate each to keep context manageable
            if len(content) > 5000:
                content = content[:5000] + "\n\n[...truncated]"
            logs.append(content)
        except Exception:
            pass
    return logs


def load_hunt_findings() -> list[dict]:
    """Load findings from all hunts with their thinking."""
    all_findings = []
    for hunt in load_all_hunts():
        question = hunt.get("question", "Unknown")
        for finding in hunt.get("findings", []):
            finding["_hunt_question"] = question
            finding["_hunt_id"] = hunt.get("hunt_id", "")
            all_findings.append(finding)
    return all_findings


# ---------------------------------------------------------------------------
# Analysis Functions
# ---------------------------------------------------------------------------

def find_connections(frameworks: list[dict], findings: list[dict]) -> str:
    """Find non-obvious connections across all data using chunked analysis."""
    import random

    # If small enough, do single pass
    if len(frameworks) <= 150 and len(findings) <= 60:
        return _find_connections_single(frameworks, findings)

    # Chunk: analyze domains separately, then synthesize
    print(f"   📦 Chunking {len(frameworks)} frameworks into domain batches...")
    fw_by_domain = {}
    for fw in frameworks:
        d = fw.get("_domain_dir", "other")
        fw_by_domain.setdefault(d, []).append(fw)

    # Phase 1: Per-domain summaries (cheap, parallel-safe)
    domain_summaries = []
    for domain, fws in sorted(fw_by_domain.items(), key=lambda x: -len(x[1])):
        fw_lines = []
        for fw in fws[:50]:  # Cap per domain
            fw_lines.append(f"- {fw.get('name','?')} ({fw.get('type','?')}, conf:{fw.get('confidence','?')}): {fw.get('description','')[:120]}")
        domain_summaries.append(f"### {domain} ({len(fws)} frameworks)\n" + "\n".join(fw_lines))

    # Phase 2: Compact findings
    finding_summary = []
    for f in findings[:80]:
        finding_summary.append(f"- [Hunt: {f.get('_hunt_question','?')[:40]}] {f.get('key_insight','')[:150]}")

    # Single synthesis call with compact data
    return _find_connections_single_from_text(
        "\n\n".join(domain_summaries),
        "\n".join(finding_summary),
        len(frameworks),
        len(findings)
    )


def _find_connections_single_from_text(fw_text: str, finding_text: str, fw_count: int, finding_count: int) -> str:
    """Connection analysis from pre-formatted text."""
    system = """You are a pattern analyst. You've been given a knowledge base of frameworks and
research findings from multiple independent hunts. Your job is to find CONNECTIONS that
no single hunt could see.

Look for:
1. CONVERGENCES — different hunts arriving at the same insight from different angles
2. CONTRADICTIONS — frameworks that disagree with each other (these are valuable)
3. GAPS — topics referenced but never explored
4. EMERGING PATTERNS — themes showing up repeatedly across unrelated searches
5. SURPRISING LINKS — connections between seemingly unrelated domains
6. INVESTMENT SIGNALS — where multiple indicators point to the same opportunity

Be specific. Cite which frameworks/findings connect. Don't be generic.
Output markdown."""

    user = f"""## Knowledge Base ({fw_count} frameworks)

{fw_text[:12000]}

## Hunt Findings ({finding_count} sources)

{finding_text[:6000]}

Find the connections. What patterns emerge that no single hunt could see?"""

    print("🔗 Analyzing connections across all data...")
    return call_claude(system, user)


def _find_connections_single(frameworks: list[dict], findings: list[dict]) -> str:
    """Original single-pass connection finding for small datasets."""
    fw_summary = []
    for fw in frameworks[:100]:
        fw_summary.append(f"- [{fw.get('_domain_dir','?')}] {fw.get('name','?')} ({fw.get('type','?')}, conf:{fw.get('confidence','?')}): {fw.get('description','')[:150]}")

    finding_summary = []
    for f in findings[:50]:
        finding_summary.append(f"- [Hunt: {f.get('_hunt_question','?')[:40]}] {f.get('title','?')[:40]}: {f.get('key_insight','')[:150]}")
        if f.get('thinking'):
            finding_summary.append(f"  Thinking: {f['thinking'][:200]}")

    system = """You are a pattern analyst. You've been given a knowledge base of frameworks and
research findings from multiple independent hunts. Your job is to find CONNECTIONS that
no single hunt could see.

Look for:
1. CONVERGENCES — different hunts arriving at the same insight from different angles
2. CONTRADICTIONS — frameworks that disagree with each other (these are valuable)
3. GAPS — topics referenced but never explored
4. EMERGING PATTERNS — themes showing up repeatedly across unrelated searches
5. SURPRISING LINKS — connections between seemingly unrelated domains
6. INVESTMENT SIGNALS — where multiple indicators point to the same opportunity

Be specific. Cite which frameworks/findings connect. Don't be generic.
Output markdown."""

    user = f"""## Knowledge Base ({len(frameworks)} frameworks)

{chr(10).join(fw_summary)}

## Hunt Findings ({len(findings)} sources across {len(set(f.get('_hunt_id','') for f in findings))} hunts)

{chr(10).join(finding_summary)}

Find the connections. What patterns emerge that no single hunt could see?"""

    print("🔗 Analyzing connections across all data...")
    return call_claude(system, user)


def spot_emerging(frameworks: list[dict], findings: list[dict], syntheses: list[str]) -> str:
    """Spot emerging patterns that deserve deeper investigation."""
    synth_text = "\n\n---\n\n".join(s[:2000] for s in syntheses[:5])

    fw_by_domain = {}
    for fw in frameworks:
        d = fw.get("_domain_dir", "other")
        fw_by_domain.setdefault(d, []).append(fw.get("name", "?"))

    domain_summary = "\n".join(f"- **{d}**: {len(fws)} frameworks ({', '.join(fws[:5])}{'...' if len(fws)>5 else ''})"
                               for d, fws in sorted(fw_by_domain.items(), key=lambda x: -len(x[1])))

    system = """You are a strategic intelligence analyst. You're looking at research syntheses
and a knowledge base to spot EMERGING PATTERNS — ideas, technologies, or opportunities
that are showing up repeatedly and gaining momentum.

For each emerging pattern you identify, provide:
1. What the pattern is
2. Evidence (which hunts/frameworks support it)
3. Why it matters
4. A specific research question to investigate it deeper
5. Urgency: is this accelerating or slow-burning?

Also identify:
- WEAK SIGNALS: things mentioned only once but that feel important
- DEAD ENDS: topics that looked promising but the evidence doesn't support
- BLIND SPOTS: important areas we haven't investigated at all

Output markdown. Be specific and actionable."""

    user = f"""## Domain Coverage
{domain_summary}

## Hunt Syntheses
{synth_text}

## Total: {len(frameworks)} frameworks, {len(findings)} findings

What's emerging? What deserves deeper investigation? What are we missing?"""

    print("🌱 Spotting emerging patterns...")
    return call_claude(system, user)


def generate_recommendations(connections: str, emerging: str, frameworks: list[dict]) -> list[dict]:
    """Generate specific hunt recommendations for the Director."""
    system = """You are generating specific research hunt recommendations for an autonomous
research system. Based on the connections and emerging patterns analysis,
recommend 3-5 specific hunts the system should execute next.

For each recommendation, output a JSON object:
{
    "question": "The specific research question to hunt",
    "priority": "critical|high|medium",
    "reason": "Why this matters NOW based on what we've found",
    "expected_value": "What we'd learn and how it connects to existing knowledge",
    "budget": 1.0-3.0,
    "sources": 15-50,
    "depth": 2-3
}

Output a JSON array of recommendations. Be specific — not "learn more about X" but
"What specific protocols are Visa and Mastercard building for AI agent authentication,
and how do they compare to Google's A2A approach?"

Base recommendations on EVIDENCE from the analysis, not generic curiosity."""

    user = f"""## Connection Analysis
{connections[:4000]}

## Emerging Patterns
{emerging[:4000]}

## Current Knowledge: {len(frameworks)} frameworks

Generate hunt recommendations. Output ONLY a JSON array."""

    print("📋 Generating hunt recommendations...")
    response = call_claude(system, user)

    try:
        json_match = re.search(r'\[[\s\S]*\]', response)
        if json_match:
            recs = json.loads(json_match.group())
            return recs
    except json.JSONDecodeError:
        pass
    return []


def generate_brief(frameworks: list[dict], findings: list[dict], syntheses: list[str]) -> str:
    """Generate a one-page brief of everything we know."""
    fw_by_domain = {}
    for fw in frameworks:
        d = fw.get("_domain_dir", "other")
        fw_by_domain.setdefault(d, []).append(fw)

    domain_summary = []
    for d, fws in sorted(fw_by_domain.items(), key=lambda x: -len(x[1])):
        top = sorted(fws, key=lambda x: x.get("confidence", 0), reverse=True)[:3]
        names = ", ".join(f.get("name", "?") for f in top)
        domain_summary.append(f"- **{d}** ({len(fws)} frameworks): {names}")

    synth_text = "\n\n---\n\n".join(s[:2000] for s in syntheses[:5])

    system = """Write a ONE PAGE executive brief. This is for a human who wants to understand
what an autonomous research system has learned. Be direct, be specific, be useful.

Structure:
1. **What We Know** (3-4 key findings, specific not generic)
2. **What's Converging** (where do multiple lines of evidence point?)
3. **What We Don't Know** (biggest gaps)
4. **What To Do Next** (2-3 specific actions)

No filler. No hedging. State what the evidence says."""

    user = f"""## Knowledge Base: {len(frameworks)} frameworks across {len(fw_by_domain)} domains
{chr(10).join(domain_summary)}

## Hunt Syntheses ({len(syntheses)} hunts completed)
{synth_text}

Write the brief."""

    print("📄 Generating executive brief...")
    return call_claude(system, user)


# ---------------------------------------------------------------------------
# Main Cycle
# ---------------------------------------------------------------------------

def _compact_frameworks(frameworks: list[dict]) -> str:
    """Build a compact text representation of all frameworks, grouped by domain."""
    fw_by_domain = {}
    for fw in frameworks:
        d = fw.get("_domain_dir", "other")
        fw_by_domain.setdefault(d, []).append(fw)

    lines = []
    for domain, fws in sorted(fw_by_domain.items(), key=lambda x: -len(x[1])):
        lines.append(f"\n### {domain} ({len(fws)} frameworks)")
        # Sort by confidence desc, cap per domain
        sorted_fws = sorted(fws, key=lambda x: x.get("confidence", 0), reverse=True)
        for fw in sorted_fws[:30]:
            lines.append(f"- {fw.get('name','?')} ({fw.get('type','?')}, conf:{fw.get('confidence','?')}): {fw.get('description','')[:120]}")
        if len(fws) > 30:
            lines.append(f"  ...and {len(fws)-30} more")
    return "\n".join(lines)


def _compact_findings(findings: list[dict]) -> str:
    """Build a compact text representation of findings."""
    lines = []
    for f in findings[:100]:
        lines.append(f"- [Hunt: {f.get('_hunt_question','?')[:50]}] {f.get('key_insight','')[:150]}")
    return "\n".join(lines)


def run_full_cycle():
    """Run the complete Nexus analysis cycle with memory-efficient batching."""
    print(f"\n{'='*70}")
    print(f"🧬 NEXUS — Pattern Analysis Cycle")
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*70}\n")

    # Load everything
    print("📚 Loading knowledge base...")
    frameworks = load_all_frameworks()
    findings = load_hunt_findings()
    syntheses = load_all_syntheses()
    hunts = load_all_hunts()

    # Load signal layer context if available
    signal_context = ""
    signal_path = STATE_DIR / "signals" / "latest.json"
    if signal_path.exists():
        try:
            from signal import format_for_nexus, get_latest_signal
            sig = get_latest_signal()
            if sig:
                signal_context = format_for_nexus(sig)
                print(f"   📡 Signal context loaded: {sig.get('topic', '?')} ({sig.get('source_count', 0)} sources)")
        except Exception as e:
            # Fallback: read raw
            try:
                sig_data = json.loads(signal_path.read_text())
                signal_context = f"## Signal Analysis: {sig_data.get('topic', '?')}\n{sig_data.get('summary', '')}"
                print(f"   📡 Signal context loaded (raw): {sig_data.get('topic', '?')}")
            except Exception:
                print(f"   ⚠️ Could not load signal context: {e}")

    fw_count = len(frameworks)
    fi_count = len(findings)
    print(f"   {fw_count} frameworks, {fi_count} findings, {len(syntheses)} syntheses, {len(hunts)} hunts\n")

    if fw_count < 5:
        print("⚠️  Not enough data for meaningful analysis. Run some hunts first.")
        return

    # Pre-compute compact representations once
    fw_text = _compact_frameworks(frameworks)
    fi_text = _compact_findings(findings)

    # Step 1: Find connections (use compact text directly)
    print("🔗 Step 1/4: Finding connections...")
    # Inject signal context into connection finding
    enriched_fi_text = fi_text
    if signal_context:
        enriched_fi_text = f"{fi_text}\n\n## Narrative Framing Analysis (Signal Layer)\n{signal_context[:4000]}"
    connections = _find_connections_single_from_text(fw_text, enriched_fi_text, fw_count, fi_count)
    conn_path = NEXUS_DIR / f"connections-{datetime.now().strftime('%Y-%m-%d')}.md"
    conn_path.write_text(f"# Cross-Hunt Connections\n\n{connections}")
    print(f"💾 Connections saved to {conn_path}\n")

    # Inject signal context into syntheses for downstream stages
    if signal_context:
        syntheses.append(f"[SIGNAL LAYER FRAMING ANALYSIS]\n{signal_context[:3000]}")

    # Step 2: Spot emerging patterns
    print("🌱 Step 2/4: Spotting emerging patterns...")
    emerging = spot_emerging(frameworks, findings, syntheses)
    emg_path = NEXUS_DIR / f"emerging-{datetime.now().strftime('%Y-%m-%d')}.md"
    emg_path.write_text(f"# Emerging Patterns\n\n{emerging}")
    print(f"💾 Emerging patterns saved to {emg_path}\n")

    # Step 3: Generate recommendations
    print("📋 Step 3/4: Generating recommendations...")
    recs = generate_recommendations(connections, emerging, frameworks)
    if recs:
        recs_path = NEXUS_DIR / "recommendations.json"
        recs_path.write_text(json.dumps(recs, indent=2))
        print(f"💾 {len(recs)} hunt recommendations saved to {recs_path}\n")

        # Also update Director's missions with recommendations
        missions_path = STATE_DIR / "missions.json"
        if missions_path.exists():
            missions = json.loads(missions_path.read_text())
        else:
            missions = {"current_cycle": datetime.now().strftime("%Y-%m-%d"), "missions": [], "hunts": [], "completed": []}

        # ── DEDUP + CAP GOVERNOR ──────────────────────────────────
        # Hard cap: never exceed 30 hunts in the queue.
        # Dedup: skip if a hunt with >60% word overlap already exists.
        HUNT_CAP = 30
        existing_hunts = missions.get("hunts", [])

        def _word_set(text):
            """Extract significant words for overlap check."""
            stop = {"what", "are", "the", "is", "how", "which", "that", "for", "and",
                    "in", "of", "to", "a", "an", "on", "with", "from", "by", "or",
                    "specific", "actual", "currently", "being", "have", "has", "do",
                    "does", "their", "its", "this", "these", "those", "been"}
            return set(w.lower().strip("?.,") for w in text.split() if len(w) > 2 and w.lower() not in stop)

        def _is_duplicate(new_q, existing_qs, threshold=0.60):
            """Check if new question overlaps >threshold with any existing."""
            new_words = _word_set(new_q)
            if not new_words:
                return True
            for eq in existing_qs:
                existing_words = _word_set(eq)
                if not existing_words:
                    continue
                overlap = len(new_words & existing_words) / min(len(new_words), len(existing_words))
                if overlap >= threshold:
                    return True
            return False

        existing_questions = [h.get("question", "") for h in existing_hunts]
        injected = 0
        skipped_dup = 0
        skipped_cap = 0

        for rec in recs:
            question = rec.get("question", "")
            if len(existing_hunts) >= HUNT_CAP:
                skipped_cap += 1
                continue
            if _is_duplicate(question, existing_questions):
                skipped_dup += 1
                continue

            hunt_entry = {
                "id": str(uuid.uuid4())[:8],
                "question": question,
                "priority": rec.get("priority", "medium"),
                "reason": f"[NEXUS] {rec.get('reason', '')}",
                "budget": rec.get("budget", 1.5),
                "max_sources": rec.get("sources", 20),
                "max_depth": rec.get("depth", 2),
                "source": "nexus",
            }
            existing_hunts.append(hunt_entry)
            existing_questions.append(question)
            injected += 1

        missions["hunts"] = existing_hunts
        missions_path.write_text(json.dumps(missions, indent=2))

        print(f"🎯 Injected {injected} hunt recommendations (skipped {skipped_dup} duplicates, {skipped_cap} over cap)")
        print(f"   Queue: {len(existing_hunts)}/{HUNT_CAP} hunts\n")

        print("📋 RECOMMENDED HUNTS:")
        print("-" * 60)
        for i, rec in enumerate(recs, 1):
            print(f"\n  {i}. [{rec.get('priority','?').upper()}] {rec.get('question','?')}")
            print(f"     Why: {rec.get('reason','')[:100]}")
            print(f"     Budget: ${rec.get('budget',1.0):.2f} | Sources: {rec.get('sources',20)} | Depth: {rec.get('depth',2)}")

    # Step 4: Generate brief
    print("\n📄 Step 4/4: Generating executive brief...")
    brief = generate_brief(frameworks, findings, syntheses)
    brief_path = NEXUS_DIR / f"brief-{datetime.now().strftime('%Y-%m-%d')}.md"
    brief_path.write_text(f"# Executive Brief — {datetime.now().strftime('%Y-%m-%d')}\n\n{brief}")
    print(f"💾 Executive brief saved to {brief_path}")

    # Write report
    report = {
        "agent": "nexus",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frameworks_analyzed": fw_count,
        "findings_analyzed": fi_count,
        "hunts_analyzed": len(hunts),
        "recommendations_generated": len(recs) if recs else 0,
    }
    report_path = STATE_DIR / "agent-reports" / f"nexus-{datetime.now().strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*70}")
    print("✅ NEXUS CYCLE COMPLETE")
    print(f"{'='*70}")


def watch_mode(interval_min: int = 30):
    """Continuous watch mode — runs analysis every N minutes."""
    print(f"👁️  NEXUS WATCH MODE — analyzing every {interval_min} minutes")
    print(f"   Press Ctrl+C to stop\n")

    while True:
        run_full_cycle()
        print(f"\n⏳ Next analysis in {interval_min} minutes...\n")
        time.sleep(interval_min * 60)


def main():
    parser = argparse.ArgumentParser(description="Nexus — Pattern Analysis Agent")
    parser.add_argument("--watch", action="store_true", help="Continuous watch mode")
    parser.add_argument("--interval", type=int, default=30, help="Watch interval in minutes")
    parser.add_argument("--connections", action="store_true", help="Find cross-hunt connections only")
    parser.add_argument("--emerging", action="store_true", help="Spot emerging patterns only")
    parser.add_argument("--recommendations", action="store_true", help="Generate hunt recommendations only")
    parser.add_argument("--brief", action="store_true", help="Generate executive brief only")
    args = parser.parse_args()

    frameworks = load_all_frameworks()
    findings = load_hunt_findings()
    syntheses = load_all_syntheses()

    if args.watch:
        watch_mode(args.interval)
    elif args.connections:
        result = find_connections(frameworks, findings)
        print(result)
    elif args.emerging:
        result = spot_emerging(frameworks, findings, syntheses)
        print(result)
    elif args.recommendations:
        connections = find_connections(frameworks, findings)
        emerging = spot_emerging(frameworks, findings, syntheses)
        recs = generate_recommendations(connections, emerging, frameworks)
        print(json.dumps(recs, indent=2))
    elif args.brief:
        result = generate_brief(frameworks, findings, syntheses)
        print(result)
    else:
        run_full_cycle()


if __name__ == "__main__":
    main()
