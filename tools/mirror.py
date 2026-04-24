#!/usr/bin/env python3
"""
mirror.py — The Mirror Tool

Analyzes personal data exports (YouTube, browsing, social) to build a
psychological/behavioral profile. Not a personality quiz — a data-driven
portrait based on what someone actually does, watches, reads, and chooses.

Usage:
    python3 mirror.py                    # Full analysis
    python3 mirror.py --quick            # Top-level summary only
    python3 mirror.py --lens career      # Focus on career/professional patterns
    python3 mirror.py --lens interests   # Focus on interest clusters
    python3 mirror.py --lens personality # Focus on psychological patterns
    python3 mirror.py --lens prospects   # Focus on life trajectory and opportunities

Output:
    state/mirror/profile.json            # Structured profile
    state/mirror/profile.md              # Human-readable portrait
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Paths
CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
MIRROR_DIR = STATE_DIR / "mirror"
MIRROR_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from api import call_claude

MODEL = "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Data Loaders
# ---------------------------------------------------------------------------

def load_youtube_history() -> list[dict]:
    """Load YouTube watch history."""
    path = KNOWLEDGE_DIR / "_youtube_history.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def load_youtube_channels() -> dict:
    """Load channel frequency index."""
    path = KNOWLEDGE_DIR / "_youtube_channels.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def load_youtube_subscriptions() -> list[dict]:
    """Load subscriptions."""
    path = KNOWLEDGE_DIR / "_youtube_subscriptions.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def load_youtube_playlists() -> dict:
    """Load playlist data."""
    path = KNOWLEDGE_DIR / "_youtube_playlists.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def load_hunt_knowledge() -> list[dict]:
    """Load frameworks from CEO knowledge base."""
    frameworks = []
    if not KNOWLEDGE_DIR.exists():
        return frameworks
    for domain_dir in KNOWLEDGE_DIR.iterdir():
        if domain_dir.is_dir() and not domain_dir.name.startswith("_"):
            for f in domain_dir.glob("*.json"):
                try:
                    fw = json.loads(f.read_text())
                    if isinstance(fw, dict):
                        frameworks.append(fw)
                except Exception:
                    pass
    return frameworks


# ---------------------------------------------------------------------------
# Analysis Engines
# ---------------------------------------------------------------------------

def analyze_watch_patterns(history: list[dict]) -> dict:
    """Extract behavioral patterns from watch history."""
    if not history:
        return {"status": "no_data"}

    total = len(history)
    channels = Counter(e["channel"] for e in history)
    
    # Time-based patterns
    date_counts = Counter()
    year_counts = Counter()
    for e in history:
        try:
            # Extract year from date string
            parts = e["date"].split(",")
            if len(parts) >= 2:
                year_match = re.search(r"(\d{4})", e["date"])
                if year_match:
                    year_counts[year_match.group(1)] += 1
        except Exception:
            pass

    # Title keyword analysis — extract themes
    title_words = Counter()
    for e in history:
        words = e["title"].lower().split()
        for w in words:
            w = w.strip(".,!?#()[]\"'")
            if len(w) > 4:
                title_words[w] += 1

    # Filter noise words
    noise = {
        'video', 'watch', 'about', 'would', 'could', 'their', 'there',
        'these', 'those', 'which', 'where', 'while', 'after', 'being',
        'first', 'every', 'other', 'never', 'world', 'think', 'people',
        'shorts', 'movie', 'short', "don't", 'doesn', 'going', 'really',
        'what\'s', 'that\'s', 'they\'re', 'you\'re', 'can\'t', 'won\'t',
        'viral', 'trending', 'foryou', 'youtubeshorts', 'shortvideo',
        'official', 'scene', 'episode', 'season', 'series', 'reaction',
        'reacts', 'challenge', 'started', 'moment', 'makes', 'total',
        'getting', 'things', 'right', 'wrong', 'always', 'never',
    }
    filtered_words = {w: c for w, c in title_words.items() if w not in noise and c > 20}

    # Concentration metric — how focused vs scattered
    top_10_pct = sum(c for _, c in channels.most_common(10)) / total * 100
    top_50_pct = sum(c for _, c in channels.most_common(50)) / total * 100

    return {
        "total_videos": total,
        "unique_channels": len(channels),
        "top_channels": dict(channels.most_common(50)),
        "years_active": dict(sorted(year_counts.items())),
        "top_keywords": dict(sorted(filtered_words.items(), key=lambda x: -x[1])[:100]),
        "concentration": {
            "top_10_channels_pct": round(top_10_pct, 1),
            "top_50_channels_pct": round(top_50_pct, 1),
        },
    }


def analyze_playlists(playlists: dict) -> dict:
    """What someone curates reveals what they value."""
    if not playlists:
        return {"status": "no_data"}
    
    # Categories reveal intentional interests (vs passive watching)
    return {
        "total_playlists": len(playlists),
        "total_curated_videos": sum(playlists.values()),
        "categories": playlists,
        "largest": sorted(playlists.items(), key=lambda x: -x[1])[:10],
    }


def analyze_subscriptions(subs: list[dict]) -> dict:
    """Subscriptions are declared interests."""
    if not subs:
        return {"status": "no_data"}
    return {
        "total": len(subs),
        "channels": [s["name"] for s in subs],
    }


def build_data_summary(watch: dict, playlists: dict, subs: dict) -> str:
    """Build compact text summary for LLM analysis."""
    parts = []
    
    if watch.get("status") != "no_data":
        parts.append(f"YOUTUBE WATCH HISTORY: {watch['total_videos']} videos across {watch['unique_channels']} channels")
        parts.append(f"Concentration: top 10 channels = {watch['concentration']['top_10_channels_pct']}% of all watching")
        parts.append(f"Top 30 channels (by watch count):")
        for ch, count in list(watch['top_channels'].items())[:30]:
            parts.append(f"  {count}x — {ch}")
        parts.append(f"\nTop 60 title keywords:")
        for word, count in list(watch['top_keywords'].items())[:60]:
            parts.append(f"  {count}x — {word}")
        if watch.get("years_active"):
            parts.append(f"\nYears active: {json.dumps(watch['years_active'])}")
    
    if playlists.get("status") != "no_data":
        parts.append(f"\nCURATED PLAYLISTS ({playlists['total_playlists']} playlists, {playlists['total_curated_videos']} videos):")
        for name, count in playlists.get("largest", []):
            parts.append(f"  {count} videos — {name}")
    
    if subs.get("status") != "no_data":
        parts.append(f"\nSUBSCRIPTIONS: {subs['total']} channels")
        # Sample 50 subscription names
        sample = subs["channels"][:50]
        parts.append(f"Sample: {', '.join(sample)}")
    
    # Add known biographical context if available
    bio_path = MIRROR_DIR / "bio_context.md"
    if bio_path.exists():
        parts.append(f"\nKNOWN BIOGRAPHICAL CONTEXT (self-reported, treat as ground truth):")
        parts.append(bio_path.read_text())

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM Analysis
# ---------------------------------------------------------------------------

def run_analysis(data_summary: str, lens: str = None) -> dict:
    """Run LLM analysis on behavioral data."""
    
    lens_prompts = {
        "career": """Focus your analysis on CAREER implications:
