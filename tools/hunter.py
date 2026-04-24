#!/usr/bin/env python3
"""
hunter.py — Wolf (Hunter v2)

Predator-model research engine. Replaces the v1 "vacuum cleaner" with
a wolf that stalks, tests, commits or abandons, and eats organs first.

Phases:
  0. TERRITORY — Scan existing knowledge, identify gaps
  1. STALK    — Search, score results against gaps, select top targets
  2. TEST BITE — Fetch 1K chars per target, quick commit/abandon
  3. KILL      — Full extraction on committed targets only (organ > meat > bone)
  4. FEED      — Wolf-style synthesis: what changed, gaps closed/opened

Usage:
    python3 hunter.py "How do digital twins work in manufacturing?"
    python3 hunter.py "question" --budget 0.50 --sources 15 --depth 2
    python3 hunter.py --resume
    python3 hunter.py --status
"""

import argparse
import gc
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api import call_claude, get_api_key
from fetch import _sanitize_content, _is_safe_url

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
TOOLS_DIR = CEO_DIR / "tools"
HUNTS_DIR = STATE_DIR / "hunts"
HUNTS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "claude-sonnet-4-5-20250929"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load hunt config with wolf defaults."""
    config = {
        "default_budget": 0.5,
        "default_max_sources": 15,
        "default_max_depth": 2,
        "max_content_chars": 15000,
        "search_queries_per_hunt": 6,
        "youtube_queries_per_hunt": 2,
        "youtube_weight": 0.6,
        "blocked_domains": [],
        "preferred_domains": [],
        "max_results_per_query": 6,
        "search_timeout_sec": 15,
        # Wolf-specific
        "max_targets": 7,
        "bite_chars": 1000,
        "min_bite_score": 6,
        "budget_split": {
            "territory": 0.05,
            "stalk": 0.15,
            "bite": 0.20,
            "kill": 0.50,
            "feed": 0.10,
        },
    }
    for name in ("hunt-config.json", "search-config.json"):
        p = CEO_DIR / "config" / name
        if p.exists():
            try:
                config.update(json.loads(p.read_text()))
            except Exception:
                pass
    return config


_CONFIG = load_config()

# ---------------------------------------------------------------------------
# Utility functions (preserved interface)
# ---------------------------------------------------------------------------


def search(query: str, limit: int = None) -> list[dict]:
    """Search via Research Engine (multi-source: web + scholar + OpenAlex)."""
    from research_engine import research as multi_search

    if limit is None:
        limit = _CONFIG.get("max_results_per_query", 6)
    try:
        results = multi_search(query, max_results=limit * 2, include_content=False)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
                "source_type": r.get("source_type", "web"),
            }
            for r in results
        ]
    except Exception as e:
        print(f"   ⚠️ Research engine failed: {e}, falling back to AgentSearch")
        # Fallback to direct AgentSearch
        import requests
        try:
            r = requests.get(
                "http://localhost:3939/search",
                params={"q": query[:80], "count": limit},
                timeout=15,
            )
            if r.ok:
                data = r.json()
                results = data if isinstance(data, list) else data.get("results", [])
                return [{"title": x.get("title",""), "url": x.get("url",""), "snippet": x.get("snippet","")} for x in results]
        except Exception:
            pass
    return []


def search_extract(query: str, limit: int = None) -> list[dict]:
    """Search via Research Engine with content extraction."""
    from research_engine import research as multi_search

    if limit is None:
        limit = _CONFIG.get("max_results_per_query", 6)
    try:
        results = multi_search(query, max_results=limit, include_content=True)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
                "content": r.get("content", ""),
                "source_type": r.get("source_type", "web"),
            }
            for r in results
        ]
    except Exception as e:
        print(f"   ⚠️ Research engine extract failed: {e}")
    return []


def search_youtube(query: str, limit: int = 5) -> list[dict]:
    """Search YouTube via yt-dlp."""
    yw = _CONFIG.get("youtube_weight", 0.6)
    if yw == 0:
        return []
    # Sanitize query — strip shell metacharacters and limit length
    query = re.sub(r'[;&|`$(){}[\]<>!#]', '', query)[:120]
    scaled = max(1, int(limit * yw))
    try:
        cmd = [
            "yt-dlp",
            f"ytsearch{scaled}:{query}",
            "--flat-playlist",
            "--print",
            "%(id)s\t%(title)s\t%(duration)s",
            "--no-download",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        videos = []
        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                videos.append(
                    {
                        "title": parts[1],
                        "url": f"https://www.youtube.com/watch?v={parts[0]}",
                        "duration": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
                        "source_type": "youtube",
                    }
                )
        return videos
    except Exception:
        return []


def fetch_content(url: str, max_chars: int = None, title: str = None) -> str | None:
    """Fetch content via smart content adapter (academic-aware, PDF extraction, Unpaywall).
    Falls back to legacy kill chain if content adapter fails."""
    try:
        from content_adapter import extract_content
        result = extract_content(url, title=title, max_chars=max_chars or 15000)
        if result.get("success"):
            content = result.get("content", "")
            if content and max_chars:
                content = content[:max_chars]
            return content
    except Exception as e:
        print(f"      ⚠️ Content adapter error: {e}, falling back to kill chain")

    # Fallback to legacy kill chain
    try:
        from fetch import kill_chain
        content = kill_chain(url, verbose=False)
        if content and max_chars:
            content = content[:max_chars]
        return content
    except Exception:
        return None


def _sanitize_path_component(name: str, fallback: str = "general") -> str:
    """Sanitize a string for use as a directory/file name. Prevents path traversal."""
    # Strip path separators and dangerous characters
    clean = re.sub(r'[/\\\.]{2,}', '', name)  # no ../ or ..\
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '-', clean)  # whitelist safe chars
    clean = clean.strip('-').lower()
    if not clean or clean in ('.', '..'):
        return fallback
    return clean[:64]  # cap length


def save_frameworks(frameworks: list, source: dict, hunt_id: str) -> int:
    """Save extracted frameworks to knowledge base. Returns count saved."""
    saved = 0
    for fw in frameworks:
        fw_id = str(uuid.uuid4())[:8]
        domain = _sanitize_path_component(fw.get("domain", "general"))
        domain_dir = KNOWLEDGE_DIR / domain
        # Path traversal guard: ensure we stay inside KNOWLEDGE_DIR
        try:
            domain_dir.resolve().relative_to(KNOWLEDGE_DIR.resolve())
        except ValueError:
            print(f"   🛡️ BLOCKED: path traversal attempt in domain '{fw.get('domain', '')}'")
            continue
        domain_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "id": fw_id,
            "type": fw.get("type", "framework"),
            "name": fw.get("name", "unnamed"),
            "description": fw.get("description", ""),
            "domain": domain,
            "confidence": fw.get("confidence", 0.5),
            "tags": fw.get("tags", []),
            "raw_quote": fw.get("raw_quote", ""),
            "value_tier": fw.get("value_tier", "bone"),
            "source": {
                "title": source.get("title", ""),
                "url": source.get("url", ""),
            },
            "hunt_id": hunt_id,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        (domain_dir / f"{fw_id}.json").write_text(json.dumps(entry, indent=2))
        saved += 1
    return saved


# ---------------------------------------------------------------------------
# Hunt — Wolf model
# ---------------------------------------------------------------------------


class Hunt:
    """A wolf-model research hunt with 5 phases."""

    def __init__(
        self,
        question: str,
        hunt_id: str = None,
        max_depth: int = None,
        max_sources: int = None,
        budget: float = None,
    ):
        self.question = question
        self.hunt_id = hunt_id or str(uuid.uuid4())[:8]
        self.max_depth = max_depth if max_depth is not None else _CONFIG.get("default_max_depth", 2)
        self.max_sources = max_sources if max_sources is not None else _CONFIG.get("default_max_sources", 15)
        self.budget = budget if budget is not None else _CONFIG.get("default_budget", 0.50)
        self.cost = 0.0
        self.started_at = None
        self.state_file = HUNTS_DIR / f"{self.hunt_id}.json"

        # Wolf state
        self.gaps: list[dict] = []          # {id, description, status}
        self.stalked: list[dict] = []       # search results + scores
        self.bitten: list[dict] = []        # test-bite results
        self.kills: list[dict] = []         # full extractions
        self.findings: list[dict] = []      # summary log per source

        # Jackal source cache
        self.source_cache: dict = {}

        # Wolf metrics
        self.metrics = {
            "targets_stalked": 0,
            "targets_committed": 0,
            "targets_abandoned": 0,
            "organs_found": 0,
            "meat_found": 0,
            "bones_found": 0,
            "gaps_identified": 0,
            "gaps_closed": 0,
            "frameworks_saved": 0,
        }

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self):
        state = {
            "hunt_id": self.hunt_id,
            "question": self.question,
            "started_at": self.started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cost": self.cost,
            "budget": self.budget,
            "metrics": self.metrics,
            "gaps": self.gaps,
            "stalked_count": len(self.stalked),
            "bitten_count": len(self.bitten),
            "kills_count": len(self.kills),
            "findings": self.findings,
            "source_urls": list(self.source_cache.keys()),
        }
        self.state_file.write_text(json.dumps(state, indent=2))

        # Write source cache for Jackal
        if self.source_cache:
            cache_path = HUNTS_DIR / f"{self.hunt_id}-sources.json"
            cache_path.write_text(json.dumps(self.source_cache, indent=2))

    @classmethod
    def load(cls, hunt_id: str) -> "Hunt":
        sf = HUNTS_DIR / f"{hunt_id}.json"
        if not sf.exists():
            raise FileNotFoundError(f"No hunt: {hunt_id}")
        s = json.loads(sf.read_text())
        h = cls(s["question"], hunt_id=hunt_id)
        h.cost = s.get("cost", 0)
        h.budget = s.get("budget", h.budget)
        h.started_at = s.get("started_at")
        h.metrics = s.get("metrics", h.metrics)
        h.gaps = s.get("gaps", [])
        h.findings = s.get("findings", [])
        # Reload source cache if exists
        cache_path = HUNTS_DIR / f"{hunt_id}-sources.json"
        if cache_path.exists():
            try:
                h.source_cache = json.loads(cache_path.read_text())
            except Exception:
                pass
        return h

    # ------------------------------------------------------------------
    # Budget helpers
    # ------------------------------------------------------------------

    def _phase_budget(self, phase: str) -> float:
        split = _CONFIG.get("budget_split", {})
        return self.budget * split.get(phase, 0.10)

    def _estimate_cost(self, input_chars: int) -> float:
        tokens = input_chars // 4
        return (tokens * 3.0 + 1000 * 15.0) / 1_000_000

    def _budget_ok(self, phase: str = None) -> bool:
        if self.cost >= self.budget:
            return False
        if phase:
            phase_limit = sum(
                self.budget * _CONFIG.get("budget_split", {}).get(p, 0.10)
                for p in self._phases_up_to(phase)
            )
            if self.cost >= phase_limit:
                return False
        return True

    @staticmethod
    def _phases_up_to(phase: str) -> list[str]:
        order = ["territory", "stalk", "bite", "kill", "feed"]
        try:
            idx = order.index(phase)
            return order[: idx + 1]
        except ValueError:
            return order

    # ------------------------------------------------------------------
    # Phase 0: TERRITORY
    # ------------------------------------------------------------------

    def phase_territory(self):
        """Scan existing knowledge, identify gaps."""
        print("\n🗺️  Phase 0: TERRITORY — Scanning existing knowledge...\n")

        # Gather existing frameworks relevant to question
        existing_summaries = []
        if KNOWLEDGE_DIR.exists():
            q_lower = self.question.lower()
            q_words = set(
                w
                for w in re.sub(r"[^a-z0-9 ]", " ", q_lower).split()
                if len(w) > 3
            )
            for domain_dir in KNOWLEDGE_DIR.iterdir():
                if not domain_dir.is_dir() or domain_dir.name.startswith("_"):
                    continue
                for fw_file in list(domain_dir.glob("*.json"))[:100]:
                    try:
                        fw = json.loads(fw_file.read_text())
                        text = (fw.get("name", "") + " " + fw.get("description", "")).lower()
                        if sum(1 for w in q_words if w in text) >= 2:
                            existing_summaries.append(
                                f"- {fw.get('name','?')}: {fw.get('description','')[:120]}"
                            )
                    except Exception:
                        continue

        # Scan previous syntheses
        prior_syntheses = []
        for sf in sorted(HUNTS_DIR.glob("*-synthesis.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
            try:
                text = sf.read_text()[:1500]
                prior_syntheses.append(text)
            except Exception:
                continue

        existing_text = "\n".join(existing_summaries[:30]) if existing_summaries else "None found."
        synth_text = "\n---\n".join(prior_syntheses) if prior_syntheses else "No prior syntheses."

        system = """You are a research strategist. Given a question and existing knowledge, identify SPECIFIC gaps — things we don't know yet that matter.

