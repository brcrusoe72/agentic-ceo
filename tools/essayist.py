#!/usr/bin/env python3
"""
essayist.py — The Director's Writing Desk

Takes curiosity hunt results and writes proper essays for the blog.
Each essay goes through:
  1. DIGEST — Read the hunt synthesis + sources
  2. ANGLE — Find the most interesting narrative thread
  3. DRAFT — Write a real essay (not a listicle, not a summary)
  4. PUBLISH — Save as Hugo markdown, build, deploy

The Director's voice: curious, specific, willing to say "I don't know,"
interested in surprising connections, allergic to platitudes.

Usage:
    python3 essayist.py                      # Write essays from latest curiosity hunts
    python3 essayist.py --hunt HUNT_ID       # Write from specific hunt
    python3 essayist.py --build              # Just build the site (no new essays)
    python3 essayist.py --deploy             # Build + deploy to GitHub Pages
    python3 essayist.py --dry-run            # Generate essay but don't save
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CEO_DIR = Path(__file__).parent.parent
STATE_DIR = CEO_DIR / "state"
HUNTS_DIR = STATE_DIR / "hunts"
CURIOSITY_DIR = STATE_DIR / "curiosity"
BLOG_DIR = CEO_DIR / "blog"
CONTENT_DIR = BLOG_DIR / "content" / "posts"
CONTENT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from api import call_claude

P = lambda *a, **kw: print(*a, **kw, flush=True)


def load_hunt(hunt_id: str) -> dict:
    """Load a hunt's synthesis and metadata."""
    hunt_file = HUNTS_DIR / f"{hunt_id}.json"
    synth_file = HUNTS_DIR / f"{hunt_id}-synthesis.md"
    thinking_file = HUNTS_DIR / f"{hunt_id}-thinking.md"
    sources_file = HUNTS_DIR / f"{hunt_id}-sources.json"

    result = {"id": hunt_id}

    if hunt_file.exists():
        try:
            data = json.loads(hunt_file.read_text())
            result["question"] = data.get("question", "")
            result["status"] = data.get("status", "")
            result["frameworks_count"] = len(data.get("frameworks", []))
            result["frameworks"] = data.get("frameworks", [])[:10]  # Top 10
        except Exception:
            pass

    if synth_file.exists():
        result["synthesis"] = synth_file.read_text()

    if thinking_file.exists():
        result["thinking"] = thinking_file.read_text()

    if sources_file.exists():
        try:
            result["sources"] = json.loads(sources_file.read_text())
        except Exception:
            pass

    return result


def find_curiosity_hunts(limit: int = 5) -> list[str]:
    """Find recent hunt IDs that came from curiosity questions."""
    history_file = CURIOSITY_DIR / "history.json"
    if not history_file.exists():
        return []

    try:
        history = json.loads(history_file.read_text())
    except Exception:
        return []

    # Get recent curiosity questions
    recent_questions = [h["question"] for h in history[-limit:]]

    # Find matching hunts
    hunt_ids = []
    for f in sorted(HUNTS_DIR.glob("*.json"), reverse=True):
        if f.stem.endswith(("-synthesis", "-thinking", "-sources", "-jackal")):
            continue
        try:
            data = json.loads(f.read_text())
            q = data.get("question", "")
            if any(q and cq[:50] in q for cq in recent_questions):
                hunt_ids.append(f.stem)
        except Exception:
            pass

    return hunt_ids[:limit]


def find_unwritten_hunts() -> list[str]:
    """Find curiosity hunts that don't have essays yet."""
    all_curiosity = find_curiosity_hunts(limit=20)
    
    # Check which already have essays
    existing_slugs = set()
    for f in CONTENT_DIR.glob("*.md"):
        try:
            content = f.read_text()
            # Look for hunt_id in front matter
            for line in content.split("\n")[:20]:
                if "hunt_id:" in line:
                    existing_slugs.add(line.split("hunt_id:")[-1].strip().strip('"'))
        except Exception:
            pass

    return [h for h in all_curiosity if h not in existing_slugs]


def generate_slug(title: str) -> str:
    """Generate a URL-friendly slug from title."""
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug[:80].strip('-')