- What professional strengths does this person's consumption pattern reveal?
- What industries/roles align with their natural interests?
- What skills are they self-teaching vs ignoring?
- Where are the gaps between what they consume and what would advance their career?
- What type of work environment would they thrive in?""",

        "interests": """Focus on INTEREST CLUSTERS:
- Map the major interest domains and their relative weight
- Identify niche obsessions vs casual browsing
- What topics show deep, sustained engagement vs passing curiosity?
- What's conspicuously absent given other interests?
- How do interests connect to each other (or don't)?""",

        "personality": """Focus on PSYCHOLOGICAL PATTERNS:
- What values and worldview emerge from consumption patterns?
- What type of thinker is this person (analytical, creative, social, etc)?
- What are their information consumption habits (deep diver vs scanner)?
- What emotional/intellectual needs does their content satisfy?
- What personality traits are strongly evidenced vs absent?""",

        "prospects": """Focus on LIFE TRAJECTORY AND OPPORTUNITIES:
- Given their interests, skills, and consumption patterns, what paths are open?
- What are they naturally positioned for that they may not see?
- What blindspots could hold them back?
- If they optimized their trajectory, what does their best-case 5-year look like?
- What's the one thing they should do next that they're probably not doing?""",
    }
    
    if lens and lens in lens_prompts:
        lens_instruction = lens_prompts[lens]
    else:
        lens_instruction = """Analyze ALL dimensions:
1. CORE IDENTITY: Who is this person based on what they actually consume? (Not who they say they are)
2. PERSONALITY TRAITS: What psychological profile emerges from the data?
3. INTEREST MAP: Major domains, depth, connections between interests
4. VALUES & WORLDVIEW: What do they care about? What do they reject?
5. INTELLECTUAL STYLE: How do they learn? Deep vs broad? Analytical vs intuitive?
6. CAREER ALIGNMENT: What professional paths match their actual interests?
7. BLINDSPOTS: What's missing? What should they be exploring but aren't?
8. PROSPECTS: Given all of the above, what are their best moves?
9. CORE TENSION: What internal contradiction or unresolved tension does the data reveal?"""

    system = f"""You are a behavioral analyst examining someone's digital consumption data — primarily YouTube watching history, subscriptions, and curated playlists.

This is NOT a personality quiz. This is forensic behavioral analysis. What someone watches for 72,000 videos reveals who they ACTUALLY are — not who they present as.

Rules:
- Be direct and honest. This person wants truth, not flattery.
- Distinguish between identity (who they are) and aspiration (who they want to be)
- Note contradictions. They're the most interesting data points.
- Don't moralize about content choices. Analyze patterns.
- Quantify when possible (heavy consumer of X = Y% of total)

{lens_instruction}

Output as markdown. Be specific. Use the data."""

    user = f"""BEHAVIORAL DATA FOR ANALYSIS:

{data_summary}

Analyze this person. Who are they really?"""

    print("🪞 Analyzing...")
    try:
        response = call_claude(system, user, model=MODEL, max_tokens=8192)
        return {"analysis": response, "lens": lens or "full", "status": "complete"}
    except Exception as e:
        print(f"⚠️ Analysis failed: {e}")
        return {"analysis": f"Analysis failed: {e}", "lens": lens or "full", "status": "error"}


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def save_report(analysis: dict, raw_data: dict):
    """Save both structured and readable output."""
    
    # Structured profile
    profile = {
        "generated": datetime.utcnow().isoformat(),
        "lens": analysis["lens"],
        "data_sources": {
            "youtube_videos": raw_data.get("watch", {}).get("total_videos", 0),
            "youtube_channels": raw_data.get("watch", {}).get("unique_channels", 0),
            "subscriptions": raw_data.get("subs", {}).get("total", 0),
            "playlists": raw_data.get("playlists", {}).get("total_playlists", 0),
        },
        "analysis": analysis["analysis"],
    }
    
    json_path = MIRROR_DIR / "profile.json"
    json_path.write_text(json.dumps(profile, indent=2))
    
    # Readable report
    md = f"""# 🪞 Mirror — Behavioral Profile
*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*
*Lens: {analysis['lens']}*
*Data: {profile['data_sources']['youtube_videos']} videos, {profile['data_sources']['youtube_channels']} channels, {profile['data_sources']['subscriptions']} subscriptions*

---

{analysis['analysis']}
"""
    
    md_path = MIRROR_DIR / "profile.md"
    md_path.write_text(md)
    
    print(f"💾 Profile saved:")
    print(f"   {json_path}")
    print(f"   {md_path}")
    
    return md_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Mirror — Behavioral Profile Analyzer")
    parser.add_argument("--quick", action="store_true", help="Top-level summary only")
    parser.add_argument("--lens", choices=["career", "interests", "personality", "prospects"],
                        help="Focus analysis on specific dimension")
    parser.add_argument("--status", action="store_true", help="Show existing profile")
    args = parser.parse_args()

    if args.status:
        md_path = MIRROR_DIR / "profile.md"
        if md_path.exists():
            print(md_path.read_text())
        else:
            print("No profile yet. Run: python3 mirror.py")
        return

    print("🪞 MIRROR — Behavioral Profile Analyzer")
    print("=" * 50)
    
    # Load all data
    print("📊 Loading data sources...")
    history = load_youtube_history()
    channels = load_youtube_channels()
    subs = load_youtube_subscriptions()
    playlists_raw = load_youtube_playlists()
    
    print(f"   YouTube: {len(history)} videos, {len(channels)} channels, {len(subs)} subs")
    
    if not history and not subs:
        print("⚠️ No data loaded. Run YouTube data import first.")
        return
    
    # Analyze
    print("🔍 Analyzing patterns...")
    watch_analysis = analyze_watch_patterns(history)
    playlist_analysis = analyze_playlists(playlists_raw)
    sub_analysis = analyze_subscriptions(subs)
    
    # Build summary for LLM
    data_summary = build_data_summary(watch_analysis, playlist_analysis, sub_analysis)
    
    if args.quick:
        print("\n" + data_summary)
        return
    
    raw_data = {
        "watch": watch_analysis,
        "playlists": playlist_analysis,
        "subs": sub_analysis,
    }
    
    # Run LLM analysis
    result = run_analysis(data_summary, lens=args.lens)
    
    # Save
    report_path = save_report(result, raw_data)
    
    print(f"\n{'=' * 50}")
    print(result["analysis"])


if __name__ == "__main__":
    main()
