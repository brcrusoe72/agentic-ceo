#!/usr/bin/env python3
"""
Common utilities for CEO Knowledge Adapters.

Handles the nested inbox item format:
  {
    "routing": {"relevance_score", "matched_tags", ...},
    "framework": {"name", "description", "tags", "type", "confidence", ...}
  }

All adapters should use extract_item() to normalize before classification.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict


def extract_item(raw: dict) -> dict:
    """Normalize a raw inbox JSON item into flat fields for classification."""
    fw = raw.get("framework", {})
    rt = raw.get("routing", {})

    # Merge tags from both framework and routing
    all_tags = list(set(
        [t.lower().replace("_", "-") for t in (fw.get("tags") or [])] +
        [t.lower().replace("_", "-") for t in (rt.get("matched_tags") or [])]
    ))

    return {
        "id": fw.get("id", ""),
        "name": fw.get("name", ""),
        "description": fw.get("description", ""),
        "type": fw.get("type", ""),
        "domain": fw.get("domain", ""),
        "confidence": fw.get("confidence", 0),
        "tags": all_tags,
        "relevance": rt.get("relevance_score", 0),
        "source_url": (fw.get("source") or {}).get("url", ""),
        "source_title": (fw.get("source") or {}).get("title", ""),
        "raw_quote": fw.get("raw_quote", ""),
        "hunt_id": fw.get("hunt_id", ""),
        "_raw": raw,
    }


def classify(item: dict, categories: dict) -> list:
    """
    Classify a normalized item against category definitions.

    categories: {
        "cat_name": {
            "tags": ["tag1", "tag2"],       # match against item tags
            "keywords": ["kw1", "kw2"],     # match against name + description
        }
    }

    Returns: [(cat_name, score), ...] sorted by score descending
    """
    name_lower = item["name"].lower()
    desc_lower = item.get("description", "").lower()
    text = name_lower + " " + desc_lower
    tags = item["tags"]

    matches = []
    for cat_name, cat_def in categories.items():
        score = 0
        # Tag matches (high weight)
        for t in tags:
            for pattern in cat_def.get("tags", []):
                if pattern in t:
                    score += 3
                    break
        # Keyword matches in name+desc
        for kw in cat_def.get("keywords", []):
            if kw.lower() in text:
                score += 1
        # Domain match
        for kw in cat_def.get("domains", []):
            if kw.lower() in (item.get("domain") or "").lower():
                score += 2
        if score > 0:
            matches.append((cat_name, score))

    matches.sort(key=lambda x: -x[1])
    return matches


def extract_numbers(text: str) -> list:
    """Extract numeric claims from text."""
    claims = []
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*%', text):
        claims.append({"value": float(m.group(1)), "unit": "%", "context": text[:80]})
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*[xX]\b', text):
        claims.append({"value": float(m.group(1)), "unit": "x", "context": text[:80]})
    return claims


def load_inbox(inbox_dir: Path, include_consumed: bool = False) -> list:
    """Load and normalize inbox items.
    
    Args:
        inbox_dir: Path to inbox directory
        include_consumed: If True, load ALL items (for dedicated adapters
            that need the full set to produce overlays). If False (default),
            only load unconsumed items.
    """
    if not inbox_dir.exists():
        return []
    items = []
    for f in sorted(inbox_dir.glob("*.json")):
        try:
            raw = json.loads(f.read_text())
            if not include_consumed and raw.get("consumed"):
                continue
            item = extract_item(raw)
            item["_path"] = str(f)
            items.append(item)
        except Exception:
            continue
    return items


def mark_consumed(items: list, adapter_name: str, category_map: dict = None) -> int:
    """Mark items as consumed in their source JSON files."""
    count = 0
    for item in items:
        path = item.get("_path")
        cat = (category_map or {}).get(item.get("id"), "uncategorized")
        if path and os.path.exists(path):
            try:
                raw = json.loads(Path(path).read_text())
                raw["consumed"] = True
                raw["consumed_at"] = datetime.now(timezone.utc).isoformat()
                raw["consumed_by"] = adapter_name
                raw["category"] = cat
                Path(path).write_text(json.dumps(raw, indent=2))
                count += 1
            except Exception:
                pass
    return count


def scan_and_categorize(inbox_dir: Path, categories: dict, system_name: str, include_consumed: bool = False):
    """Universal scan: load inbox, classify, print report, return categorized dict.
    
    Args:
        include_consumed: If True, scan ALL items (for overlay regeneration).
    """
    items = load_inbox(inbox_dir, include_consumed=include_consumed)
    if not items:
        print("Inbox empty or all consumed.")
        return {}, []

    categorized = defaultdict(list)
    uncategorized = []

    for item in items:
        matches = classify(item, categories)
        if matches:
            top_cat = matches[0][0]
            item["_category"] = top_cat
            item["claims"] = extract_numbers(item["name"] + " " + item.get("description", ""))
            categorized[top_cat].append(item)
        else:
            uncategorized.append(item)

    total_cat = sum(len(v) for v in categorized.values())
    print(f"\n{'='*60}")
    print(f"  {system_name} — CEO INBOX SCAN")
    print(f"{'='*60}")
    print(f"  Total items: {len(items)}")
    print(f"  Categorized: {total_cat}")
    print(f"  Uncategorized: {len(uncategorized)}")

    for cat, items_list in sorted(categorized.items(), key=lambda x: -len(x[1])):
        print(f"\n  {cat.upper()} ({len(items_list)} items)")
        top = sorted(items_list, key=lambda x: -x["relevance"])[:5]
        for t in top:
            print(f"    [{t['relevance']:.2f}|{t['confidence']:.1f}] {t['name'][:65]}")
            if t.get("claims"):
                for c in t["claims"][:2]:
                    print(f"           → {c['value']}{c['unit']}")

    return categorized, uncategorized
