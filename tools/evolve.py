#!/usr/bin/env python3
"""
evolve.py — The Self-Improvement Agent

This agent reads its own system's code, analyzes effectiveness, and generates
concrete improvements. It's brutally honest about what's working and what's not.

The goal: Make the Agentic CEO system better at what it does by identifying
inefficiencies, error patterns, cost waste, and capability gaps.

Usage:
    python3 evolve.py                # Full analysis + improvement plan
    python3 evolve.py --metrics      # Just show performance metrics
    python3 evolve.py --code         # Analyze code only
    python3 evolve.py --knowledge    # Analyze knowledge base quality only
    python3 evolve.py --patches      # Generate improvement patches
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Any

# Resolve paths
CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"
TOOLS_DIR = CEO_DIR / "tools"
PATCHES_DIR = STATE_DIR / "patches"
PATCHES_DIR.mkdir(parents=True, exist_ok=True)


from api import call_claude as _call_claude_base, get_api_key

def call_claude(system: str, user: str, model: str = "claude-sonnet-4-20250514") -> str:
    """Call Claude API for analysis."""
    return _call_claude_base(system, user, model=model, max_tokens=4096)


class CodeAnalyzer:
    """Analyzes Python code for efficiency, error handling, and patterns."""
    
    def __init__(self):
        self.analyses = []
    
    def analyze_file(self, filepath: Path) -> Dict[str, Any]:
        """Analyze a single Python file."""
        try:
            content = filepath.read_text()
            tree = ast.parse(content)
            
            analysis = {
                "file": str(filepath.relative_to(CEO_DIR)),
                "lines": len(content.splitlines()),
                "functions": [],
                "classes": [],
                "imports": [],
                "llm_calls": [],
                "error_handling": [],
                "performance_issues": [],
                "code_smells": []
            }
            
            # Analyze AST
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis["functions"].append({
                        "name": node.name,
                        "line": node.lineno,
                        "args": len(node.args.args),
                        "docstring": ast.get_docstring(node) is not None
                    })
                
                elif isinstance(node, ast.ClassDef):
                    analysis["classes"].append({
                        "name": node.name,
                        "line": node.lineno,
                        "methods": len([n for n in node.body if isinstance(n, ast.FunctionDef)])
                    })
                
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        analysis["imports"].append(alias.name)
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        analysis["imports"].append(node.module)
            
            # Look for LLM calls in source code
            llm_patterns = [
                r"call_claude\(",
                r"client\.messages\.create\(",
                r"openai\.ChatCompletion\.create\(",
                r"anthropic\.Anthropic\("
            ]
            
            for i, line in enumerate(content.splitlines(), 1):
                for pattern in llm_patterns:
                    if re.search(pattern, line):
                        analysis["llm_calls"].append({
                            "line": i,
                            "type": pattern,
                            "content": line.strip()
                        })
            
            # Look for error handling patterns
            try_blocks = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
            analysis["error_handling"] = [
                {
                    "line": node.lineno,
                    "handlers": len(node.handlers),
                    "has_finally": bool(node.finalbody),
                    "has_else": bool(node.orelse)
                }
                for node in try_blocks
            ]
            
            # Identify performance issues
            self._find_performance_issues(content, analysis)
            
            # Identify code smells
            self._find_code_smells(content, tree, analysis)
            
            return analysis
            
        except Exception as e:
            return {
                "file": str(filepath.relative_to(CEO_DIR)),
                "error": str(e),
                "lines": 0
            }
    
    def _find_performance_issues(self, content: str, analysis: Dict):
        """Find potential performance issues in code."""
        issues = []
        lines = content.splitlines()
        
        for i, line in enumerate(lines, 1):
            # O(n²) loops
            if "for" in line and any(x in lines[j] for j in range(max(0, i-5), min(len(lines), i+5)) for x in ["for"]):
                if re.search(r'for.*for.*in', " ".join(lines[max(0, i-2):i+3])):
                    issues.append({"line": i, "type": "nested_loops", "description": "Potential O(n²) complexity"})
            
            # Inefficient string concatenation
            if "+=" in line and '"' in line:
                issues.append({"line": i, "type": "string_concat", "description": "Inefficient string concatenation"})
            
            # Blocking calls without timeout
            if re.search(r"requests\.(get|post)", line) and "timeout" not in line:
                issues.append({"line": i, "type": "no_timeout", "description": "HTTP request without timeout"})
        
        analysis["performance_issues"] = issues
    
    def _find_code_smells(self, content: str, tree: ast.AST, analysis: Dict):
        """Find code smells and anti-patterns."""
        smells = []
        
        # Long functions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_lines = node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0
                if func_lines > 50:
                    smells.append({
                        "line": node.lineno,
                        "type": "long_function",
                        "description": f"Function '{node.name}' is {func_lines} lines long"
                    })
        
        # Magic numbers
        for line_num, line in enumerate(content.splitlines(), 1):
            # Look for hardcoded numbers (excluding common ones)
            numbers = re.findall(r'\b(?<!\.)\d+(?!\d*\.)\b', line)
            for num in numbers:
                if int(num) not in [0, 1, 2, 10, 100, 1000] and len(num) > 2:
                    smells.append({
                        "line": line_num,
                        "type": "magic_number",
                        "description": f"Magic number: {num}"
                    })
        
        analysis["code_smells"] = smells
    
    def analyze_all(self) -> List[Dict]:
        """Analyze all Python files in the tools directory."""
        py_files = list(TOOLS_DIR.glob("*.py"))
        
        for filepath in py_files:
            analysis = self.analyze_file(filepath)
            self.analyses.append(analysis)
        
        return self.analyses


class MetricsAnalyzer:
    """Analyzes performance metrics from state files."""
    
    def __init__(self):
        self.metrics = {}
    
    def calculate_metrics(self) -> Dict[str, Any]:
        """Calculate key performance metrics from state files."""
        metrics = {
            "frameworks": self._analyze_frameworks(),
            "cost": self._analyze_cost(),
            "sources": self._analyze_sources(),
            "hunts": self._analyze_hunts(),
            "agents": self._analyze_agents(),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
        self.metrics = metrics
        return metrics
    
    def _analyze_frameworks(self) -> Dict[str, Any]:
        """Analyze framework extraction metrics."""
        all_frameworks = list(KNOWLEDGE_DIR.rglob("*.json"))
        
        if not all_frameworks:
            return {
                "total": 0,
                "by_domain": {},
                "by_confidence": {},
                "avg_confidence": 0.0
            }
        
        domain_counts = defaultdict(int)
        confidence_buckets = {"high": 0, "medium": 0, "low": 0}
        confidence_sum = 0
        confidence_count = 0
        
        for fw_path in all_frameworks:
            try:
                fw_data = json.loads(fw_path.read_text())
                domain = fw_data.get("domain", "unknown")
                domain_counts[domain] += 1
                
                conf = fw_data.get("confidence", 0.5)
                confidence_sum += conf
                confidence_count += 1
                
                if conf >= 0.7:
                    confidence_buckets["high"] += 1
                elif conf >= 0.5:
                    confidence_buckets["medium"] += 1
                else:
                    confidence_buckets["low"] += 1
            except Exception:
                continue
        
        return {
            "total": len(all_frameworks),
            "by_domain": dict(domain_counts),
            "by_confidence": confidence_buckets,
            "avg_confidence": confidence_sum / confidence_count if confidence_count > 0 else 0.0,
            "quality_score": confidence_buckets["high"] / len(all_frameworks) if all_frameworks else 0.0
        }
    
    def _analyze_cost(self) -> Dict[str, Any]:
        """Analyze cost efficiency from ingest logs."""
        ingest_log_path = STATE_DIR / "ingest-log.json"
        
        if not ingest_log_path.exists():
            return {"total_cost": 0, "frameworks_per_dollar": 0, "cost_per_framework": 0}
        
        try:
            ingest_data = json.loads(ingest_log_path.read_text())
            total_frameworks = sum(entry.get("extraction_count", 0) for entry in ingest_data)
            
            # Estimate cost based on typical API usage
            total_cost = len(ingest_data) * 0.01  # Rough estimate
            
            return {
                "total_cost": total_cost,
                "frameworks_per_dollar": total_frameworks / total_cost if total_cost > 0 else 0,
                "cost_per_framework": total_cost / total_frameworks if total_frameworks > 0 else 0,
                "total_sources": len(ingest_data),
                "total_frameworks": total_frameworks
            }
        except Exception:
            return {"error": "Could not parse ingest log"}
    
    def _analyze_sources(self) -> Dict[str, Any]:
        """Analyze source success rates."""
        # Check for obstacles.json
        obstacles_path = STATE_DIR / "obstacles.json"
        success_rate = 1.0  # Assume good by default
        
        if obstacles_path.exists():
            try:
                obstacles = json.loads(obstacles_path.read_text())
                total_attempts = len(obstacles)
                failed_attempts = len([obs for obs in obstacles if obs.get("failed", False)])
                success_rate = 1 - (failed_attempts / total_attempts) if total_attempts > 0 else 1.0
            except Exception:
                pass
        
        # Analyze ingest log for source diversity
        ingest_log_path = STATE_DIR / "ingest-log.json"
        source_domains = set()
        
        if ingest_log_path.exists():
            try:
                ingest_data = json.loads(ingest_log_path.read_text())
                for entry in ingest_data:
                    url = entry.get("source", "")
                    if url:
                        domain = url.split("//")[-1].split("/")[0] if "//" in url else ""
                        if domain:
                            source_domains.add(domain)
            except Exception:
                pass
        
        return {
            "success_rate": success_rate,
            "unique_domains": len(source_domains),
            "domain_diversity": list(source_domains)[:10]  # Top 10
        }
    
    def _analyze_hunts(self) -> Dict[str, Any]:
        """Analyze hunt efficiency."""
        hunts_dir = STATE_DIR / "hunts"
        
        if not hunts_dir.exists():
            return {"total_hunts": 0, "avg_cost": 0, "avg_frameworks": 0}
        
        hunt_files = [f for f in hunts_dir.glob("*.json") if not f.stem.endswith("-synthesis")]
        
        if not hunt_files:
            return {"total_hunts": 0, "avg_cost": 0, "avg_frameworks": 0}
        
        total_cost = 0
        total_frameworks = 0
        total_sources = 0
        
        for hunt_file in hunt_files:
            try:
                hunt_data = json.loads(hunt_file.read_text())
                total_cost += hunt_data.get("cost", 0)
                total_frameworks += hunt_data.get("frameworks_found", 0)
                total_sources += hunt_data.get("sources_processed", 0)
            except Exception:
                continue
        
        num_hunts = len(hunt_files)
        
        return {
            "total_hunts": num_hunts,
            "avg_cost": total_cost / num_hunts if num_hunts > 0 else 0,
            "avg_frameworks": total_frameworks / num_hunts if num_hunts > 0 else 0,
            "avg_sources": total_sources / num_hunts if num_hunts > 0 else 0,
            "frameworks_per_source": total_frameworks / total_sources if total_sources > 0 else 0
        }
    
    def _analyze_agents(self) -> Dict[str, Any]:
        """Analyze agent performance from reports."""
        reports_dir = STATE_DIR / "agent-reports"
        
        if not reports_dir.exists():
            return {"active_agents": 0, "last_activity": None}
        
        report_files = list(reports_dir.glob("*.json"))
        agent_activity = {}
        
        for report_file in report_files:
            try:
                report_data = json.loads(report_file.read_text())
                agent_name = report_data.get("agent", "unknown")
                timestamp = report_data.get("timestamp", "")
                agent_activity[agent_name] = timestamp
            except Exception:
                continue
        
        return {
            "active_agents": len(agent_activity),
            "agents": list(agent_activity.keys()),
            "last_activity": max(agent_activity.values()) if agent_activity else None
        }


class ImprovementGenerator:
    """Generates concrete improvement suggestions."""
    
    def __init__(self, code_analyses: List[Dict], metrics: Dict):
        self.code_analyses = code_analyses
        self.metrics = metrics
        self.improvements = []
    
    def generate_improvements(self) -> List[Dict[str, Any]]:
        """Generate improvement suggestions based on analysis."""
        improvements = []
        
        # Analyze code inefficiencies
        improvements.extend(self._suggest_code_improvements())
        
        # Analyze cost inefficiencies
        improvements.extend(self._suggest_cost_improvements())
        
        # Analyze reliability improvements
        improvements.extend(self._suggest_reliability_improvements())
        
        # Analyze capability gaps
        improvements.extend(self._suggest_capability_improvements())
        
        self.improvements = improvements
        return improvements
    
    def _suggest_code_improvements(self) -> List[Dict]:
        """Suggest code-level improvements."""
        improvements = []
        
        for analysis in self.code_analyses:
            if "error" in analysis:
                continue
            
            file = analysis["file"]
            
            # Check for inefficient LLM usage
            llm_calls = analysis.get("llm_calls", [])
            if len(llm_calls) > 5:
                improvements.append({
                    "id": str(uuid.uuid4()),
                    "target": file,
                    "type": "efficiency",
                    "description": f"File {file} has {len(llm_calls)} LLM calls. Consider batching related calls to reduce API overhead.",
                    "impact": "high",
                    "effort": "medium",
                    "code_suggestion": "Batch multiple prompts into single API calls where semantically appropriate"
                })
            
            # Check for missing error handling
            functions = analysis.get("functions", [])
            error_handlers = analysis.get("error_handling", [])
            if len(functions) > 3 and len(error_handlers) == 0:
                improvements.append({
                    "id": str(uuid.uuid4()),
                    "target": file,
                    "type": "reliability",
                    "description": f"File {file} has {len(functions)} functions but no try/catch blocks. Add error handling for robustness.",
                    "impact": "high",
                    "effort": "low",
                    "code_suggestion": "Add try/catch blocks around API calls and file operations"
                })
            
            # Check performance issues
            perf_issues = analysis.get("performance_issues", [])
            if perf_issues:
                for issue in perf_issues:
                    improvements.append({
                        "id": str(uuid.uuid4()),
                        "target": file,
                        "type": "efficiency",
                        "description": f"Line {issue['line']}: {issue['description']}",
                        "impact": "medium",
                        "effort": "low" if issue["type"] in ["no_timeout", "string_concat"] else "medium",
                        "code_suggestion": self._get_performance_fix_suggestion(issue)
                    })
        
        return improvements
    
    def _suggest_cost_improvements(self) -> List[Dict]:
        """Suggest cost optimization improvements."""
        improvements = []
        
        cost_metrics = self.metrics.get("cost", {})
        frameworks_per_dollar = cost_metrics.get("frameworks_per_dollar", 0)
        
        if frameworks_per_dollar < 50:  # Low efficiency threshold
            improvements.append({
                "id": str(uuid.uuid4()),
                "target": "system_wide",
                "type": "cost",
                "description": f"Current efficiency is {frameworks_per_dollar:.1f} frameworks per dollar. Consider optimizing prompt templates to extract more frameworks per API call.",
                "impact": "high",
                "effort": "medium",
                "code_suggestion": "Review extraction prompts and batch multiple extraction tasks"
            })
        
        return improvements
    
    def _suggest_reliability_improvements(self) -> List[Dict]:
        """Suggest reliability improvements."""
        improvements = []
        
        sources_metrics = self.metrics.get("sources", {})
        success_rate = sources_metrics.get("success_rate", 1.0)
        
        if success_rate < 0.8:
            improvements.append({
                "id": str(uuid.uuid4()),
                "target": "source_handling",
                "type": "reliability",
                "description": f"Source success rate is {success_rate:.2%}. Implement better retry logic and source validation.",
                "impact": "high",
                "effort": "medium",
                "code_suggestion": "Add exponential backoff retry logic and source validation before processing"
            })
        
        return improvements
    
    def _suggest_capability_improvements(self) -> List[Dict]:
        """Suggest new capabilities that could be added."""
        improvements = []
        
        frameworks_metrics = self.metrics.get("frameworks", {})
        by_domain = frameworks_metrics.get("by_domain", {})
        
        # Check for domain gaps
        expected_domains = ["ai-systems", "manufacturing", "strategy", "leadership", "finance", "technology"]
        missing_domains = [d for d in expected_domains if d not in by_domain or by_domain[d] < 5]
        
        if missing_domains:
            improvements.append({
                "id": str(uuid.uuid4()),
                "target": "knowledge_coverage",
                "type": "capability",
                "description": f"Weak coverage in domains: {', '.join(missing_domains)}. Need targeted hunting in these areas.",
                "impact": "medium",
                "effort": "low",
                "code_suggestion": "Create focused hunt missions for underrepresented domains"
            })
        
        return improvements
    
    def _get_performance_fix_suggestion(self, issue: Dict) -> str:
        """Get specific fix suggestion for performance issue."""
        issue_type = issue["type"]
        
        suggestions = {
            "nested_loops": "Consider using hash maps, sets, or vectorized operations instead of nested loops",
            "string_concat": "Use join() or f-strings instead of += for string concatenation",
            "no_timeout": "Add timeout parameter to prevent hanging requests"
        }
        
        return suggestions.get(issue_type, "Review and optimize this code section")


class KnowledgeAnalyzer:
    """Analyzes the quality of the knowledge base."""
    
    def __init__(self):
        self.quality_issues = []
    
    def analyze_knowledge_base(self) -> Dict[str, Any]:
        """Analyze knowledge base quality and identify issues."""
        all_frameworks = list(KNOWLEDGE_DIR.rglob("*.json"))
        
        if not all_frameworks:
            return {
                "total_frameworks": 0,
                "quality_issues": [],
                "duplicates": [],
                "recommendations": ["No frameworks found - system needs initial knowledge ingestion"]
            }
        
        frameworks = []
        for fw_path in all_frameworks:
            try:
                fw_data = json.loads(fw_path.read_text())
                # Ensure we have a dictionary, not a list
                if isinstance(fw_data, dict):
                    frameworks.append(fw_data)
            except Exception:
                continue
        
        quality_issues = []
        duplicates = []
        recommendations = []
        
        # Check for low-quality frameworks
        low_quality = [fw for fw in frameworks if self._is_low_quality(fw)]
        if low_quality:
            quality_issues.append({
                "type": "low_quality",
                "count": len(low_quality),
                "description": f"{len(low_quality)} frameworks are low quality (generic, shallow, or missing fields)"
            })
        
        # Check for duplicates
        duplicates = self._find_duplicates(frameworks)
        if duplicates:
            quality_issues.append({
                "type": "duplicates",
                "count": len(duplicates),
                "description": f"Found {len(duplicates)} potential duplicate frameworks"
            })
        
        # Check domain balance
        domain_balance = self._check_domain_balance(frameworks)
        if domain_balance["imbalanced"]:
            quality_issues.append({
                "type": "domain_imbalance",
                "description": "Knowledge base is imbalanced across domains",
                "details": domain_balance
            })
        
        # Generate recommendations
        recommendations = self._generate_quality_recommendations(frameworks, quality_issues)
        
        return {
            "total_frameworks": len(frameworks),
            "quality_score": self._calculate_quality_score(frameworks),
            "quality_issues": quality_issues,
            "duplicates": duplicates,
            "domain_coverage": domain_balance,
            "recommendations": recommendations
        }
    
    def _is_low_quality(self, framework: Dict) -> bool:
        """Check if a framework is low quality."""
        description = framework.get("description", "")
        name = framework.get("name", "")
        confidence = framework.get("confidence", 0.5)
        
        # Check for generic content
        generic_words = ["thing", "approach", "method", "way", "system", "process"]
        if any(word in description.lower() for word in generic_words) and len(description) < 100:
            return True
        
        # Check for missing key fields
        if not name or len(name) < 5:
            return True
        
        if not description or len(description) < 20:
            return True
        
        # Check confidence
        if confidence < 0.3:
            return True
        
        return False
    
    def _find_duplicates(self, frameworks: List[Dict]) -> List[Dict]:
        """Find potential duplicate frameworks."""
        duplicates = []
        
        for i, fw1 in enumerate(frameworks):
            for j, fw2 in enumerate(frameworks[i+1:], i+1):
                similarity = self._calculate_similarity(fw1, fw2)
                if similarity > 0.8:
                    duplicates.append({
                        "framework1": fw1.get("id", "unknown"),
                        "framework2": fw2.get("id", "unknown"),
                        "similarity": similarity,
                        "name1": fw1.get("name", ""),
                        "name2": fw2.get("name", "")
                    })
        
        return duplicates
    
    def _calculate_similarity(self, fw1: Dict, fw2: Dict) -> float:
        """Calculate similarity between two frameworks."""
        name1 = fw1.get("name", "").lower()
        name2 = fw2.get("name", "").lower()
        desc1 = fw1.get("description", "").lower()
        desc2 = fw2.get("description", "").lower()
        
        # Simple word overlap similarity
        words1 = set(name1.split() + desc1.split())
        words2 = set(name2.split() + desc2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def _check_domain_balance(self, frameworks: List[Dict]) -> Dict:
        """Check if domains are balanced."""
        domain_counts = defaultdict(int)
        
        for fw in frameworks:
            domain = fw.get("domain", "unknown")
            domain_counts[domain] += 1
        
        total = len(frameworks)
        domain_percentages = {domain: count/total for domain, count in domain_counts.items()}
        
        # Check if any domain has >50% or <5%
        imbalanced = any(pct > 0.5 or pct < 0.05 for pct in domain_percentages.values() if total > 20)
        
        return {
            "counts": dict(domain_counts),
            "percentages": domain_percentages,
            "imbalanced": imbalanced
        }
    
    def _calculate_quality_score(self, frameworks: List[Dict]) -> float:
        """Calculate overall quality score."""
        if not frameworks:
            return 0.0
        
        total_score = 0
        for fw in frameworks:
            score = 0
            
            # Confidence score
            score += fw.get("confidence", 0.5) * 0.4
            
            # Description quality (length and content)
            desc = fw.get("description", "")
            if len(desc) > 50:
                score += 0.3
            elif len(desc) > 20:
                score += 0.15
            
            # Has tags
            if fw.get("tags", []):
                score += 0.1
            
            # Has source
            if fw.get("source", {}).get("url"):
                score += 0.1
            
            # Not generic
            if not self._is_low_quality(fw):
                score += 0.1
            
            total_score += score
        
        return total_score / len(frameworks)
    
    def _generate_quality_recommendations(self, frameworks: List[Dict], issues: List[Dict]) -> List[str]:
        """Generate recommendations for improving knowledge quality."""
        recommendations = []
        
        if len(frameworks) < 100:
            recommendations.append("Knowledge base is small - continue targeted hunting to reach critical mass")
        
        for issue in issues:
            if issue["type"] == "low_quality":
                recommendations.append("Improve extraction prompts to capture more detailed frameworks with higher confidence")
            elif issue["type"] == "duplicates":
                recommendations.append("Implement deduplication logic to prevent similar frameworks from being stored")
            elif issue["type"] == "domain_imbalance":
                recommendations.append("Focus hunting efforts on underrepresented domains")
        
        # Check for missing capabilities
        domains = set(fw.get("domain", "unknown") for fw in frameworks)
        if "podcasts" not in [fw.get("source", {}).get("type", "") for fw in frameworks]:
            recommendations.append("Add podcast ingestion capability using yt-dlp for podcast RSS feeds")
        
        return recommendations


class PatchGenerator:
    """Generates code patches for safe improvements."""
    
    def __init__(self, improvements: List[Dict]):
        self.improvements = improvements
    
    def generate_patches(self) -> List[Dict]:
        """Generate patches for low-effort, high-impact improvements."""
        patches = []
        
        for improvement in self.improvements:
            if improvement.get("effort") == "low" and improvement.get("impact") == "high":
                patch = self._create_patch(improvement)
                if patch:
                    patches.append(patch)
        
        return patches
    
    def _create_patch(self, improvement: Dict) -> Dict | None:
        """Create a specific patch for an improvement."""
        target = improvement.get("target", "")
        improvement_type = improvement.get("type", "")
        
        if improvement_type == "reliability" and "error handling" in improvement.get("description", "").lower():
            return self._create_error_handling_patch(target, improvement)
        elif improvement_type == "efficiency" and "timeout" in improvement.get("description", "").lower():
            return self._create_timeout_patch(target, improvement)
        
        return None
    
    def _create_error_handling_patch(self, target: str, improvement: Dict) -> Dict:
        """Create a patch to add error handling."""
        patch_id = improvement["id"]
        
        patch_content = f"""# Patch for adding error handling to {target}