Output JSON:
{
  "gaps": [
    {"id": "gap_1", "description": "What specific unknown we need to fill"},
    ...
  ],
  "search_queries": ["5-8 word search query", ...]
}

Be specific. "How does X work" is bad. "What failure modes exist in X under Y conditions" is good.
Output 4-8 gaps and 4-6 search queries."""

        user = f"""Question: {self.question}

Existing knowledge ({len(existing_summaries)} frameworks):
{existing_text[:3000]}

Prior syntheses (most recent):
{synth_text[:2000]}"""

        try:
            resp = call_claude(system, user, model=MODEL)
            m = re.search(r"\{[\s\S]*\}", resp)
            if m:
                data = json.loads(m.group())
                self.gaps = [
                    {"id": g.get("id", f"gap_{i}"), "description": g["description"], "status": "open"}
                    for i, g in enumerate(data.get("gaps", []))
                ]
                self._territory_queries = data.get("search_queries", [])
            self.cost += 0.01
        except Exception as e:
            print(f"   ⚠️ Territory phase error: {e}")
            self.gaps = [{"id": "gap_0", "description": self.question, "status": "open"}]
            self._territory_queries = []

        self.metrics["gaps_identified"] = len(self.gaps)
        print(f"   Found {len(existing_summaries)} existing frameworks")
        print(f"   Identified {len(self.gaps)} gaps:")
        for g in self.gaps:
            print(f"     🔍 {g['description'][:90]}")
        print()
        self.save_state()

    # ------------------------------------------------------------------
    # Phase 1: STALK
    # ------------------------------------------------------------------

    def phase_stalk(self):
        """Search broadly, score results against gaps, select top targets."""
        print("🐺 Phase 1: STALK — Searching and scoring targets...\n")

        # Build search queries
        queries = list(getattr(self, "_territory_queries", []))
        if not queries:
            # Fallback: generate from question
            if len(self.question) < 60:
                queries = [self.question]
            else:
                try:
                    resp = call_claude(
                        "Output 4 short search queries (5-8 words each) for this research question. One per line, no numbering.",
                        self.question,
                        model=MODEL,
                    )
                    queries = [l.strip().strip("-•") for l in resp.strip().split("\n") if l.strip() and len(l.strip()) > 5][:4]
                    self.cost += 0.005
                except Exception:
                    queries = [self.question[:60]]

        max_q = _CONFIG.get("search_queries_per_hunt", 6)
        yt_q = _CONFIG.get("youtube_queries_per_hunt", 2)

        # Fire multi-source searches via Research Engine
        all_results = []
        seen_urls = set()

        # First query with content extraction, rest without
        for i, q in enumerate(queries[:max_q]):
            include_content = (i == 0)  # Only extract content for first query
            print(f"   🔎{'📄' if include_content else ''} {q}{' (with content)' if include_content else ''}")
            fetcher = search_extract if include_content else search
            for r in fetcher(q, limit=8):
                if r["url"] not in seen_urls and _is_safe_url(r["url"]):
                    seen_urls.add(r["url"])
                    r["query"] = q
                    all_results.append(r)

        for q in queries[:yt_q]:
            print(f"   🎬 YT: {q}")
            for r in search_youtube(q, limit=3):
                if r["url"] not in seen_urls and _is_safe_url(r["url"]):
                    seen_urls.add(r["url"])
                    r["query"] = q
                    all_results.append(r)

        print(f"\n   Found {len(all_results)} unique results")

        if not all_results:
            print("   ⚠️ No search results. Aborting stalk.")
            return

        # Batch-score all results against gaps in a SINGLE LLM call
        gaps_text = "\n".join(f"- [{g['id']}] {g['description']}" for g in self.gaps)
        results_text = "\n".join(
            f"[{i}] TITLE: {r['title'][:100]}\n    SNIPPET: {r.get('snippet','')[:150]}\n    URL: {r['url']}"
            for i, r in enumerate(all_results)
        )

        system = """You are scoring search results against known research gaps.