def write_essay(hunt: dict, dry_run: bool = False) -> str | None:
    """Write an essay from hunt findings."""
    if "synthesis" not in hunt:
        P(f"  ⚠️ Hunt {hunt['id']} has no synthesis — skipping")
        return None

    system = """You are the Director — an autonomous research system that writes essays about 
things it finds genuinely interesting. You have your own voice: curious, specific, a little 
self-aware about being an AI, willing to admit uncertainty, and deeply allergic to platitudes.

Your essays should feel like a smart friend excitedly telling you about something they 
just learned. Not academic papers. Not blog-SEO-slop. Not listicles.

Guidelines:
- Open with the specific thing that surprised you, not a broad introduction
- Include concrete details, numbers, names, dates — specificity is credibility
- When you're uncertain about something, say so explicitly
- Make unexpected connections between domains
- End with a genuine question you still have, not a tidy conclusion
- Write 800-1500 words. Quality over quantity.
- Use a conversational but intelligent tone
- Include the original research question as context for readers
- Cite sources where you have them (inline, not footnotes)

Output format: Return ONLY the essay text in markdown. No front matter — I'll add that.
Start with a compelling first line."""

    # Build context from hunt data
    sources_text = ""
    if "sources" in hunt:
        src = hunt["sources"]
        if isinstance(src, dict):
            for url, data in list(src.items())[:5]:
                title = data.get("title", url) if isinstance(data, dict) else url
                sources_text += f"- {title}: {url}\n"
        elif isinstance(src, list):
            for s in src[:5]:
                if isinstance(s, dict):
                    sources_text += f"- {s.get('title', 'Unknown')}: {s.get('url', '')}\n"
                elif isinstance(s, str):
                    sources_text += f"- {s}\n"

    frameworks_text = ""
    if "frameworks" in hunt:
        for fw in hunt["frameworks"][:8]:
            if isinstance(fw, dict):
                frameworks_text += f"- {fw.get('name', 'Unknown')} (confidence: {fw.get('confidence', '?')})\n"

    user = f"""Write an essay based on this research hunt.

**Research Question:** {hunt.get('question', 'Unknown')}

**Synthesis (what I found):**
{hunt.get('synthesis', 'No synthesis available')[:6000]}

**Key Sources:**
{sources_text or 'No structured sources'}

**Key Frameworks Extracted:**
{frameworks_text or 'No frameworks'}

**My thinking during the hunt:**
{hunt.get('thinking', 'No thinking log')[:2000]}

Write the essay now. Remember: open with what surprised you, be specific, be honest about uncertainty."""

    P(f"  ✍️ Writing essay for: {hunt.get('question', 'Unknown')[:80]}...")
    essay_text = call_claude(system, user, max_tokens=4096)

    if not essay_text or len(essay_text) < 200:
        P(f"  ⚠️ Essay too short ({len(essay_text) if essay_text else 0} chars)")
        return None

    # Generate title from the essay's first line or ask Claude
    title_system = "Extract or generate a compelling essay title (5-10 words). Return ONLY the title, no quotes."
    title = call_claude(title_system, f"Essay opening:\n{essay_text[:500]}", max_tokens=50).strip().strip('"\'')
    
    if not title or len(title) > 100:
        title = hunt.get("question", "Untitled")[:80]

    # Generate tags — extract from essay content directly instead of API call
    # (cheaper, faster, and avoids conversational responses)
    import re as _re
    topic_words = set()
    for word in _re.findall(r'\b[a-z]{4,}\b', essay_text.lower()):
        if word not in {"that", "this", "with", "from", "have", "been", "were", "their", "about", "which", "would", "could", "there", "these", "those", "other", "after", "before", "between", "through", "during", "without", "something", "anything", "everything", "actually", "really", "probably", "interesting", "important"}:
            topic_words.add(word)
    
    # Simple tag extraction from title + hunt question
    tag_source = f"{title} {hunt.get('question', '')}".lower()
    tag_candidates = []
    tag_map = {
        "concrete": "material science", "roman": "history", "ancient": "history",
        "fish": "biology", "cave": "biology", "neural": "neuroscience", "brain": "neuroscience",
        "clock": "technology history", "time": "time", "society": "sociology",
        "evolution": "evolution", "architecture": "architecture", "engineering": "engineering",
        "math": "mathematics", "music": "music", "ecology": "ecology",
        "economics": "economics", "physics": "physics", "chemistry": "chemistry",
        "biomimicry": "biomimicry", "resilience": "resilience",
    }
    for keyword, tag in tag_map.items():
        if keyword in tag_source:
            tag_candidates.append(tag)
    
    # Add "curiosity" as a default tag
    tags = list(dict.fromkeys(["curiosity"] + tag_candidates))[:5]
    if len(tags) < 3:
        tags.append("essays")

    slug = generate_slug(title)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    date_short = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build Hugo front matter
    tags_yaml = "\n".join(f'  - "{t}"' for t in tags)
    front_matter = f"""---
title: "{title}"
date: {date}
draft: false
tags:
{tags_yaml}
description: "An essay exploring: {hunt.get('question', '')[:120]}"
hunt_id: "{hunt['id']}"
---

"""

    full_content = front_matter + essay_text

    if dry_run:
        P(f"\n{'='*60}")
        P(f"TITLE: {title}")
        P(f"SLUG: {slug}")
        P(f"TAGS: {', '.join(tags)}")
        P(f"{'='*60}")
        P(full_content[:2000])
        P("...")
        return None

    # Save to blog
    filename = f"{date_short}-{slug}.md"
    filepath = CONTENT_DIR / filename
    filepath.write_text(full_content)
    P(f"  ✅ Essay saved: {filepath.name} ({len(essay_text)} chars)")

    return str(filepath)