# Generated by evolve.py on {datetime.now().isoformat()}

# Add this try/catch pattern around API calls and file operations:

try:
    # Existing code here
    result = risky_operation()
    return result
except Exception as e:
    print(f"Error in {{operation_name}}: {{e}}")
    # Handle the error appropriately:
    # - Return None/empty result
    # - Log the error
    # - Retry with exponential backoff
    # - Fall back to alternative approach
    return None
"""
        
        patch = {
            "id": patch_id,
            "target": target,
            "type": "error_handling",
            "description": improvement["description"],
            "patch_content": patch_content,
            "auto_apply": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Save patch to file
        patch_file = PATCHES_DIR / f"{patch_id}.patch"
        patch_file.write_text(json.dumps(patch, indent=2))
        
        return patch
    
    def _create_timeout_patch(self, target: str, improvement: Dict) -> Dict:
        """Create a patch to add timeouts to requests."""
        patch_id = improvement["id"]
        
        patch_content = f"""# Patch for adding timeouts to {target}
# Generated by evolve.py on {datetime.now().isoformat()}

# Replace requests without timeout:
# OLD: requests.get(url)
# NEW: requests.get(url, timeout=15)

# For YouTube downloads:
# OLD: subprocess.run(cmd, capture_output=True, text=True)
# NEW: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
"""
        
        patch = {
            "id": patch_id,
            "target": target,
            "type": "timeout",
            "description": improvement["description"],
            "patch_content": patch_content,
            "auto_apply": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        patch_file = PATCHES_DIR / f"{patch_id}.patch"
        patch_file.write_text(json.dumps(patch, indent=2))
        
        return patch


def create_evolution_plan(code_analyses: List[Dict], metrics: Dict, improvements: List[Dict], knowledge_analysis: Dict) -> Dict:
    """Create the complete evolution plan."""
    
    # Calculate summary statistics
    total_code_lines = sum(a.get("lines", 0) for a in code_analyses if "error" not in a)
    agents_analyzed = [a["file"] for a in code_analyses if "error" not in a]
    
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis": {
            "total_code_lines": total_code_lines,
            "agents_analyzed": agents_analyzed,
            "metrics": {
                "frameworks_per_dollar": metrics.get("cost", {}).get("frameworks_per_dollar", 0),
                "source_success_rate": metrics.get("sources", {}).get("success_rate", 0),
                "avg_confidence": metrics.get("frameworks", {}).get("avg_confidence", 0),
                "total_frameworks": metrics.get("frameworks", {}).get("total", 0),
                "active_agents": metrics.get("agents", {}).get("active_agents", 0),
                "knowledge_quality_score": knowledge_analysis.get("quality_score", 0)
            }
        },
        "improvements": improvements,
        "tool_gaps": [
            {
                "description": "No podcast ingestion capability",
                "impact": "medium",
                "suggested_implementation": "Use yt-dlp for podcast RSS feeds + same transcript pipeline"
            },
            {
                "description": "No automated deduplication system",
                "impact": "medium", 
                "suggested_implementation": "Add similarity detection before framework storage"
            },
            {
                "description": "Limited batch processing for LLM calls",
                "impact": "high",
                "suggested_implementation": "Implement request batching to reduce API costs"
            }
        ],
        "knowledge_base_analysis": knowledge_analysis,
        "recommendations": {
            "immediate_actions": [
                imp for imp in improvements 
                if imp.get("effort") == "low" and imp.get("impact") == "high"
            ][:5],
            "strategic_priorities": [
                "Improve cost efficiency through LLM call batching",
                "Enhance reliability with better error handling",
                "Expand domain coverage in underrepresented areas",
                "Implement knowledge quality controls"
            ],
            "technical_debt": [
                imp for imp in improvements 
                if imp.get("type") in ["efficiency", "reliability"]
            ]
        }
    }
    
    # Save evolution plan
    plan_file = STATE_DIR / "evolution-plan.json"
    plan_file.write_text(json.dumps(plan, indent=2))
    
    return plan


def show_metrics(metrics: Dict):
    """Display metrics in a readable format."""
    print("\n🔍 PERFORMANCE METRICS")
    print("=" * 60)
    
    # Framework metrics
    fw_metrics = metrics.get("frameworks", {})
    print(f"\n📚 Knowledge Base:")
    print(f"  Total frameworks: {fw_metrics.get('total', 0):,}")
    print(f"  Average confidence: {fw_metrics.get('avg_confidence', 0):.3f}")
    print(f"  Quality score: {fw_metrics.get('quality_score', 0):.3f}")
    
    by_domain = fw_metrics.get("by_domain", {})
    if by_domain:
        print(f"  By domain:")
        for domain, count in sorted(by_domain.items(), key=lambda x: x[1], reverse=True):
            print(f"    {domain}: {count}")
    
    # Cost metrics
    cost_metrics = metrics.get("cost", {})
    print(f"\n💰 Cost Efficiency:")
    print(f"  Frameworks per dollar: {cost_metrics.get('frameworks_per_dollar', 0):.1f}")
    print(f"  Cost per framework: ${cost_metrics.get('cost_per_framework', 0):.4f}")
    print(f"  Total cost: ${cost_metrics.get('total_cost', 0):.2f}")
    
    # Source metrics
    source_metrics = metrics.get("sources", {})
    print(f"\n🔗 Source Performance:")
    print(f"  Success rate: {source_metrics.get('success_rate', 0):.1%}")
    print(f"  Unique domains: {source_metrics.get('unique_domains', 0)}")
    
    # Hunt metrics
    hunt_metrics = metrics.get("hunts", {})
    print(f"\n🎯 Hunt Efficiency:")
    print(f"  Total hunts: {hunt_metrics.get('total_hunts', 0)}")
    print(f"  Average cost per hunt: ${hunt_metrics.get('avg_cost', 0):.2f}")
    print(f"  Average frameworks per hunt: {hunt_metrics.get('avg_frameworks', 0):.1f}")
    print(f"  Frameworks per source: {hunt_metrics.get('frameworks_per_source', 0):.2f}")
    
    # Agent metrics
    agent_metrics = metrics.get("agents", {})
    print(f"\n🤖 Agent Activity:")
    print(f"  Active agents: {agent_metrics.get('active_agents', 0)}")
    agents = agent_metrics.get("agents", [])
    if agents:
        print(f"  Agents: {', '.join(agents)}")


def show_improvements(improvements: List[Dict]):
    """Display improvements in a readable format."""
    if not improvements:
        print("\n✅ No significant improvements identified!")
        return
    
    print(f"\n🚀 IMPROVEMENT OPPORTUNITIES ({len(improvements)})")
    print("=" * 60)
    
    # Group by impact level
    by_impact = defaultdict(list)
    for imp in improvements:
        by_impact[imp.get("impact", "medium")].append(imp)
    
    for impact in ["high", "medium", "low"]:
        if impact not in by_impact:
            continue
        
        print(f"\n{impact.upper()} IMPACT ({len(by_impact[impact])} items):")
        
        for imp in by_impact[impact][:5]:  # Show top 5 per category
            effort = imp.get("effort", "?")
            imp_type = imp.get("type", "?")
            target = imp.get("target", "?")
            description = imp.get("description", "")
            
            print(f"\n  [{imp_type}] {target} (effort: {effort})")
            print(f"    {description}")
            
            suggestion = imp.get("code_suggestion", "")
            if suggestion and len(suggestion) < 100:
                print(f"    💡 {suggestion}")


def main():
    parser = argparse.ArgumentParser(description="Agentic CEO Self-Improvement Agent")
    parser.add_argument("--metrics", action="store_true", help="Show performance metrics only")
    parser.add_argument("--code", action="store_true", help="Analyze code only")
    parser.add_argument("--knowledge", action="store_true", help="Analyze knowledge base only") 
    parser.add_argument("--patches", action="store_true", help="Generate improvement patches")
    args = parser.parse_args()
    
    print("🧬 AGENTIC CEO EVOLUTION AGENT")
    print("=" * 70)
    print("Analyzing system effectiveness and generating improvements...")
    
    try:
        # Ensure dependencies
        # Dependencies handled by api.py gateway
        
        if args.metrics:
            metrics_analyzer = MetricsAnalyzer()
            metrics = metrics_analyzer.calculate_metrics()
            show_metrics(metrics)
            return
        
        if args.code:
            print("\n🔍 Analyzing code structure and patterns...")
            code_analyzer = CodeAnalyzer()
            analyses = code_analyzer.analyze_all()
            
            print(f"Analyzed {len(analyses)} Python files:")
            for analysis in analyses:
                if "error" not in analysis:
                    file = analysis["file"]
                    lines = analysis["lines"]
                    functions = len(analysis.get("functions", []))
                    llm_calls = len(analysis.get("llm_calls", []))
                    print(f"  {file}: {lines} lines, {functions} functions, {llm_calls} LLM calls")
            return
        
        if args.knowledge:
            print("\n📚 Analyzing knowledge base quality...")
            knowledge_analyzer = KnowledgeAnalyzer()
            knowledge_analysis = knowledge_analyzer.analyze_knowledge_base()
            
            print(f"Total frameworks: {knowledge_analysis.get('total_frameworks', 0)}")
            print(f"Quality score: {knowledge_analysis.get('quality_score', 0):.3f}")
            
            issues = knowledge_analysis.get("quality_issues", [])
            if issues:
                print(f"\nQuality issues found:")
                for issue in issues:
                    print(f"  - {issue.get('description', 'Unknown issue')}")
            
            recommendations = knowledge_analysis.get("recommendations", [])
            if recommendations:
                print(f"\nRecommendations:")
                for rec in recommendations:
                    print(f"  - {rec}")
            return
        
        if args.patches:
            print("\n🔧 Generating improvement patches...")
            # Need to run full analysis first
            code_analyzer = CodeAnalyzer()
            analyses = code_analyzer.analyze_all()
            
            metrics_analyzer = MetricsAnalyzer()
            metrics = metrics_analyzer.calculate_metrics()
            
            improvement_generator = ImprovementGenerator(analyses, metrics)
            improvements = improvement_generator.generate_improvements()
            
            patch_generator = PatchGenerator(improvements)
            patches = patch_generator.generate_patches()
            
            print(f"Generated {len(patches)} patches for low-effort, high-impact improvements")
            for patch in patches:
                print(f"  - {patch['target']}: {patch['type']}")
                print(f"    Saved to: {PATCHES_DIR}/{patch['id']}.patch")
            return
        
        # Full analysis
        print("\n🔍 Phase 1: Analyzing code structure...")
        code_analyzer = CodeAnalyzer()
        code_analyses = code_analyzer.analyze_all()
        
        print("\n📊 Phase 2: Calculating performance metrics...")
        metrics_analyzer = MetricsAnalyzer()
        metrics = metrics_analyzer.calculate_metrics()
        
        print("\n🚀 Phase 3: Generating improvements...")
        improvement_generator = ImprovementGenerator(code_analyses, metrics)
        improvements = improvement_generator.generate_improvements()
        
        print("\n📚 Phase 4: Analyzing knowledge base...")
        knowledge_analyzer = KnowledgeAnalyzer()
        knowledge_analysis = knowledge_analyzer.analyze_knowledge_base()
        
        print("\n🧬 Phase 5: Creating evolution plan...")
        evolution_plan = create_evolution_plan(code_analyses, metrics, improvements, knowledge_analysis)
        
        # Display results
        show_metrics(metrics)
        show_improvements(improvements)
        
        print(f"\n{'='*70}")
        print("🧬 EVOLUTION PLAN COMPLETE")
        print(f"   Total improvements: {len(improvements)}")
        print(f"   High-impact, low-effort: {len([i for i in improvements if i.get('effort') == 'low' and i.get('impact') == 'high'])}")
        print(f"   Plan saved to: {STATE_DIR}/evolution-plan.json")
        
        immediate_actions = evolution_plan.get("recommendations", {}).get("immediate_actions", [])
        if immediate_actions:
            print(f"\n🎯 IMMEDIATE ACTIONS:")
            for action in immediate_actions[:3]:
                print(f"   • {action.get('description', '')}")
        
        print(f"{'='*70}")
        
    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()