For each result, output a score 0-10 and which gap it likely addresses.

Score guide:
- 8-10: Title/snippet strongly suggests NEW info that fills a specific gap
- 5-7: Probably relevant, worth a test bite
- 0-4: Generic, SEO filler, or doesn't address any gap

Output JSON:
{"scores": [{"index": 0, "score": 7, "gap_id": "gap_1", "reason": "short reason"}, ...]}

Score ALL results. Be harsh — most web content is thin."""

        user = f"""GAPS:
{gaps_text}

RESULTS:
{results_text[:6000]}"""

        scores = {}
        try:
            resp = call_claude(system, user, model=MODEL)
            m = re.search(r"\{[\s\S]*\}", resp)
            if m:
                data = json.loads(m.group())
                for s in data.get("scores", []):
                    idx = s.get("index", -1)
                    if 0 <= idx < len(all_results):
                        scores[idx] = s
            self.cost += 0.02
        except Exception as e:
            print(f"   ⚠️ Scoring failed: {e}. Selecting top results by position.")

        # Select top targets
        max_targets = _CONFIG.get("max_targets", 7)
        min_score = _CONFIG.get("min_bite_score", 6)

        scored_results = []
        for i, r in enumerate(all_results):
            s = scores.get(i, {})
            score = s.get("score", 5)  # Default 5 if scoring failed
            scored_results.append(
                {
                    "title": r["title"],
                    "url": r["url"],
                    "snippet": r.get("snippet", ""),
                    "score": score,
                    "gap_id": s.get("gap_id", ""),
                    "reason": s.get("reason", ""),
                    "source_type": r.get("source_type", "web"),
                }
            )

        scored_results.sort(key=lambda x: x["score"], reverse=True)
        self.stalked = scored_results

        # Select targets above min_score, capped at max_targets
        targets = [r for r in scored_results if r["score"] >= min_score][:max_targets]
        # If too few, take top max_targets anyway
        if len(targets) < 3:
            targets = scored_results[:max_targets]

        self.metrics["targets_stalked"] = len(targets)

        print(f"\n   Selected {len(targets)} targets (from {len(all_results)} results):")
        for t in targets:
            print(f"     {'🎬' if t['source_type'] == 'youtube' else '📄'} [{t['score']}/10] {t['title'][:65]}")
            if t["reason"]:
                print(f"        → {t['reason'][:80]}")

        self._targets = targets
        print()
        self.save_state()

    # ------------------------------------------------------------------
    # Phase 2: TEST BITE
    # ------------------------------------------------------------------

    def phase_test_bite(self):
        """Fetch first N chars of each target. Commit or abandon."""
        print("🦷 Phase 2: TEST BITE — Quick assessment of targets...\n")

        targets = getattr(self, "_targets", [])
        if not targets:
            print("   No targets to bite.")
            return

        bite_chars = _CONFIG.get("bite_chars", 1000)
        committed = []
        abandoned = []

        for t in targets:
            if not self._budget_ok("bite"):
                print("   💰 Bite budget exhausted.")
                break

            url = t["url"]
            title = t["title"][:60]
            print(f"   🦷 Biting: {title}...")

            # First check if search result already has content from /search/extract
            content = t.get("content", "")
            if content and len(content) >= 100:
                # Use pre-extracted content, truncate to bite_chars
                content = content[:bite_chars]
                print(f"      📄 Using pre-extracted content")
            else:
                # Fall back to fetch_content (with title hint for academic fallback)
                try:
                    content = fetch_content(url, max_chars=bite_chars, title=t.get("title"))
                except Exception as e:
                    print(f"      ⚠️ Fetch failed: {e}")
                    abandoned.append({**t, "verdict": "ABANDON", "reason": f"fetch error: {e}"})
                    continue

                if not content or len(content) < 100:
                    print(f"      ❌ ABANDON — no content")
                    abandoned.append({**t, "verdict": "ABANDON", "reason": "empty/too short"})
                    continue

            # Quick Sonnet assessment
            gap_desc = ""
            for g in self.gaps:
                if g["id"] == t.get("gap_id"):
                    gap_desc = g["description"]
                    break
            if not gap_desc:
                gap_desc = self.question

            system = """You are testing whether a source is worth fully reading. Be HARSH.
