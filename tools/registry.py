#!/usr/bin/env python3
"""
registry.py — Central Tool Registry

Maintains a central registry of all tools in the CEO ecosystem:
- Built-in agents (tools/*.py)
- Builder-shipped tools (tools/built/*)

Tracks health status: last run, errors, usage frequency.

Usage:
    python3 registry.py                      # List all tools
    python3 registry.py --search "barrier"   # Search for tools
    python3 registry.py --detail tool-name   # Show tool details
    python3 registry.py --refresh            # Refresh registry from filesystem
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# Resolve paths
CEO_DIR = Path(__file__).parent.parent
TOOLS_DIR = CEO_DIR / "tools"
BUILT_TOOLS_DIR = TOOLS_DIR / "built" / "tools"
STATE_DIR = CEO_DIR / "state"
MANIFEST_PATH = STATE_DIR / "builder" / "shipped" / "manifest.json"
REGISTRY_PATH = STATE_DIR / "registry.json"
EVENTS_LOG = STATE_DIR / "events.jsonl"

STATE_DIR.mkdir(parents=True, exist_ok=True)


def extract_docstring(filepath: Path) -> str:
    """Extract the module docstring from a Python file."""
    try:
        content = filepath.read_text()
        # Match triple-quoted strings at the start of the file (after comments/shebang)
        match = re.search(r'^\s*(?:#!/[^\n]*\n)?(?:#[^\n]*\n)*\s*["\']{{3}}(.*?)["\']{{3}}', content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""
    except Exception:
        return ""


def extract_description(docstring: str) -> str:
    """Extract first line/paragraph from docstring as description."""
    if not docstring:
        return ""
    lines = [line.strip() for line in docstring.split("\n") if line.strip()]
    if lines:
        return lines[0]
    return ""


def scan_builtin_tools() -> list[dict]:
    """Scan tools/*.py for built-in agents."""
    tools = []
    
    # Known built-in agents (not all .py files are agents)
    agent_files = [
        "hunter.py", "builder.py", "nexus.py", "observer.py", "director.py",
        "critic.py", "evolver.py", "sentinel.py", "equalizer.py", "dissolve.py",
        "bridge.py", "analyst.py", "librarian.py", "scout.py", "orchestrator.py",
        "pipeline.py", "barrier_cycle.py"
    ]
    
    for filename in agent_files:
        filepath = TOOLS_DIR / filename
        if filepath.exists():
            docstring = extract_docstring(filepath)
            description = extract_description(docstring)
            
            tools.append({
                "name": filepath.stem,
                "type": "builtin",
                "path": str(filepath),
                "description": description,
                "docstring": docstring,
            })
    
    return tools


def scan_shipped_tools() -> list[dict]:
    """Scan tools/built/ and manifest.json for shipped tools."""
    tools = []
    
    if not MANIFEST_PATH.exists():
        return tools
    
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
        for entry in manifest:
            tool_name = entry.get("tool_name", "")
            if not tool_name:
                continue
            
            # Find the main tool file
            files = entry.get("files", [])
            main_file = None
            for f in files:
                if tool_name.replace("-", "_") in f and f.endswith(".py") and "test" not in f:
                    main_file = f
                    break
            
            tools.append({
                "name": tool_name,
                "type": "shipped",
                "title": entry.get("title", ""),
                "path": main_file or "",
                "build_id": entry.get("build_id", ""),
                "question": entry.get("question", ""),
                "shipped_at": entry.get("shipped_at", ""),
                "tests_passed": entry.get("tests_passed", False),
                "needs_review": entry.get("needs_review", False),
                "files": files,
            })
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    
    return tools


def load_health_status() -> dict:
    """Load tool health status from events log."""
    health = {}
    
    if not EVENTS_LOG.exists():
        return health
    
    try:
        for line in EVENTS_LOG.read_text().strip().split("\n"):
            if not line.strip():
                continue
            event = json.loads(line)
            tool = event.get("tool")
            if not tool:
                continue
            
            if tool not in health:
                health[tool] = {
                    "run_count": 0,
                    "last_run": None,
                    "last_error": None,
                    "error_count": 0,
                }
            
            event_type = event.get("event_type", "")
            if event_type == "run":
                health[tool]["run_count"] += 1
                health[tool]["last_run"] = event.get("timestamp")
            elif event_type == "error":
                health[tool]["error_count"] += 1
                health[tool]["last_error"] = event.get("timestamp")
    except Exception:
        pass
    
    return health


def build_registry() -> dict:
    """Build the complete tool registry."""
    builtin = scan_builtin_tools()
    shipped = scan_shipped_tools()
    health = load_health_status()
    
    # Merge health status into tools
    for tool in builtin + shipped:
        name = tool["name"]
        if name in health:
            tool["health"] = health[name]
        else:
            tool["health"] = {
                "run_count": 0,
                "last_run": None,
                "last_error": None,
                "error_count": 0,
            }
    
    registry = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "builtin_count": len(builtin),
        "shipped_count": len(shipped),
        "total_count": len(builtin) + len(shipped),
        "tools": builtin + shipped,
    }
    
    return registry


def save_registry(registry: dict) -> None:
    """Save registry to state/registry.json."""
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


def load_registry() -> dict:
    """Load registry from state/registry.json."""
    if not REGISTRY_PATH.exists():
        return build_registry()
    
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return build_registry()


def list_tools() -> list[dict]:
    """List all tools in the registry."""
    registry = load_registry()
    return registry.get("tools", [])


def get_tool(name: str) -> dict | None:
    """Get a specific tool by name."""
    tools = list_tools()
    for tool in tools:
        if tool["name"] == name or tool["name"].replace("-", "_") == name.replace("-", "_"):
            return tool
    return None


def search_tools(query: str) -> list[dict]:
    """Search tools by name, description, or question."""
    tools = list_tools()
    query_lower = query.lower()
    results = []
    
    for tool in tools:
        searchable = " ".join([
            tool.get("name", ""),
            tool.get("description", ""),
            tool.get("title", ""),
            tool.get("question", ""),
        ]).lower()
        
        if query_lower in searchable:
            results.append(tool)
    
    return results


def register_tool(manifest_entry: dict) -> None:
    """Register a new tool (used by Builder after shipping)."""
    registry = load_registry()
    
    # Check if tool already exists
    existing = None
    for i, tool in enumerate(registry["tools"]):
        if tool["name"] == manifest_entry.get("tool_name"):
            existing = i
            break
    
    # Convert manifest entry to registry format
    tool_name = manifest_entry.get("tool_name", "")
    files = manifest_entry.get("files", [])
    main_file = None
    for f in files:
        if tool_name.replace("-", "_") in f and f.endswith(".py") and "test" not in f:
            main_file = f
            break
    
    tool_entry = {
        "name": tool_name,
        "type": "shipped",
        "title": manifest_entry.get("title", ""),
        "path": main_file or "",
        "build_id": manifest_entry.get("build_id", ""),
        "question": manifest_entry.get("question", ""),
        "shipped_at": manifest_entry.get("shipped_at", ""),
        "tests_passed": manifest_entry.get("tests_passed", False),
        "needs_review": manifest_entry.get("needs_review", False),
        "files": files,
        "health": {
            "run_count": 0,
            "last_run": None,
            "last_error": None,
            "error_count": 0,
        }
    }
    
    if existing is not None:
        # Update existing entry
        registry["tools"][existing] = tool_entry
    else:
        # Add new entry
        registry["tools"].append(tool_entry)
        registry["shipped_count"] = registry.get("shipped_count", 0) + 1
        registry["total_count"] = registry.get("total_count", 0) + 1
    
    registry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_registry(registry)


def print_tool_list(tools: list[dict], show_health: bool = False) -> None:
    """Pretty-print a list of tools."""
    if not tools:
        print("  No tools found.")
        return
    
    for tool in tools:
        name = tool.get("name", "?")
        tool_type = tool.get("type", "?")
        description = tool.get("description") or tool.get("title", "")
        
        icon = "🔧" if tool_type == "shipped" else "⚙️"
        print(f"\n  {icon} {name} ({tool_type})")
        if description:
            # Wrap long descriptions
            if len(description) > 70:
                print(f"     {description[:70]}...")
            else:
                print(f"     {description}")
        
        if show_health:
            health = tool.get("health", {})
            run_count = health.get("run_count", 0)
            last_run = health.get("last_run")
            error_count = health.get("error_count", 0)
            
            status_parts = [f"runs: {run_count}"]
            if error_count > 0:
                status_parts.append(f"errors: {error_count}")
            if last_run:
                # Parse and format timestamp
                try:
                    dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                    days_ago = (datetime.now(timezone.utc) - dt).days
                    if days_ago == 0:
                        status_parts.append("last: today")
                    elif days_ago == 1:
                        status_parts.append("last: yesterday")
                    else:
                        status_parts.append(f"last: {days_ago}d ago")
                except Exception:
                    pass
            
            print(f"     [{', '.join(status_parts)}]")


def print_tool_detail(tool: dict) -> None:
    """Pretty-print detailed tool information."""
    print(f"\n{'='*70}")
    print(f"Tool: {tool.get('name', '?')}")
    print(f"{'='*70}\n")
    
    print(f"Type: {tool.get('type', '?')}")
    
    if tool.get("title"):
        print(f"Title: {tool['title']}")
    
    if tool.get("description"):
        print(f"Description: {tool['description']}")
    
    if tool.get("path"):
        print(f"Path: {tool['path']}")
    
    if tool.get("question"):
        print(f"\nOrigin Question:\n  {tool['question']}")
    
    if tool.get("build_id"):
        print(f"\nBuild ID: {tool['build_id']}")
    
    if tool.get("shipped_at"):
        print(f"Shipped: {tool['shipped_at']}")
    
    if tool.get("files"):
        print(f"\nFiles:")
        for f in tool["files"]:
            print(f"  - {f}")
    
    # Health status
    health = tool.get("health", {})
    print(f"\n{'='*70}")
    print(f"Health Status")
    print(f"{'='*70}")
    print(f"Run count: {health.get('run_count', 0)}")
    print(f"Error count: {health.get('error_count', 0)}")
    
    if health.get("last_run"):
        print(f"Last run: {health['last_run']}")
    else:
        print(f"Last run: Never")
    
    if health.get("last_error"):
        print(f"Last error: {health['last_error']}")
    
    print()


def main():
    parser = argparse.ArgumentParser(description="Tool Registry")
    parser.add_argument("--refresh", action="store_true", help="Refresh registry from filesystem")
    parser.add_argument("--search", metavar="QUERY", help="Search for tools")
    parser.add_argument("--detail", metavar="NAME", help="Show detailed info for a tool")
    parser.add_argument("--health", action="store_true", help="Show health status in list")
    args = parser.parse_args()
    
    if args.refresh:
        print("🔄 Refreshing registry...")
        registry = build_registry()
        save_registry(registry)
        print(f"✅ Registry updated: {registry['total_count']} tools ({registry['builtin_count']} builtin, {registry['shipped_count']} shipped)")
        print(f"   Saved to: {REGISTRY_PATH}")
        return
    
    if args.detail:
        tool = get_tool(args.detail)
        if not tool:
            print(f"❌ Tool not found: {args.detail}")
            return
        print_tool_detail(tool)
        return
    
    if args.search:
        results = search_tools(args.search)
        print(f"\n🔍 Search results for '{args.search}': {len(results)} found")
        print_tool_list(results, show_health=args.health)
        print()
        return
    
    # Default: list all tools
    registry = load_registry()
    print(f"\n📋 Tool Registry")
    print(f"{'='*70}")
    print(f"Total: {registry.get('total_count', 0)} tools")
    print(f"  Built-in: {registry.get('builtin_count', 0)}")
    print(f"  Shipped: {registry.get('shipped_count', 0)}")
    print(f"Last updated: {registry.get('updated_at', 'unknown')}")
    print(f"{'='*70}")
    
    tools = registry.get("tools", [])
    
    # Group by type
    builtin = [t for t in tools if t.get("type") == "builtin"]
    shipped = [t for t in tools if t.get("type") == "shipped"]
    
    if builtin:
        print(f"\n⚙️  Built-in Agents ({len(builtin)}):")
        print_tool_list(builtin, show_health=args.health)
    
    if shipped:
        print(f"\n🔧 Shipped Tools ({len(shipped)}):")
        print_tool_list(shipped, show_health=args.health)
    
    print()


if __name__ == "__main__":
    main()
