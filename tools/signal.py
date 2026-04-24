#!/usr/bin/env python3
"""
signal.py — Signal Layer integration for CEO Pipeline

Runs framing analysis on a topic using the Signal Layer engine.
Can be invoked standalone or as a pipeline stage.

Usage:
    python3 signal.py "manufacturing AI adoption"
    python3 signal.py --from-nexus          # Pull topic from Nexus recommendations
    python3 signal.py --from-hunter         # Analyze framing of last Hunter topic
"""

import argparse
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# Add signal-layer to path
SIGNAL_DIR = Path(__file__).parent.parent.parent / "signal-layer"
sys.path.insert(0, str(SIGNAL_DIR))

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
SIGNAL_STATE = STATE_DIR / "signals"
SIGNAL_STATE.mkdir(parents=True, exist_ok=True)
NEXUS_DIR = STATE_DIR / "nexus"
HUNTS_DIR = STATE_DIR / "hunts"


def get_nexus_topic() -> str | None:
    """Pull the top recommendation from Nexus as a signal topic."""
    rec_path = NEXUS_DIR / "recommendations.json"
    if not rec_path.exists():
        return None
    try:
        recs = json.loads(rec_path.read_text())
        if recs:
            # Sort by priority, take first
            recs.sort(key=lambda r: r.get("priority", 99))
            return recs[0].get("question", recs[0].get("topic", ""))
    except Exception:
        pass
    return None


def get_hunter_topic() -> str | None:
    """Pull the last Hunter hunt topic."""
    try:
        hunt_files = sorted(HUNTS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if hunt_files:
            data = json.loads(hunt_files[0].read_text())
            return data.get("question", data.get("topic", ""))
    except Exception:
        pass
    return None


def run_signal_analysis(topic: str, include_news: bool = True, track: bool = True) -> dict:
    """Run signal layer analysis and save results to CEO state."""
    from sigint import run_analysis
    
    print(f"\n{'='*70}")
    print(f"📡 CEO SIGNAL STAGE: {topic}")
    print(f"{'='*70}\n")
    
    result = run_analysis(topic, include_news=include_news, track=track, source_count=10)
    
    # Save to CEO state
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_topic = topic[:50].replace(" ", "_").replace("/", "-")
    out_path = SIGNAL_STATE / f"signal-{ts}-{safe_topic}.json"
    out_path.write_text(json.dumps(result, indent=2))
    
    # Also save latest for pipeline consumption
    latest_path = SIGNAL_STATE / "latest.json"
    latest_path.write_text(json.dumps({
        "topic": topic,
        "timestamp": ts,
        "analysis": result.get("analysis", {}),
        "summary": result.get("summary", ""),
        "drift": result.get("drift"),
        "source_count": result.get("source_count", 0),
    }, indent=2))
    
    print(f"\n💾 Signal saved: {out_path.name}")
    print(f"💾 Latest: {latest_path}")
    
    return result


def get_latest_signal() -> dict | None:
    """Read the latest signal analysis — for other pipeline stages to consume."""
    # Check CEO state first, then signal-layer's own DB
    for path in [SIGNAL_STATE / "latest.json", SIGNAL_DIR / "state" / "signals" / "latest.json"]:
        if path.exists():
            return json.loads(path.read_text())
    # Also check signal-layer's signals.db via direct file
    sl_latest = SIGNAL_DIR / "latest_signal.json"
    if sl_latest.exists():
        return json.loads(sl_latest.read_text())
    return None


def format_for_nexus(signal: dict) -> str:
    """Format signal analysis as context for Nexus consumption."""
    if not signal:
        return ""
    
    analysis = signal.get("analysis", {})
    parts = [f"## Signal Analysis: {signal.get('topic', 'unknown')}"]
    parts.append(f"Sources analyzed: {signal.get('source_count', 0)}")
    
    clusters = analysis.get("frame_clusters", [])
    if clusters:
        parts.append("\n### Frame Clusters:")
        for c in clusters:
            parts.append(f"- **{c.get('frame', '?')}** (strength: {c.get('strength', 0):.1f})")
            parts.append(f"  Beneficiary: {c.get('beneficiary', '?')}")
            parts.append(f"  Sources: {', '.join(c.get('sources', [])[:3])}")
    
    omissions = analysis.get("omissions", [])
    if omissions:
        parts.append("\n### Omissions:")
        for o in omissions:
            parts.append(f"- {o.get('description', '')}")
    
    dominant = analysis.get("dominant_frame", {})
    if dominant:
        parts.append(f"\n### Dominant Frame: {dominant.get('frame', '?')}")
        parts.append(f"Why: {dominant.get('why_dominant', '?')}")
    
    sig = analysis.get("signal", "")
    if sig:
        parts.append(f"\n### Signal: {sig}")
    
    summary = signal.get("summary", "")
    if summary:
        parts.append(f"\n### Narrative Briefing:\n{summary}")
    
    drift = signal.get("drift")
    if drift and isinstance(drift, dict) and "error" not in drift:
        parts.append(f"\n### Drift: {drift.get('overall_direction', 'unknown')}")
        if drift.get("likely_catalyst"):
            parts.append(f"Catalyst: {drift['likely_catalyst']}")
    
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="CEO Pipeline — Signal Stage")
    parser.add_argument("topic", nargs="?", help="Topic to analyze")
    parser.add_argument("--from-nexus", action="store_true", help="Pull topic from Nexus recommendations")
    parser.add_argument("--from-hunter", action="store_true", help="Analyze last Hunter topic")
    parser.add_argument("--news", action="store_true", default=True, help="Include news sources")
    parser.add_argument("--no-news", action="store_true", help="Skip news sources")
    parser.add_argument("--latest", action="store_true", help="Print latest signal")
    
    args = parser.parse_args()
    
    if args.latest:
        sig = get_latest_signal()
        if sig:
            print(format_for_nexus(sig))
        else:
            print("No signal analysis found.")
        return
    
    topic = args.topic
    if args.from_nexus:
        topic = get_nexus_topic()
        if not topic:
            print("⚠️ No Nexus recommendations found.")
            return
        print(f"📋 From Nexus: {topic}")
    elif args.from_hunter:
        topic = get_hunter_topic()
        if not topic:
            print("⚠️ No Hunter history found.")
            return
        print(f"🐺 From Hunter: {topic}")
    
    if not topic:
        parser.print_help()
        return
    
    include_news = not args.no_news
    run_signal_analysis(topic, include_news=include_news)


if __name__ == "__main__":
    main()