Most sources are thin SEO filler. Say COMMIT only if you see specific data, frameworks,
contrarian takes, or real expertise. Say ABANDON if it's generic or surface-level.

Output JSON: {"verdict": "COMMIT" or "ABANDON", "reason": "one line why", "meat_signal": "what specific value you see (if COMMIT)"}"""

            user = f"GAP: {gap_desc}\nFIRST {bite_chars} CHARS:\n{content}"

            try:
                resp = call_claude(system, user, model=MODEL)
                self.cost += 0.008
                m = re.search(r"\{[\s\S]*\}", resp)
                if m:
                    assessment = json.loads(m.group())
                else:
                    assessment = {"verdict": "COMMIT", "reason": "parse failed, giving benefit of doubt"}
            except Exception as e:
                print(f"      ⚠️ Assessment failed: {e}. Committing by default.")
                assessment = {"verdict": "COMMIT", "reason": f"assessment error: {e}"}

            verdict = assessment.get("verdict", "ABANDON").upper()
            reason = assessment.get("reason", "")

            if verdict == "COMMIT":
                print(f"      ✅ COMMIT — {reason[:70]}")
                committed.append({**t, "verdict": "COMMIT", "reason": reason, "meat_signal": assessment.get("meat_signal", "")})
            else:
                print(f"      ❌ ABANDON — {reason[:70]}")
                abandoned.append({**t, "verdict": "ABANDON", "reason": reason})

        self.bitten = committed + abandoned
        self._committed = committed
        self.metrics["targets_committed"] = len(committed)
        self.metrics["targets_abandoned"] = len(abandoned)

        print(f"\n   Results: {len(committed)} committed, {len(abandoned)} abandoned")
        if abandoned:
            print(f"   Abandon rate: {len(abandoned)}/{len(committed)+len(abandoned)} = {len(abandoned)/(len(committed)+len(abandoned)):.0%}")
        print()
        self.save_state()

    # ------------------------------------------------------------------
    # Phase 3: KILL
    # ------------------------------------------------------------------

    def phase_kill(self):
        """Full extraction on committed targets with organ/meat/bone hierarchy."""
        print("🗡️  Phase 3: KILL — Full extraction on committed targets...\n")

        committed = getattr(self, "_committed", [])
        if not committed:
            print("   No committed targets. Nothing to kill.")
            return

        gaps_text = "\n".join(
            f"- [{g['id']}] {g['description']}"
            for g in self.gaps
            if g["status"] == "open"
        )

        # Gather existing knowledge names to detect contradictions
        known_names = set()
        if KNOWLEDGE_DIR.exists():
            for dd in KNOWLEDGE_DIR.iterdir():
                if dd.is_dir() and not dd.name.startswith("_"):
                    for f in list(dd.glob("*.json"))[:50]:
                        try:
                            known_names.add(json.loads(f.read_text()).get("name", "").lower())
                        except Exception:
                            pass

        for t in committed:
            if not self._budget_ok("kill"):
                print("   💰 Kill budget exhausted.")
                break

            url = t["url"]
            title = t["title"][:60]
            gap_id = t.get("gap_id", "")
            print(f"   🗡️  Killing: {title}...")

            try:
                content = fetch_content(url, title=t.get("title"))
            except Exception as e:
                print(f"      ⚠️ Fetch failed: {e}")
                continue

            if not content or len(content) < 200:
                print(f"      ⚠️ Insufficient content, skipping")
                continue

            max_chars = _CONFIG.get("max_content_chars", 15000)
            content_trimmed = content[:max_chars]

            system = f"""You are extracting knowledge with a value hierarchy. You know what we already know and what gaps remain.

