#!/usr/bin/env python3
"""
jackal.py — Lateral Scavenger Agent

Runs AFTER Wolf (hunter.py). Finds what Wolf was too focused to see.
Works with Wolf's cached output + knowledge base, and can chase connections via AgentSearch.

Three Lenses:
  1. Carcass Picker — Re-read Wolf's sources ignoring the hunt question
  2. Thread Finder  — See all kills at once, find cross-connections
  3. Archaeologist  — Connect new findings to old knowledge base (--deep only)

Connection Chasing:
  - When high-confidence connections are found, searches for more information
  - Can emit hunt suggestions for Wolf to pick up via --emit-hunts

Usage:
    python3 jackal.py                    # Scavenge last hunt
    python3 jackal.py --hunt-id abc123   # Scavenge specific hunt
    python3 jackal.py --deep             # Include archaeology
    python3 jackal.py --emit-hunts       # Write next hunts to state/hunts/next-hunts.json
    python3 jackal.py --status           # Show jackal reports
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from api import call_claude
from fetch import _sanitize_content

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
HUNTS_DIR = STATE_DIR / "hunts"
HUNTS_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config() -> dict:
    defaults = {
        "max_sources_to_reexamine": 5,
        "knowledge_lookback_days": 30,
        "min_connection_confidence": 0.6,
    }
    p = CEO_DIR / "config" / "hunt-config.json"
    if p.exists():
        try:
            cfg = json.loads(p.read_text())
            defaults.update(cfg.get("jackal", {}))
        except Exception:
            pass
    return defaults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def find_latest_hunt() -> str | None:
    """Find the most recent hunt by timestamp in the JSON."""
    best_id, best_time = None, ""
    for f in HUNTS_DIR.glob("*.json"):
        name = f.stem
        if "-" in name:  # skip adjacent, sources, jackal files
            continue
        try:
            d = json.loads(f.read_text())
            t = d.get("started_at", d.get("updated_at", ""))
            if t > best_time:
                best_time = t
                best_id = name
        except Exception:
            continue
    return best_id


def _sanitize_hunt_id(hunt_id: str) -> str:
    """Ensure hunt_id is safe for use in filenames."""
    import re
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '', hunt_id)
    return clean[:32] if clean else "unknown"


def load_hunt(hunt_id: str) -> dict | None:
    hunt_id = _sanitize_hunt_id(hunt_id)
    p = HUNTS_DIR / f"{hunt_id}.json"
    if not p.exists():
        return None
    try:
        p.resolve().relative_to(HUNTS_DIR.resolve())
    except ValueError:
        return None
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        return None
    return data


def load_sources(hunt_id: str) -> dict | None:
    hunt_id = _sanitize_hunt_id(hunt_id)
    p = HUNTS_DIR / f"{hunt_id}-sources.json"
    if not p.exists():
        return None
    try:
        p.resolve().relative_to(HUNTS_DIR.resolve())
    except ValueError:
        return None
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        return None
    return data


def load_synthesis(hunt_id: str) -> str | None:
    p = HUNTS_DIR / f"{hunt_id}-synthesis.md"
    if not p.exists():
        return None
    return p.read_text()


MAX_FRAMEWORK_FILES = 500       # Cap on files to read
MAX_FRAMEWORK_FILE_SIZE = 50000  # 50KB per file
MAX_FRAMEWORKS_TOTAL = 1000      # Cap on total frameworks loaded


def load_all_frameworks() -> list[dict]:
    """Load all knowledge base frameworks with safety limits."""
    frameworks = []
    if not KNOWLEDGE_DIR.exists():
        return frameworks
    files_read = 0
    for f in KNOWLEDGE_DIR.rglob("*.json"):
        if files_read >= MAX_FRAMEWORK_FILES:
            break
        if f.name.startswith("_"):
            continue
        # Path traversal guard: ensure file is inside KNOWLEDGE_DIR
        try:
            f.resolve().relative_to(KNOWLEDGE_DIR.resolve())
        except ValueError:
            continue
        # Size guard
        try:
            if f.stat().st_size > MAX_FRAMEWORK_FILE_SIZE:
                continue
        except OSError:
            continue
        try:
            data = json.loads(f.read_text())
            files_read += 1
            if isinstance(data, dict) and data.get("name"):
                data["_path"] = str(f.relative_to(KNOWLEDGE_DIR))
                frameworks.append(data)
            elif isinstance(data, list):
                for item in data[:50]:  # Cap items per file
                    if isinstance(item, dict) and item.get("name"):
                        item["_path"] = str(f.relative_to(KNOWLEDGE_DIR))
                        frameworks.append(item)
            if len(frameworks) >= MAX_FRAMEWORKS_TOTAL:
                break
        except Exception:
            continue
    return frameworks


def extract_json(text: str) -> any:
    """Try to parse JSON from LLM response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # skip ```json
        end = next((i for i, l in enumerate(lines) if l.strip() == "```"), len(lines))
        text = "\n".join(lines[:end])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in the text
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            s = text.find(start_char)
            e = text.rfind(end_char)
            if s != -1 and e != -1 and e > s:
                try:
                    return json.loads(text[s:e + 1])
                except json.JSONDecodeError:
                    continue
        return None


