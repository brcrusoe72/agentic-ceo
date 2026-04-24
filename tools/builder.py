#!/usr/bin/env python3
"""
builder.py — The Tool Smith

Reads what Nexus found. Understands the gap. Designs the right tool
to fill it. Builds it. Verifies it works. Ships it.

This is not a code generator. This is an agent that closes the
SENSE → ACT gap. Hunter finds knowledge. Nexus finds patterns.
Builder turns patterns into working tools.

Usage:
    python3 builder.py                        # Full cycle: pick top rec, spec, build, test, ship
    python3 builder.py --spec-only            # Generate spec only
    python3 builder.py --from-rec 0           # Build from recommendation #0
    python3 builder.py --from-question "..."  # Build tool for custom need
    python3 builder.py --list                 # Show available recommendations
    python3 builder.py --status               # Show what's been built
    python3 builder.py --dry-run              # Show what would be built
"""

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
NEXUS_DIR = STATE_DIR / "nexus"
BUILDER_DIR = STATE_DIR / "builder"
SPECS_DIR = BUILDER_DIR / "specs"
BUILDS_DIR = BUILDER_DIR / "builds"
SHIPPED_DIR = BUILDER_DIR / "shipped"
REPORTS_DIR = STATE_DIR / "agent-reports"
BUILT_TOOLS_DIR = CEO_DIR / "tools" / "built"