GAPS (what we need to learn):
{gaps_text}

VALUE HIERARCHY — mark each framework with its tier:
🫀 ORGAN (highest): Contradicts existing knowledge, surprising, challenges assumptions
🩸 MEAT (high): Fills a SPECIFIC gap, genuinely new information
🦴 BONE (low): Confirms what we already know (log it, don't celebrate it)

For each framework output:
{{
  "type": "framework|claim|technique|case_study|contrarian",
  "name": "short name",
  "description": "1-3 sentences",
  "confidence": 0.0-1.0,
  "domain": "ai-systems|manufacturing|strategy|leadership|finance|technology|general",
  "tags": [],
  "raw_quote": "supporting quote if available",
  "value_tier": "organ|meat|bone",
  "addresses_gap": "gap_id or null"
}}

Be ruthless. Surface-level content is BONE. Only generate sub-components for gaps, not for everything.

Output JSON:
{{
  "frameworks": [...],
  "sub_components": [{{"concept": "...", "search_queries": ["..."], "gap_id": "..."}}],
  "key_insight": "single most important thing",
  "changes_understanding": "how this changes what we know"
}}"""

            user = f"""Question: {self.question}
Source: {t['title']}
URL: {url}

Content:
{content_trimmed}"""

            try:
                resp = call_claude(system, user, model=MODEL)
                self.cost += self._estimate_cost(len(content_trimmed))
            except Exception as e:
                print(f"      ⚠️ Extraction failed: {e}")
                continue

            # Parse
            result = {"frameworks": [], "sub_components": [], "key_insight": "", "changes_understanding": ""}
            try:
                m = re.search(r"\{[\s\S]*\}", resp)
                if m:
                    result = json.loads(m.group())
            except json.JSONDecodeError:
                print(f"      ⚠️ JSON parse failed")

            frameworks = result.get("frameworks", [])

            # Count tiers
            organ_count = sum(1 for f in frameworks if f.get("value_tier") == "organ")
            meat_count = sum(1 for f in frameworks if f.get("value_tier") == "meat")
            bone_count = sum(1 for f in frameworks if f.get("value_tier") == "bone")

            self.metrics["organs_found"] += organ_count
            self.metrics["meat_found"] += meat_count
            self.metrics["bones_found"] += bone_count

            # Mark gaps as closed if addressed
            for fw in frameworks:
                gid = fw.get("addresses_gap")
                if gid and fw.get("value_tier") in ("organ", "meat"):
                    for g in self.gaps:
                        if g["id"] == gid and g["status"] == "open":
                            g["status"] = "closed"
                            self.metrics["gaps_closed"] += 1

            # Save frameworks
            source_info = {"title": t["title"], "url": url}
            saved = save_frameworks(frameworks, source_info, self.hunt_id)
            self.metrics["frameworks_saved"] += saved

            # Cache source content for Jackal (sanitized)
            self.source_cache[url] = {
                "title": t["title"],
                "content": _sanitize_content(content[:max_chars]),
                "frameworks_extracted": [f.get("name", "") for f in frameworks],
                "value_tiers": {"organ": organ_count, "meat": meat_count, "bone": bone_count},
            }

            # Log finding
            self.findings.append(
                {
                    "url": url,
                    "title": t["title"],
                    "frameworks": len(frameworks),
                    "organs": organ_count,
                    "meat": meat_count,
                    "bones": bone_count,
                    "key_insight": result.get("key_insight", ""),
                    "changes_understanding": result.get("changes_understanding", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            self.kills.append(
                {
                    "url": url,
                    "title": t["title"],
                    "frameworks": frameworks,
                    "sub_components": result.get("sub_components", []),
                    "key_insight": result.get("key_insight", ""),
                    "changes_understanding": result.get("changes_understanding", ""),
                }
            )

            tier_str = ""
            if organ_count:
                tier_str += f" 🫀{organ_count}"
            if meat_count:
                tier_str += f" 🩸{meat_count}"
            if bone_count:
                tier_str += f" 🦴{bone_count}"
            print(f"      ✅ {saved} frameworks{tier_str}")
            if result.get("key_insight"):
                print(f"      💡 {result['key_insight'][:100]}")

            del content, content_trimmed, resp
            gc.collect()

        # Summary
        open_gaps = sum(1 for g in self.gaps if g["status"] == "open")
        closed = self.metrics["gaps_closed"]
        print(f"\n   Kill complete: {len(self.kills)} sources processed")
        print(f"   Gaps: {closed} closed, {open_gaps} still open")
        print()
        self.save_state()

    # ------------------------------------------------------------------
    # Phase 4: FEED
    # ------------------------------------------------------------------

    def phase_feed(self):
        """Wolf-style synthesis — territorial update, not book report."""
        print("🍖 Phase 4: FEED — Synthesizing understanding...\n")

        if not self.kills:
            print("   No kills to synthesize.")
            return

        # Build kill summaries
        kill_text = ""
        for k in self.kills:
            kill_text += f"\n### {k['title']}\n"
            kill_text += f"Key insight: {k.get('key_insight', 'none')}\n"
            kill_text += f"Understanding shift: {k.get('changes_understanding', 'none')}\n"
            for fw in k.get("frameworks", []):
                tier = fw.get("value_tier", "bone")
                emoji = {"organ": "🫀", "meat": "🩸", "bone": "🦴"}.get(tier, "")
                kill_text += f"  {emoji} [{tier}] {fw.get('name','?')}: {fw.get('description','')[:120]}\n"

        gaps_before = "\n".join(f"- [{g['id']}] {g['description']} → {g['status']}" for g in self.gaps)

        system = """You are writing a wolf-style research synthesis. This is a TERRITORIAL UPDATE, not a book report.

Structure:
1. **What Changed**: What do we now understand differently? (NOT "what we found")
2. **Gaps Closed**: Which specific unknowns were resolved?
3. **Gaps Opened**: What NEW questions emerged?
4. **Organs**: What surprised us or contradicted expectations?
5. **Territory Map**: Updated understanding of the landscape
6. **Next Hunt**: Where should the next wolf go?

Be direct. Skip pleasantries. This is intel, not an essay."""

        user = f"""Question: {self.question}

GAPS (before hunt):
{gaps_before}

KILLS:
{kill_text[:6000]}

Synthesize."""

        try:
            synthesis = call_claude(system, user, model=MODEL)
            self.cost += 0.02
        except Exception as e:
            synthesis = f"[Synthesis failed: {e}]"

        # Compute wolf metrics
        ts = self.metrics["targets_stalked"]
        tc = self.metrics["targets_committed"]
        ta = self.metrics["targets_abandoned"]
        organs = self.metrics["organs_found"]
        gi = self.metrics["gaps_identified"]
        gc_count = self.metrics["gaps_closed"]

        kill_rate = tc / ts if ts > 0 else 0
        abandon_rate = ta / (tc + ta) if (tc + ta) > 0 else 0
        gap_closure = gc_count / gi if gi > 0 else 0
        cost_per_organ = self.cost / organs if organs > 0 else self.cost

        wolf_metrics = {
            "kill_rate": round(kill_rate, 3),
            "organs_found": organs,
            "abandon_rate": round(abandon_rate, 3),
            "gap_closure_rate": round(gap_closure, 3),
            "cost_per_organ": round(cost_per_organ, 4),
        }

        # Save synthesis
        synth_path = HUNTS_DIR / f"{self.hunt_id}-synthesis.md"
        synth_content = f"""# Wolf Hunt Synthesis: {self.question}

**Hunt ID:** {self.hunt_id}
**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
**Cost:** ${self.cost:.4f} / ${self.budget:.2f}
**Kills:** {len(self.kills)} | **Frameworks:** {self.metrics['frameworks_saved']}
**Tiers:** 🫀 {organs} organs | 🩸 {self.metrics['meat_found']} meat | 🦴 {self.metrics['bones_found']} bone

## Wolf Metrics
- Kill rate: {kill_rate:.0%} ({tc}/{ts} targets committed)
- Abandon rate: {abandon_rate:.0%} ({ta} abandoned)
- Gap closure: {gap_closure:.0%} ({gc_count}/{gi} gaps closed)
- Cost per organ: ${cost_per_organ:.4f}

## Gaps Status
"""
        for g in self.gaps:
            status_emoji = "✅" if g["status"] == "closed" else "❓"
            synth_content += f"- {status_emoji} [{g['id']}] {g['description']}\n"

        synth_content += f"\n---\n\n{synthesis}\n"

        synth_path.write_text(synth_content)
        print(f"   💾 Synthesis saved: {synth_path.name}")

        # Write thinking log
        log_path = HUNTS_DIR / f"{self.hunt_id}-thinking.md"
        with open(log_path, "w") as f:
            f.write(f"# 🐺 Wolf Hunt Log: {self.question}\n\n")
            f.write(f"**Hunt ID:** {self.hunt_id} | **Cost:** ${self.cost:.4f}\n\n")
            f.write(f"## Gaps Identified\n")
            for g in self.gaps:
                f.write(f"- [{g['status']}] {g['description']}\n")
            f.write(f"\n## Kills\n")
            for k in self.kills:
                f.write(f"\n### {k['title']}\n")
                f.write(f"**Key insight:** {k.get('key_insight','')}\n")
                f.write(f"**Shift:** {k.get('changes_understanding','')}\n")
                for fw in k.get("frameworks", []):
                    f.write(f"- [{fw.get('value_tier','?')}] {fw.get('name','?')}: {fw.get('description','')[:100]}\n")

        # Print summary
        print(f"\n{'='*60}")
        print(f"🐺 WOLF HUNT COMPLETE")
        print(f"   Question: {self.question[:70]}")
        print(f"   Cost: ${self.cost:.4f} / ${self.budget:.2f}")
        print(f"   Kills: {len(self.kills)} | Frameworks: {self.metrics['frameworks_saved']}")
        print(f"   🫀 Organs: {organs} | 🩸 Meat: {self.metrics['meat_found']} | 🦴 Bone: {self.metrics['bones_found']}")
        print(f"   Kill rate: {kill_rate:.0%} | Abandon rate: {abandon_rate:.0%}")
        print(f"   Gap closure: {gap_closure:.0%} ({gc_count}/{gi})")
        print(f"   Cost/organ: ${cost_per_organ:.4f}")
        print(f"{'='*60}")

        # Save wolf metrics in state
        self.metrics["wolf_metrics"] = wolf_metrics
        self.save_state()

        # Post-hunt: Observer → Critic → Evolver
        self._post_hunt_cycle()

    # ------------------------------------------------------------------
    # Post-hunt cycle
    # ------------------------------------------------------------------

    def _post_hunt_cycle(self):
        """Run Observer → Critic → Evolver after hunt."""
        print(f"\n🔄 Post-Hunt: Observer → Critic → Evolver\n")

        for name, args in [
            ("Observer", ["python3", str(CEO_DIR / "tools" / "observer.py"), "--score-hunt", self.hunt_id]),
            ("Critic", ["python3", str(CEO_DIR / "tools" / "critic.py")]),
            ("Evolver", ["python3", str(CEO_DIR / "tools" / "evolver.py")]),
        ]:
            try:
                proc = subprocess.run(args, timeout=120, capture_output=True, text=True, cwd=str(CEO_DIR))
                if proc.stdout:
                    lines = proc.stdout.strip().split("\n")
                    for line in lines[:5]:
                        print(f"   [{name}] {line}")
            except Exception as e:
                print(f"   ⚠️ {name} failed: {e}")

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self):
        """Execute the 5-phase wolf hunt."""
        self.started_at = datetime.now(timezone.utc).isoformat()
        print(f"\n{'='*60}")
        print(f"🐺 WOLF HUNT: {self.question}")
        print(f"   ID: {self.hunt_id} | Budget: ${self.budget:.2f} | Max sources: {self.max_sources}")
        print(f"{'='*60}")

        phases = [
            ("territory", self.phase_territory),
            ("stalk", self.phase_stalk),
            ("bite", self.phase_test_bite),
            ("kill", self.phase_kill),
            ("feed", self.phase_feed),
        ]

        for phase_name, phase_fn in phases:
            try:
                phase_fn()
            except Exception as e:
                print(f"\n⚠️ Phase {phase_name} failed: {e}")
                print(f"   Saving partial state, continuing...")
                self.save_state()
                # Territory/stalk failure is fatal — no targets to work with
                if phase_name in ("territory", "stalk") and not getattr(self, "_targets", []):
                    print(f"   Cannot continue without targets. Aborting.")
                    break


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def show_status():
    """Show all hunts and their status."""
    print("\n🐺 WOLF HUNT STATUS")
    print("=" * 60)

    hunts = sorted(HUNTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    hunts = [h for h in hunts if not any(h.stem.endswith(s) for s in ("-synthesis", "-sources", "-thinking", "-adjacent", "-next-questions"))]

    if not hunts:
        print("  No hunts yet. Start one with: python3 hunter.py \"your question\"")
        return

    for h in hunts[:10]:
        try:
            state = json.loads(h.read_text())
            q = state.get("question", "?")[:60]
            hid = state.get("hunt_id", "?")
            cost = state.get("cost", 0)
            m = state.get("metrics", {})
            wm = m.get("wolf_metrics", {})
            print(f"\n  [{hid}] {q}")
            print(f"    Cost: ${cost:.4f} | Frameworks: {m.get('frameworks_saved', '?')}")
            if wm:
                print(f"    🫀 Organs: {wm.get('organs_found', 0)} | Kill rate: {wm.get('kill_rate', 0):.0%} | Gap closure: {wm.get('gap_closure_rate', 0):.0%}")
            else:
                print(f"    Kills: {state.get('kills_count', '?')} | Gaps: {len(state.get('gaps', []))}")
        except Exception:
            pass
    print()


def get_latest_hunt_id() -> str | None:
    hunts = sorted(HUNTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    hunts = [h for h in hunts if not any(h.stem.endswith(s) for s in ("-synthesis", "-sources", "-thinking", "-adjacent", "-next-questions"))]
    return hunts[0].stem if hunts else None


def main():
    parser = argparse.ArgumentParser(description="Wolf — Autonomous Research Hunter v2")
    parser.add_argument("question", nargs="?", help="Research question to hunt")
    parser.add_argument("--resume", action="store_true", help="Resume last hunt")
    parser.add_argument("--status", action="store_true", help="Show hunt status")
    parser.add_argument("--depth", type=int, help="Max recursion depth")
    parser.add_argument("--budget", type=float, help="Max spend in dollars")
    parser.add_argument("--sources", type=int, help="Max sources to process")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.resume:
        hunt_id = get_latest_hunt_id()
        if not hunt_id:
            print("No hunts to resume.")
            return
        hunt = Hunt.load(hunt_id)
        print(f"Resuming hunt: {hunt.question}")
        if args.depth is not None:
            hunt.max_depth = args.depth
        if args.budget is not None:
            hunt.budget = args.budget
        if args.sources is not None:
            hunt.max_sources = args.sources
        hunt.run()
        return

    if not args.question:
        parser.print_help()
        return

    hunt = Hunt(
        question=args.question,
        max_depth=args.depth,
        max_sources=args.sources,
        budget=args.budget,
    )
    hunt.run()


if __name__ == "__main__":
    main()