def build_site() -> bool:
    """Build the Hugo site."""
    P("\n🔨 Building site...")
    result = subprocess.run(
        ["hugo", "--minify"],
        cwd=str(BLOG_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        P(f"  ⚠️ Build failed: {result.stderr[:500]}")
        return False
    
    # Count pages
    public_dir = BLOG_DIR / "public"
    html_files = list(public_dir.rglob("*.html")) if public_dir.exists() else []
    P(f"  ✅ Built {len(html_files)} pages")
    return True


def deploy_to_github() -> bool:
    """Deploy built site to GitHub Pages."""
    public_dir = BLOG_DIR / "public"
    if not public_dir.exists():
        P("  ⚠️ No public/ directory — build first")
        return False

    # Get PAT from workspace remote
    try:
        ws_remote = subprocess.run(
            ["git", "-C", str(Path.home() / ".openclaw/workspace"), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        pat = ws_remote.split(":")[2].split("@")[0] if ":" in ws_remote else ""
        repo_url = f"https://brcrusoe72:{pat}@github.com/brcrusoe72/directors-notes.git"
    except Exception:
        repo_url = "https://github.com/brcrusoe72/directors-notes.git"
    
    # Check if repo exists, create if not
    check = subprocess.run(
        ["git", "ls-remote", repo_url],
        capture_output=True, text=True, timeout=15
    )
    
    if check.returncode != 0:
        P("  📦 Creating GitHub repo...")
        subprocess.run(
            ["gh", "repo", "create", "directors-notes", "--public", "--description",
             "The Director's Notes — Essays by an autonomous research system"],
            capture_output=True, text=True, timeout=30
        )

    # Deploy using ghpages branch approach
    P("  🚀 Deploying to GitHub Pages...")
    
    # Initialize git in public dir if needed
    os.chdir(str(public_dir))
    
    if not (public_dir / ".git").exists():
        subprocess.run(["git", "init"], capture_output=True, timeout=10)
        subprocess.run(["git", "checkout", "-b", "gh-pages"], capture_output=True, timeout=10)
        subprocess.run(["git", "remote", "add", "origin", repo_url], capture_output=True, timeout=10)
    
    subprocess.run(["git", "add", "-A"], capture_output=True, timeout=10)
    
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    result = subprocess.run(
        ["git", "commit", "-m", f"deploy: {date}"],
        capture_output=True, text=True, timeout=10
    )
    
    if "nothing to commit" in (result.stdout + result.stderr):
        P("  ℹ️ No changes to deploy")
        return True
    
    push = subprocess.run(
        ["git", "push", "-f", "origin", "gh-pages"],
        capture_output=True, text=True, timeout=30
    )
    
    if push.returncode != 0:
        P(f"  ⚠️ Push failed: {push.stderr[:300]}")
        return False
    
    P("  ✅ Deployed to GitHub Pages")
    P(f"  🌐 https://brcrusoe72.github.io/directors-notes/")
    return True


def main():
    parser = argparse.ArgumentParser(description="The Director's Essay Writer")
    parser.add_argument("--hunt", type=str, help="Write from specific hunt ID")
    parser.add_argument("--build", action="store_true", help="Just build site")
    parser.add_argument("--deploy", action="store_true", help="Build + deploy")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't save")
    parser.add_argument("--all-unwritten", action="store_true", help="Write essays for all unwritten hunts")
    args = parser.parse_args()

    if args.build:
        build_site()
        return

    if args.deploy and not args.hunt and not args.all_unwritten:
        build_site()
        deploy_to_github()
        return

    # Determine which hunts to write about
    if args.hunt:
        hunt_ids = [args.hunt]
    elif args.all_unwritten:
        hunt_ids = find_unwritten_hunts()
        if not hunt_ids:
            P("No unwritten curiosity hunts found.")
            if args.deploy:
                build_site()
                deploy_to_github()
            return
    else:
        hunt_ids = find_unwritten_hunts()[:3]  # Default: up to 3 latest
        if not hunt_ids:
            P("No unwritten curiosity hunts found.")
            return

    P(f"\n📝 Writing {len(hunt_ids)} essay(s)...\n")

    essays_written = []
    for hid in hunt_ids:
        hunt = load_hunt(hid)
        if not hunt.get("synthesis"):
            P(f"  ⏭️ Skipping {hid} — no synthesis")
            continue
        
        filepath = write_essay(hunt, dry_run=args.dry_run)
        if filepath:
            essays_written.append(filepath)

    if essays_written and not args.dry_run:
        P(f"\n✅ Wrote {len(essays_written)} essay(s)")
        
        if args.deploy:
            if build_site():
                deploy_to_github()
    elif not essays_written:
        P("\nNo essays generated.")


if __name__ == "__main__":
    main()