for d in [BUILDER_DIR, SPECS_DIR, BUILDS_DIR, SHIPPED_DIR, REPORTS_DIR, BUILT_TOOLS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

P = lambda *a, **kw: print(*a, **kw, flush=True)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str, model: str = "claude-sonnet-4-5-20250929",
                max_tokens: int = 8192) -> str:
    return _call_claude_base(system, user, model=model, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_recommendations() -> list[dict]:
    recs_path = NEXUS_DIR / "recommendations.json"
    if not recs_path.exists():
        return []
    try:
        return json.loads(recs_path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def load_nexus_context() -> str:
    """Load latest Nexus outputs for context."""
    parts = []
    today = datetime.now().strftime("%Y-%m-%d")

    for prefix in ("connections", "emerging", "brief"):
        # Try today first, then find latest
        candidates = sorted(NEXUS_DIR.glob(f"{prefix}-*.md"), reverse=True)
        if candidates:
            content = candidates[0].read_text()
            if len(content) > 4000:
                content = content[:4000] + "\n\n[...truncated]"
            parts.append(content)

    return "\n\n---\n\n".join(parts) if parts else ""


def load_knowledge_summary() -> str:
    """Compact summary of the knowledge base."""
    fw_by_domain: dict[str, int] = {}
    for domain_dir in KNOWLEDGE_DIR.iterdir():
        if domain_dir.is_dir() and not domain_dir.name.startswith("_"):
            count = len(list(domain_dir.glob("*.json")))
            if count > 0:
                fw_by_domain[domain_dir.name] = count
    lines = [f"- **{d}**: {c} frameworks" for d, c in sorted(fw_by_domain.items(), key=lambda x: -x[1])]
    return "\n".join(lines) if lines else "No frameworks yet."


def load_shipped_manifest() -> list[dict]:
    manifest_path = SHIPPED_DIR / "manifest.json"
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return []


def save_shipped_manifest(manifest: list[dict]):
    (SHIPPED_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))


def load_constitution() -> str:
    const_path = CEO_DIR / "constitution.yaml"
    if const_path.exists():
        return const_path.read_text()
    return ""


# ---------------------------------------------------------------------------
# Safety Check
# ---------------------------------------------------------------------------

UNSAFE_PATTERNS = [
    r"\bos\.system\b", r"\bsubprocess\.(run|call|Popen|check_output)\b",
    r"\brequests\.(get|post|put|delete|patch)\b", r"\burllib\b",
    r"\bshutil\.rmtree\b", r"\bos\.remove\b", r"\bos\.unlink\b",
    r"\bopen\(.*(\/etc|\/var|\/usr|\/root|~\/)\b",
    r"\bsocket\b", r"\bhttp\.client\b", r"\bftplib\b",
    r"\bsmtplib\b", r"\bparamiko\b", r"\bssh\b",
    r"\beval\b", r"\bexec\b",
]


def check_safety(code: str) -> list[str]:
    """Check generated code for unsafe operations. Returns list of concerns."""
    concerns = []
    for pattern in UNSAFE_PATTERNS:
        matches = re.findall(pattern, code)
        if matches:
            concerns.append(f"⚠️  Found potentially unsafe pattern: {matches[0]}")
    return concerns


def is_safe_to_run(code: str) -> bool:
    """Conservative check: is this code safe to auto-execute for testing?"""
    concerns = check_safety(code)
    return len(concerns) == 0


# ---------------------------------------------------------------------------
# Core Pipeline
# ---------------------------------------------------------------------------

def select_recommendation(recs: list[dict], index: int | None = None) -> dict | None:
    """Pick the best recommendation to build from."""
    if not recs:
        return None
    if index is not None:
        if 0 <= index < len(recs):
            return recs[index]
        P(f"❌ Index {index} out of range (0-{len(recs)-1})")
        return None

    # Pick highest priority that hasn't been built yet
    shipped = load_shipped_manifest()
    shipped_questions = {s.get("question", "") for s in shipped}

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_recs = sorted(recs, key=lambda r: priority_order.get(r.get("priority", "medium"), 2))

    for rec in sorted_recs:
        if rec.get("question", "") not in shipped_questions:
            return rec

    P("ℹ️  All recommendations have been built. Use --from-question for custom builds.")
    return None


def generate_spec(recommendation: dict, nexus_context: str, knowledge_summary: str) -> dict:
    """Generate a full build spec from a recommendation."""
    P("📐 Generating build spec...")

    system = """You are a senior software architect designing a tool for an autonomous research system.
Given a recommendation from the pattern analysis engine, design a complete tool specification.

The tool will live in the CEO ecosystem — a multi-agent system with:
- Hunter (recursive research)
- Nexus (pattern analysis)
- Builder (you're designing what Builder will build)
- A shared knowledge base (JSON files in knowledge/ directories)
- State tracking in state/ directories

Design tools that INTEGRATE with this ecosystem. They should read from and write to
the knowledge base. They should be useful to the other agents.

Output a JSON spec:
{
    "tool_name": "short-snake-case-name",
    "title": "Human readable title",
    "description": "What it does and why it matters",
    "architecture": "How it works — components, data flow, key decisions",
    "acceptance_criteria": ["list of testable criteria"],
    "files": [
        {"path": "relative/path.py", "purpose": "what this file does"}
    ],
    "dependencies": ["python packages needed beyond stdlib"],
    "edge_cases": ["things that could go wrong"],
    "integration_points": ["how it connects to the CEO ecosystem"],
    "estimated_complexity": "simple|moderate|complex",
    "safety_notes": ["any safety concerns for auto-execution"]
}

Be specific and practical. These tools will be auto-generated and tested.
Prefer single-file tools when possible. Keep dependencies minimal."""

    question = recommendation.get("question", "")
    reason = recommendation.get("reason", "")
    expected = recommendation.get("expected_value", "")

    user = f"""## Recommendation
**Question:** {question}
**Priority:** {recommendation.get('priority', 'medium')}
**Reason:** {reason}
**Expected Value:** {expected}

## Nexus Analysis Context
{nexus_context[:3000]}

## Knowledge Base Coverage
{knowledge_summary}

Design the tool spec. Output ONLY valid JSON."""

    response = call_claude(system, user)

    try:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            spec = json.loads(json_match.group())
            spec["_source_recommendation"] = recommendation
            spec["_generated_at"] = datetime.now(timezone.utc).isoformat()
            return spec
    except json.JSONDecodeError:
        pass

    P("⚠️  Failed to parse spec JSON, returning raw")
    return {
        "tool_name": "unknown",
        "title": "Parse Error",
        "description": response[:500],
        "_source_recommendation": recommendation,
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_raw": response,
    }


def save_spec(spec: dict) -> Path:
    name = spec.get("tool_name", "unknown")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    spec_path = SPECS_DIR / f"{name}-{ts}.json"
    spec_path.write_text(json.dumps(spec, indent=2))
    P(f"💾 Spec saved: {spec_path}")
    return spec_path


def build_tool(spec: dict, nexus_context: str) -> dict:
    """Generate working code from a spec."""
    P("🔨 Building tool...")

    tool_name = spec.get("tool_name", "tool")
    files_spec = spec.get("files", [{"path": f"{tool_name}.py", "purpose": "main tool"}])

    system = f"""You are a Python developer building a tool for the Agentic CEO system.
You write clean, production-quality Python. No placeholder code. No TODOs. Working code.

Key patterns to follow:
- Use pathlib for all file operations
- Use json for data serialization
- Print with flush=True for unbuffered output
- Include if __name__ == "__main__" with argparse
- Include docstrings
- Handle errors gracefully — don't crash, log and continue
- Read/write to the CEO knowledge base at: {CEO_DIR}
  - Knowledge: {KNOWLEDGE_DIR}
  - State: {STATE_DIR}
- Keep it self-contained. Minimize external dependencies.

The tool integrates into an ecosystem where:
- knowledge/ contains JSON framework files organized by domain
- state/ contains agent state, reports, missions
- tools/ contains agent scripts (hunter.py, nexus.py, builder.py)
- tools/built/ is where YOUR generated tools go

Generate the COMPLETE file content for each file. No truncation. No "..." placeholders."""

    built_files = {}

    for file_spec in files_spec:
        rel_path = file_spec.get("path", f"{tool_name}.py")
        purpose = file_spec.get("purpose", "")

        user = f"""## Tool Spec
**Name:** {spec.get('title', tool_name)}
**Description:** {spec.get('description', '')}
**Architecture:** {spec.get('architecture', '')}

## This File
**Path:** tools/built/{rel_path}
**Purpose:** {purpose}

## Acceptance Criteria
{json.dumps(spec.get('acceptance_criteria', []), indent=2)}

## Edge Cases to Handle
{json.dumps(spec.get('edge_cases', []), indent=2)}

## Integration Points
{json.dumps(spec.get('integration_points', []), indent=2)}

## Context from Nexus Analysis
{nexus_context[:2000]}

Generate the COMPLETE Python file. Output ONLY the code — no markdown fences, no explanation.
Start with #!/usr/bin/env python3"""

        P(f"   📝 Generating {rel_path}...")
        code = call_claude(system, user, max_tokens=16384)

        # Clean up: remove markdown fences if present
        code = re.sub(r'^```python\s*\n?', '', code.strip())
        code = re.sub(r'\n?```\s*$', '', code.strip())

        # Ensure shebang
        if not code.startswith("#!/"):
            code = "#!/usr/bin/env python3\n" + code

        built_files[rel_path] = code

    return built_files


def write_built_files(files: dict[str, str]) -> list[Path]:
    """Write generated files to tools/built/. Returns list of paths."""
    paths = []
    for rel_path, code in files.items():
        full_path = BUILT_TOOLS_DIR / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(code)
        full_path.chmod(0o755)
        paths.append(full_path)
        P(f"   💾 Written: {full_path}")
    return paths


def test_tool(files: dict[str, str], spec: dict) -> dict:
    """Test the generated tool. Only auto-runs safe code."""
    P("🧪 Testing tool...")
    results = {
        "syntax_ok": True,
        "safety_ok": True,
        "safety_concerns": [],
        "run_ok": None,
        "run_output": None,
        "run_error": None,
    }

    for rel_path, code in files.items():
        # 1. Syntax check
        P(f"   🔍 Syntax check: {rel_path}")
        try:
            compile(code, rel_path, "exec")
            P(f"      ✅ Syntax OK")
        except SyntaxError as e:
            P(f"      ❌ Syntax error: {e}")
            results["syntax_ok"] = False
            results["run_error"] = str(e)
            return results

        # 2. Safety check
        P(f"   🛡️  Safety check: {rel_path}")
        concerns = check_safety(code)
        if concerns:
            results["safety_ok"] = False
            results["safety_concerns"] = concerns
            for c in concerns:
                P(f"      {c}")
            P("      🚫 Has network/system calls — skipping auto-execution")
            P("      📋 NEEDS HUMAN REVIEW before running")
        else:
            P(f"      ✅ No unsafe patterns detected")

        # 3. Auto-run if safe (import test + help flag)
        if results["safety_ok"]:
            full_path = BUILT_TOOLS_DIR / rel_path
            if full_path.exists():
                P(f"   🏃 Running: python3 {full_path} --help")
                try:
                    proc = subprocess.run(
                        ["python3", "-u", str(full_path), "--help"],
                        capture_output=True, text=True, timeout=30,
                        cwd=str(CEO_DIR),
                    )
                    results["run_ok"] = proc.returncode == 0
                    results["run_output"] = proc.stdout[:2000] if proc.stdout else None
                    results["run_error"] = proc.stderr[:2000] if proc.stderr else None

                    if proc.returncode == 0:
                        P(f"      ✅ Runs successfully")
                        if proc.stdout:
                            for line in proc.stdout.strip().split("\n")[:5]:
                                P(f"         {line}")
                    else:
                        P(f"      ❌ Exit code {proc.returncode}")
                        if proc.stderr:
                            for line in proc.stderr.strip().split("\n")[:5]:
                                P(f"         {line}")
                except subprocess.TimeoutExpired:
                    P(f"      ⏰ Timed out after 30s")
                    results["run_ok"] = False
                    results["run_error"] = "Timeout"
                except Exception as e:
                    P(f"      ❌ Error: {e}")
                    results["run_ok"] = False
                    results["run_error"] = str(e)

    return results


def ship_tool(spec: dict, files: dict[str, str], test_results: dict, build_id: str) -> dict:
    """Ship: update manifest, write docs, log report."""
    P("📦 Shipping tool...")

    tool_name = spec.get("tool_name", "unknown")
    now = datetime.now(timezone.utc)

    # 1. Build log
    build_log = {
        "build_id": build_id,
        "tool_name": tool_name,
        "title": spec.get("title", ""),
        "description": spec.get("description", ""),
        "timestamp": now.isoformat(),
        "spec_summary": {
            "acceptance_criteria": spec.get("acceptance_criteria", []),
            "dependencies": spec.get("dependencies", []),
            "complexity": spec.get("estimated_complexity", "unknown"),
        },
        "files": list(files.keys()),
        "test_results": test_results,
        "source_recommendation": spec.get("_source_recommendation", {}),
    }
    build_path = BUILDS_DIR / f"{tool_name}-{build_id}.json"
    build_path.write_text(json.dumps(build_log, indent=2))
    P(f"   💾 Build log: {build_path}")

    # 2. Update shipped manifest
    manifest = load_shipped_manifest()
    manifest.append({
        "tool_name": tool_name,
        "title": spec.get("title", ""),
        "build_id": build_id,
        "question": spec.get("_source_recommendation", {}).get("question", "custom"),
        "files": [str(BUILT_TOOLS_DIR / f) for f in files.keys()],
        "shipped_at": now.isoformat(),
        "tests_passed": test_results.get("syntax_ok", False) and test_results.get("run_ok", False),
        "needs_review": not test_results.get("safety_ok", True),
    })
    save_shipped_manifest(manifest)
    P(f"   📋 Manifest updated ({len(manifest)} tools shipped)")

    # 3. Generate README for the tool
    readme_content = f"""# {spec.get('title', tool_name)}

{spec.get('description', '')}

## Architecture
{spec.get('architecture', 'See spec.')}

## Files
"""
    for f_spec in spec.get("files", []):
        readme_content += f"- `{f_spec.get('path', '')}` — {f_spec.get('purpose', '')}\n"

    readme_content += f"""
## Acceptance Criteria
"""
    for ac in spec.get("acceptance_criteria", []):
        readme_content += f"- {ac}\n"

    if spec.get("dependencies"):
        readme_content += f"\n## Dependencies\n"
        for dep in spec["dependencies"]:
            readme_content += f"- {dep}\n"

    if not test_results.get("safety_ok", True):
        readme_content += f"\n## ⚠️ Safety Review Required\n"
        for c in test_results.get("safety_concerns", []):
            readme_content += f"- {c}\n"

    readme_content += f"\n---\n*Built by Builder agent on {now.strftime('%Y-%m-%d %H:%M UTC')}*\n"
    readme_content += f"*Build ID: {build_id}*\n"

    readme_path = BUILT_TOOLS_DIR / f"{tool_name}-README.md"
    readme_path.write_text(readme_content)
    P(f"   📄 README: {readme_path}")

    # 4. Agent report
    report = {
        "agent": "builder",
        "timestamp": now.isoformat(),
        "build_id": build_id,
        "tool_name": tool_name,
        "title": spec.get("title", ""),
        "description": spec.get("description", ""),
        "files_generated": list(files.keys()),
        "tests": {
            "syntax": test_results.get("syntax_ok", False),
            "safety": test_results.get("safety_ok", True),
            "execution": test_results.get("run_ok"),
        },
        "needs_human_review": not test_results.get("safety_ok", True),
        "source_question": spec.get("_source_recommendation", {}).get("question", "custom"),
    }
    report_path = REPORTS_DIR / f"builder-{now.strftime('%Y-%m-%d')}.json"
    # Append if multiple builds today
    if report_path.exists():
        try:
            existing = json.loads(report_path.read_text())
            if isinstance(existing, list):
                existing.append(report)
            else:
                existing = [existing, report]
            report_path.write_text(json.dumps(existing, indent=2))
        except (json.JSONDecodeError, FileNotFoundError):
            report_path.write_text(json.dumps([report], indent=2))
    else:
        report_path.write_text(json.dumps([report], indent=2))
    P(f"   📊 Report: {report_path}")

    # 5. Post-ship validation
    P("   🔍 Running post-ship validation...")
    main_file = None
    for f in files.keys():
        if tool_name.replace("-", "_") in f and f.endswith(".py") and "test" not in f:
            main_file = BUILT_TOOLS_DIR / f
            break
    
    validation_passed = True
    if main_file and main_file.exists():
        # Test --help
        try:
            result = subprocess.run(
                [sys.executable, str(main_file), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=BUILT_TOOLS_DIR
            )
            if result.returncode == 0:
                P(f"      ✅ --help works")
            else:
                P(f"      ⚠️ --help failed (exit {result.returncode})")
                validation_passed = False
        except Exception as e:
            P(f"      ⚠️ --help test failed: {e}")
            validation_passed = False
        
        # Basic smoke test (if tool has --status or --dry-run)
        for flag in ["--status", "--dry-run"]:
            try:
                result = subprocess.run(
                    [sys.executable, str(main_file), flag],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=BUILT_TOOLS_DIR
                )
                if result.returncode == 0:
                    P(f"      ✅ {flag} works")
                    break
            except Exception:
                pass
    
    # 6. Register tool in registry
    try:
        sys.path.insert(0, str(CEO_DIR / "tools"))
        from registry import register_tool
        
        manifest_entry = {
            "tool_name": tool_name,
            "title": spec.get("title", ""),
            "build_id": build_id,
            "question": spec.get("_source_recommendation", {}).get("question", "custom"),
            "files": [str(BUILT_TOOLS_DIR / f) for f in files.keys()],
            "shipped_at": now.isoformat(),
            "tests_passed": test_results.get("syntax_ok", False) and test_results.get("run_ok", False),
            "needs_review": not test_results.get("safety_ok", True),
        }
        register_tool(manifest_entry)
        P(f"   📋 Registered in tool registry")
    except Exception as e:
        P(f"   ⚠️ Registry registration failed: {e}")
    
    # 7. Log ship event to events.jsonl
    try:
        from events import log_event
        log_event("builder", "ship", {
            "tool_name": tool_name,
            "build_id": build_id,
            "validation_passed": validation_passed,
            "tests_passed": test_results.get("syntax_ok", False) and test_results.get("run_ok", False),
        })
    except Exception as e:
        P(f"   ⚠️ Event logging failed: {e}")

    return build_log


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------

def cmd_list():
    """Show available recommendations."""
    recs = load_recommendations()
    if not recs:
        P("❌ No recommendations found. Run Nexus first.")
        return

    shipped = load_shipped_manifest()
    shipped_questions = {s.get("question", "") for s in shipped}

    P(f"\n{'='*70}")
    P(f"📋 NEXUS RECOMMENDATIONS ({len(recs)} available)")
    P(f"{'='*70}\n")

    for i, rec in enumerate(recs):
        q = rec.get("question", "?")
        built = "✅ BUILT" if q in shipped_questions else "⬜ PENDING"
        P(f"  [{i}] [{rec.get('priority', '?').upper()}] {built}")
        P(f"      {q[:90]}")
        P(f"      Why: {rec.get('reason', '')[:80]}")
        P()


def cmd_status():
    """Show what's been built."""
    manifest = load_shipped_manifest()

    P(f"\n{'='*70}")
    P(f"🏗️  BUILDER STATUS ({len(manifest)} tools shipped)")
    P(f"{'='*70}\n")

    if not manifest:
        P("  No tools built yet. Run: python3 builder.py")
        return

    for entry in manifest:
        review = " ⚠️ NEEDS REVIEW" if entry.get("needs_review") else ""
        passed = "✅" if entry.get("tests_passed") else "❌"
        P(f"  {passed} {entry.get('title', entry.get('tool_name', '?'))}{review}")
        P(f"     Built: {entry.get('shipped_at', '?')[:10]}")
        P(f"     Files: {', '.join(Path(f).name for f in entry.get('files', []))}")
        P()


def cmd_build(rec_index: int | None = None, question: str | None = None,
              spec_only: bool = False, dry_run: bool = False):
    """Full build cycle."""
    build_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)

    P(f"\n{'='*70}")
    P(f"🔨 BUILDER — Tool Smith Cycle")
    P(f"📅 {now.strftime('%Y-%m-%d %H:%M UTC')} | Build ID: {build_id}")
    P(f"{'='*70}\n")

    # Step 1: Select what to build
    if question:
        P(f"📝 Custom build request: {question[:80]}")
        recommendation = {
            "question": question,
            "priority": "custom",
            "reason": "User-specified build request",
            "expected_value": question,
        }
    else:
        recs = load_recommendations()
        if not recs:
            P("❌ No recommendations. Run Nexus first, or use --from-question.")
            return
        recommendation = select_recommendation(recs, rec_index)
        if not recommendation:
            return

    P(f"\n🎯 Building for: {recommendation.get('question', '?')[:90]}")
    P(f"   Priority: {recommendation.get('priority', '?')}")
    P(f"   Reason: {recommendation.get('reason', '')[:100]}")

    # Step 2: Load context
    P("\n📚 Loading context...")
    nexus_context = load_nexus_context()
    knowledge_summary = load_knowledge_summary()
    P(f"   Nexus context: {len(nexus_context):,} chars")
    P(f"   Knowledge base: loaded")

    # Step 3: Generate spec
    P(f"\n📐 Step 1/4: Generating spec...")
    spec = generate_spec(recommendation, nexus_context, knowledge_summary)
    spec_path = save_spec(spec)

    P(f"\n   Tool: {spec.get('title', '?')}")
    P(f"   Description: {spec.get('description', '')[:120]}")
    P(f"   Files: {len(spec.get('files', []))}")
    P(f"   Complexity: {spec.get('estimated_complexity', '?')}")
    if spec.get("acceptance_criteria"):
        P(f"   Criteria:")
        for ac in spec["acceptance_criteria"][:5]:
            P(f"     • {ac[:80]}")

    if dry_run:
        P(f"\n{'='*70}")
        P(f"🏁 DRY RUN — spec generated, nothing built")
        P(f"   Spec: {spec_path}")
        P(f"{'='*70}")
        return

    if spec_only:
        P(f"\n{'='*70}")
        P(f"🏁 SPEC ONLY — ready for build")
        P(f"   Spec: {spec_path}")
        P(f"{'='*70}")
        return

    # Step 4: Build
    P(f"\n🔨 Step 2/4: Building tool...")
    files = build_tool(spec, nexus_context)
    paths = write_built_files(files)

    # Step 5: Test
    P(f"\n🧪 Step 3/4: Testing...")
    test_results = test_tool(files, spec)

    # Step 6: Ship
    P(f"\n📦 Step 4/4: Shipping...")
    build_log = ship_tool(spec, files, test_results, build_id)

    # Summary
    syntax = "✅" if test_results.get("syntax_ok") else "❌"
    safety = "✅" if test_results.get("safety_ok") else "⚠️  NEEDS REVIEW"
    run = "✅" if test_results.get("run_ok") else ("⚠️  NEEDS REVIEW" if test_results.get("run_ok") is None else "❌")

    P(f"\n{'='*70}")
    P(f"🏁 BUILD COMPLETE — {spec.get('title', '?')}")
    P(f"{'='*70}")
    P(f"   Build ID:  {build_id}")
    P(f"   Syntax:    {syntax}")
    P(f"   Safety:    {safety}")
    P(f"   Execution: {run}")
    P(f"   Files:     {', '.join(str(p) for p in paths)}")
    P(f"   Spec:      {spec_path}")
    if not test_results.get("safety_ok"):
        P(f"\n   ⚠️  This tool contains network/system calls.")
        P(f"   ⚠️  Review the code before running it in production.")
    P(f"{'='*70}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Builder — The Tool Smith Agent")
    parser.add_argument("--list", action="store_true", help="Show available recommendations")
    parser.add_argument("--status", action="store_true", help="Show what's been built")
    parser.add_argument("--spec-only", action="store_true", help="Generate spec only, don't build")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be built")
    parser.add_argument("--from-rec", type=int, default=None, metavar="N",
                        help="Use recommendation #N (0-indexed)")
    parser.add_argument("--from-question", type=str, default=None, metavar="Q",
                        help="Build a tool for a custom question/need")
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.status:
        cmd_status()
    else:
        cmd_build(
            rec_index=args.from_rec,
            question=args.from_question,
            spec_only=args.spec_only,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