# ---------------------------------------------------------------------------
# Lens 1: Carcass Picker
# ---------------------------------------------------------------------------
def pick_carcasses(hunt: dict, sources: dict, config: dict) -> list[dict]:
    """Re-examine Wolf's cached sources for overlooked insights."""
    question = hunt.get("question", "")
    findings = hunt.get("findings", hunt.get("kills", []))
    
    # Map source URLs to their extracted framework names
    url_frameworks = {}
    for f in findings:
        url = f.get("url", "")
        fw_raw = f.get("frameworks", [])
        if isinstance(fw_raw, list):
            names = [fw.get("name", "") for fw in fw_raw if isinstance(fw, dict)]
        else:
            names = []
        url_frameworks[url] = names

    max_sources = config.get("max_sources_to_reexamine", 5)
    results = []
    examined = 0

    for url, src in list(sources.items())[:max_sources]:
        content = src.get("content", "")
        if not content or len(content) < 200:
            continue
        # Sanitize cached content (may pre-date fetch.py sanitization)
        content = _sanitize_content(content)
        
        title = src.get("title", url)
        extracted_names = url_frameworks.get(url, src.get("frameworks_extracted", []))

        system = """You are re-examining content that was already analyzed for a specific research question.
The previous analysis extracted frameworks relevant to that question. Your job is DIFFERENT.

Ignore the original question entirely. Instead find:
1. TANGENTIAL: Something mentioned in passing that deserves its own investigation
2. METHODOLOGY: How does the author think? What reasoning patterns do they use?
3. ASSUMPTIONS: What does the author take as given that might be wrong?
4. CROSS_FIELD: What would an expert from a completely unrelated field notice here?

Output a JSON array of discoveries. Each: {"type": "...", "insight": "...", "quote": "...", "why_it_matters": "..."}
If there's nothing interesting, return an empty array []. Don't force it. Max 3 items."""

        user = f"""ORIGINAL QUESTION (for context only — do NOT answer this):
{question}

WHAT WAS ALREADY EXTRACTED:
{json.dumps(extracted_names)}

SOURCE ({title}):
{content[:8000]}"""

        try:
            print(f"  🦴 Picking: {title[:60]}...")
            raw = call_claude(system, user, model=MODEL, max_tokens=2048)
            parsed = extract_json(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    item["source_title"] = title
                    item["source_url"] = url
                results.extend(parsed)
            examined += 1
        except Exception as e:
            print(f"  ⚠️ Carcass pick failed for {title[:40]}: {e}")
            examined += 1

    print(f"  📊 Examined {examined} sources, found {len(results)} overlooked insights")
    return results


# ---------------------------------------------------------------------------
# Lens 2: Thread Finder
# ---------------------------------------------------------------------------
def find_threads(hunt: dict) -> dict:
    """Find cross-connections across all of Wolf's kills."""
    findings = hunt.get("findings", hunt.get("kills", []))
    question = hunt.get("question", "")

    # Build summary of all kills
    kill_summaries = []
    for f in findings:
        title = f.get("title", f.get("url", "unknown"))
        frameworks_raw = f.get("frameworks", [])
        insight = f.get("key_insight", "")
        changes = f.get("changes_understanding", "")
        # Handle both list-of-dicts and integer formats
        if isinstance(frameworks_raw, list):
            fw_names = [fw.get("name", "") for fw in frameworks_raw if isinstance(fw, dict)]
            fw_descs = [fw.get("description", "")[:150] for fw in frameworks_raw[:5] if isinstance(fw, dict)]
        else:
            fw_names = []
            fw_descs = []
        kill_summaries.append({
            "source": title,
            "frameworks": fw_names,
            "key_insight": insight,
            "changes_understanding": changes,
        })

    if not kill_summaries:
        return {}

    system = """You are examining multiple research sources that were analyzed independently for the same question.
Your job: find CONNECTIONS and PATTERNS that aren't visible when reading them one at a time.

Look for:
- TRANSLATIONS: Same concept, different words across sources
- SUPPLY_CHAINS: Hidden dependencies (A needs B needs C — who builds C?)
- SILENT_DOGS: What should ALL these sources discuss but none do?
- CONVERGENCE: Multiple sources pointing at the same conclusion from different angles
- CONTRADICTIONS: Where sources disagree — and WHY they might disagree

Output JSON:
{
  "translations": [{"insight": "...", "sources": [...], "confidence": 0.0-1.0, "significance": "high/medium/low"}],
  "supply_chains": [{"insight": "...", "sources": [...], "confidence": 0.0-1.0, "significance": "high/medium/low"}],
  "silent_dogs": [{"insight": "...", "sources": [...], "confidence": 0.0-1.0, "significance": "high/medium/low"}],
  "convergence": [{"insight": "...", "sources": [...], "confidence": 0.0-1.0, "significance": "high/medium/low"}],
  "contradictions": [{"insight": "...", "sources": [...], "confidence": 0.0-1.0, "significance": "high/medium/low"}]
}
Keep each category to max 3 items. Only report genuinely interesting findings."""

    user = f"""HUNT QUESTION: {question}

ALL KILLS ({len(kill_summaries)} sources):
{json.dumps(kill_summaries, indent=1)}"""

    print(f"  🧵 Finding threads across {len(kill_summaries)} kills...")
    raw = call_claude(system, user, model=MODEL, max_tokens=4096)
    parsed = extract_json(raw)
    if isinstance(parsed, dict):
        total = sum(len(v) for v in parsed.values() if isinstance(v, list))
        print(f"  📊 Found {total} cross-connections")
        return parsed
    return {}


# ---------------------------------------------------------------------------
# Lens 3: Archaeologist
# ---------------------------------------------------------------------------
def dig_archaeology(hunt: dict, config: dict) -> list[dict]:
    """Connect new findings to old knowledge base frameworks."""
    findings = hunt.get("findings", hunt.get("kills", []))
    question = hunt.get("question", "")

    # Collect new framework names and keywords
    new_frameworks = []
    new_keywords = set()
    for f in findings:
        fw_raw = f.get("frameworks", [])
        if not isinstance(fw_raw, list):
            continue
        for fw in fw_raw:
            if not isinstance(fw, dict):
                continue
            new_frameworks.append({
                "name": fw.get("name", ""),
                "description": fw.get("description", "")[:200],
                "domain": fw.get("domain", ""),
                "source": f.get("title", ""),
            })
            # Extract keywords from name and description
            text = f"{fw.get('name', '')} {fw.get('description', '')} {fw.get('domain', '')}".lower()
            words = set(w for w in text.split() if len(w) > 3)
            new_keywords.update(words)

    if not new_frameworks:
        print("  📊 No new frameworks to connect")
        return []

    # Step 1: Keyword matching (no LLM)
    all_kb = load_all_frameworks()
    if not all_kb:
        print("  📊 Knowledge base empty, skipping archaeology")
        return []

    related_old = []
    for fw in all_kb:
        text = f"{fw.get('name', '')} {fw.get('description', '')} {fw.get('domain', '')}".lower()
        overlap = sum(1 for kw in new_keywords if kw in text)
        if overlap >= 2:
            related_old.append({
                "name": fw.get("name", ""),
                "description": fw.get("description", "")[:200],
                "domain": fw.get("domain", ""),
                "source": fw.get("source", ""),
                "overlap_score": overlap,
            })

    related_old.sort(key=lambda x: x["overlap_score"], reverse=True)
    related_old = related_old[:15]

    if not related_old:
        print("  📊 No keyword matches found in knowledge base")
        return []

    # Step 2: Sonnet call for meaningful connections
    system = """You are connecting NEW research findings to OLDER knowledge from previous hunts.
The old knowledge was collected days or weeks ago for different questions.
Find connections that only become visible NOW with the new findings.

Look for:
- COMPLETED_PUZZLE: Old fragment + new fragment = complete picture
- EVOLVED: What we thought before — does new data confirm or challenge it?
- DORMANT: Old knowledge that seemed unimportant but now matters
- ACCELERATION: A trend noticed before that's now moving faster/slower

Output JSON array: [{"type": "...", "old_framework": "...", "new_framework": "...", "connection": "...", "significance": "high/medium/low"}]
Only report genuinely surprising connections. Max 5 items."""

    user = f"""HUNT QUESTION: {question}

NEW FRAMEWORKS (from this hunt):
{json.dumps(new_frameworks[:10], indent=1)}

RELATED OLD FRAMEWORKS (from knowledge base):
{json.dumps(related_old, indent=1)}"""

    print(f"  🏺 Digging connections: {len(new_frameworks)} new × {len(related_old)} old...")
    raw = call_claude(system, user, model=MODEL, max_tokens=3072)
    parsed = extract_json(raw)
    if isinstance(parsed, list):
        print(f"  📊 Found {len(parsed)} archaeological connections")
        return parsed
    return []


# ---------------------------------------------------------------------------
# Connection Chaser
# ---------------------------------------------------------------------------
def chase_connections(hunt: dict, threads: dict, carcass_picks: list) -> list[dict]:
    """When Jackal finds a cross-connection worth pursuing, search for it."""
    import requests
    
    next_hunts = []
    
    # From thread finder - if there are strong connections, search for more
    connections = threads.get("connections", [])
    for category_name, category_items in threads.items():
        if not isinstance(category_items, list):
            continue
        for conn in category_items:
            if conn.get("confidence", 0) >= 0.7:  # Only chase high-confidence connections
                query = conn.get("suggested_query", conn.get("insight", ""))
                if query and len(query) > 5:
                    try:
                        r = requests.get("http://localhost:3939/search/extract", 
                                        params={"q": query[:80], "count": 3}, timeout=30)
                        if r.ok:
                            data = r.json()
                            results = data.get("results", [])
                            if results:
                                next_hunts.append({
                                    "query": query,
                                    "source": "jackal_thread",
                                    "connection": conn.get("insight", ""),
                                    "results": results[:3],
                                    "confidence": conn.get("confidence", 0)
                                })
                    except Exception:
                        pass
    
    # From carcass picks - if tangential findings are strong, search for more
    for pick in carcass_picks:
        if pick.get("type") == "TANGENTIAL" and pick.get("why_it_matters"):
            query = pick["insight"][:80]
            try:
                r = requests.get("http://localhost:3939/search/extract",
                                params={"q": query, "count": 2}, timeout=30)
                if r.ok:
                    data = r.json()
                    results = data.get("results", [])
                    if results:
                        next_hunts.append({
                            "query": query,
                            "source": "jackal_carcass",
                            "insight": pick["insight"],
                            "results": results[:2],
                            "confidence": 0.6
                        })
            except Exception:
                pass
    
    return next_hunts


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------
def generate_report(hunt_id: str, question: str, overlooked: list, connected: dict,
                    resurfaced: list, deep: bool) -> str:
    """Generate the markdown scavenger report."""
    lines = [
        f"# 🦊 Jackal Report — Hunt {hunt_id}",
        f'## After Wolf\'s hunt: "{question}"',
        f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
    ]

    # OVERLOOKED
    lines.append("### OVERLOOKED")
    lines.append("*Things in Wolf's sources that nobody asked about:*")
    lines.append("")
    if overlooked:
        for item in overlooked:
            t = item.get("type", "tangential").upper()
            lines.append(f"- **[{t}]** {item.get('insight', 'N/A')}")
            if item.get("quote"):
                lines.append(f'  > "{item["quote"][:200]}"')
            lines.append(f"  *Source: {item.get('source_title', 'unknown')}*")
            if item.get("why_it_matters"):
                lines.append(f"  Why it matters: {item['why_it_matters']}")
            lines.append("")
    else:
        lines.append("*No sources.json available or nothing overlooked.*\n")

    # CONNECTED
    lines.append("### CONNECTED")
    lines.append("*Patterns across Wolf's kills:*")
    lines.append("")
    if connected:
        for category, items in connected.items():
            if not isinstance(items, list) or not items:
                continue
            label = category.upper().replace("_", " ")
            for item in items:
                sources = ", ".join(str(s) for s in item.get("sources", []))
                lines.append(f"- **{label}**: {item.get('insight', 'N/A')}")
                if sources:
                    lines.append(f"  *Sources: {sources}*")
                lines.append("")
    else:
        lines.append("*No cross-connections found.*\n")

    # RESURFACED
    lines.append("### RESURFACED")
    lines.append("*Old knowledge that just became relevant:*")
    lines.append("")
    if resurfaced:
        for item in resurfaced:
            lines.append(f"- **{item.get('type', 'connection').upper()}**: "
                        f"{item.get('old_framework', '?')} ↔ {item.get('new_framework', '?')}")
            lines.append(f"  {item.get('connection', '')}")
            lines.append("")
    else:
        if deep:
            lines.append("*No archaeological connections found.*\n")
        else:
            lines.append("*Run with --deep to enable archaeology.*\n")

    # SUSPICIONS (derived from silent dogs + assumptions)
    lines.append("### SUSPICIONS")
    lines.append("*Consensus without evidence:*")
    lines.append("")
    suspicions = []
    # From overlooked assumptions
    for item in overlooked:
        if item.get("type", "").lower() in ("assumptions", "assumption"):
            suspicions.append(item.get("insight", ""))
    # From silent dogs
    for item in connected.get("silent_dogs", []):
        suspicions.append(item.get("insight", ""))
    if suspicions:
        for s in suspicions:
            lines.append(f"- {s}")
        lines.append("")
    else:
        lines.append("*No suspicions flagged.*\n")

    # NEXT HUNTS
    lines.append("### NEXT HUNTS")
    lines.append("*Questions Wolf should chase next:*")
    lines.append("")
    next_hunts = _derive_next_hunts(overlooked, connected, resurfaced)
    if next_hunts:
        for i, q in enumerate(next_hunts, 1):
            lines.append(f"{i}. {q}")
        lines.append("")
    else:
        lines.append("*No follow-up hunts suggested.*\n")

    return "\n".join(lines)


def _derive_next_hunts(overlooked: list, connected: dict, resurfaced: list) -> list[str]:
    """Derive suggested next hunts from findings."""
    hunts = []
    # From tangential insights
    for item in overlooked:
        if item.get("type", "").lower() == "tangential" and item.get("why_it_matters"):
            hunts.append(f"Investigate: {item['insight'][:100]}")
    # From silent dogs
    for item in connected.get("silent_dogs", []):
        hunts.append(f"Why is nobody discussing: {item.get('insight', '')[:100]}?")
    # From contradictions
    for item in connected.get("contradictions", []):
        hunts.append(f"Resolve contradiction: {item.get('insight', '')[:100]}")
    # From archaeology
    for item in resurfaced:
        if item.get("type", "").lower() == "completed_puzzle":
            hunts.append(f"Complete the puzzle: {item.get('connection', '')[:100]}")
    return hunts[:5]


def build_structured_output(hunt_id: str, question: str, overlooked: list,
                            connected: dict, resurfaced: list, metrics: dict) -> dict:
    """Build the structured JSON output."""
    suspicions = []
    for item in overlooked:
        if item.get("type", "").lower() in ("assumptions", "assumption"):
            suspicions.append(item.get("insight", ""))
    for item in connected.get("silent_dogs", []):
        suspicions.append(item.get("insight", ""))

    return {
        "hunt_id": hunt_id,
        "wolf_question": question,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overlooked": overlooked,
        "connected": connected,
        "resurfaced": resurfaced,
        "suspicions": suspicions,
        "next_hunts": _derive_next_hunts(overlooked, connected, resurfaced),
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def show_status():
    """Show existing jackal reports."""
    reports = sorted(HUNTS_DIR.glob("*-jackal.json"))
    if not reports:
        print("🦊 No Jackal reports yet.")
        return

    print(f"🦊 Jackal Reports ({len(reports)}):\n")
    for r in reports:
        try:
            d = json.loads(r.read_text())
            hunt_id = d.get("hunt_id", r.stem.replace("-jackal", ""))
            q = d.get("wolf_question", "?")[:60]
            m = d.get("metrics", {})
            print(f"  {hunt_id}: \"{q}\"")
            print(f"    Overlooked: {m.get('overlooked_count', '?')} | "
                  f"Connections: {m.get('connections_found', '?')} | "
                  f"Resurfaced: {m.get('resurfaced_count', '?')} | "
                  f"Cost: ${m.get('cost', 0):.2f}")
        except Exception:
            print(f"  {r.stem}: (error reading)")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_jackal(hunt_id: str | None = None, deep: bool = False, emit_hunts: bool = False):
    """Run Jackal scavenger on a hunt."""
    # Resolve hunt
    if not hunt_id:
        hunt_id = find_latest_hunt()
    if not hunt_id:
        print("❌ No hunts found.")
        sys.exit(1)

    hunt = load_hunt(hunt_id)
    if not hunt:
        print(f"❌ Hunt {hunt_id} not found.")
        sys.exit(1)

    question = hunt.get("question", "unknown")
    findings = hunt.get("findings", hunt.get("kills", []))

    print(f"🦊 Jackal scavenging hunt {hunt_id}")
    print(f"   Question: \"{question[:80]}\"")
    print(f"   Wolf findings: {len(findings)}")
    print()

    if not findings:
        print("Nothing to scavenge — Wolf found zero findings.")
        return

    # Track metrics
    metrics = {
        "sources_reexamined": 0,
        "overlooked_count": 0,
        "connections_found": 0,
        "resurfaced_count": 0,
        "cost": 0.0,
    }

    # Lens 1: Carcass Picker
    overlooked = []
    sources = load_sources(hunt_id)
    try:
        if sources:
            print("🦴 Lens 1: Carcass Picker")
            config = load_config()
            overlooked = pick_carcasses(hunt, sources, config)
            metrics["sources_reexamined"] = min(len(sources), config.get("max_sources_to_reexamine", 5))
            metrics["overlooked_count"] = len(overlooked)
            # Rough cost: ~$0.01 per source call
            metrics["cost"] += metrics["sources_reexamined"] * 0.01
            print()
        else:
            print("🦴 Lens 1: Carcass Picker — SKIPPED (no sources.json for this hunt)")
            print("   Wolf didn't cache source content. Run a new hunt with Wolf v2 for full Jackal.\n")
    except Exception as e:
        print(f"⚠️ Carcass Picker failed: {e}\n")

    # Lens 2: Thread Finder
    connected = {}
    try:
        print("🧵 Lens 2: Thread Finder")
        connected = find_threads(hunt)
        total_connections = sum(len(v) for v in connected.values() if isinstance(v, list))
        metrics["connections_found"] = total_connections
        metrics["cost"] += 0.02  # Single Sonnet call
        print()
    except Exception as e:
        print(f"⚠️ Thread Finder failed: {e}\n")

    # Lens 3: Archaeologist (--deep only)
    resurfaced = []
    if deep:
        try:
            print("🏺 Lens 3: Archaeologist")
            config = load_config()
            resurfaced = dig_archaeology(hunt, config)
            metrics["resurfaced_count"] = len(resurfaced)
            metrics["cost"] += 0.02  # keyword match + one Sonnet call
            print()
        except Exception as e:
            print(f"⚠️ Archaeologist failed: {e}\n")

    # Connection Chaser - chase high-confidence connections
    next_hunts = []
    try:
        print("🔍 Connection Chaser")
        next_hunts = chase_connections(hunt, connected, overlooked)
        if next_hunts:
            print(f"  📊 Found {len(next_hunts)} follow-up hunts")
            # Add to structured output
            metrics["chases_found"] = len(next_hunts)
        else:
            print("  📊 No high-confidence connections to chase")
        print()
    except Exception as e:
        print(f"⚠️ Connection Chaser failed: {e}\n")

    # Generate outputs
    report = generate_report(hunt_id, question, overlooked, connected, resurfaced, deep)
    structured = build_structured_output(hunt_id, question, overlooked, connected, resurfaced, metrics)
    
    # Add chases to structured output
    if next_hunts:
        structured["chases"] = next_hunts

    # Save
    report_path = HUNTS_DIR / f"{hunt_id}-jackal.md"
    json_path = HUNTS_DIR / f"{hunt_id}-jackal.json"
    report_path.write_text(report)
    json_path.write_text(json.dumps(structured, indent=2))

    # Emit next hunts if requested
    if emit_hunts and next_hunts:
        hunts_path = HUNTS_DIR / "next-hunts.json"
        # Make sure the directory exists
        HUNTS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Write the hunts file for Wolf to pick up
        hunts_path.write_text(json.dumps(next_hunts, indent=2))
        print(f"📋 Next hunts written to: {hunts_path}")
        print(f"   {len(next_hunts)} hunts ready for Wolf")

    print(f"✅ Jackal report saved:")
    print(f"   {report_path}")
    print(f"   {json_path}")
    print(f"   Cost: ~${metrics['cost']:.2f}")
    print(f"   Overlooked: {metrics['overlooked_count']} | "
          f"Connected: {metrics['connections_found']} | "
          f"Resurfaced: {metrics['resurfaced_count']}")
    if next_hunts:
        print(f"   Chases: {len(next_hunts)}")


def main():
    parser = argparse.ArgumentParser(description="🦊 Jackal — Lateral Scavenger Agent")
    parser.add_argument("--hunt-id", help="Scavenge a specific hunt")
    parser.add_argument("--deep", action="store_true", help="Include archaeology lens")
    parser.add_argument("--emit-hunts", action="store_true", help="Write next hunt queries to state/hunts/next-hunts.json")
    parser.add_argument("--status", action="store_true", help="Show jackal reports")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    run_jackal(hunt_id=args.hunt_id, deep=args.deep, emit_hunts=args.emit_hunts)


if __name__ == "__main__":
    main()
