#!/usr/bin/env python3
"""
DIRECTOR AGENT - Strategic Planning for the Agentic CEO System
=============================================================

The Director is the CEO brain. It plans, prioritizes, and makes strategic decisions.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import requests
import yaml


class DirectorAgent:
    def __init__(self, ceo_dir: str = None):
        if ceo_dir is None:
            ceo_dir = str(Path(__file__).parent.parent)
        self.ceo_dir = Path(ceo_dir)
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Ensure required directories exist
        (self.ceo_dir / "state" / "agent-reports").mkdir(parents=True, exist_ok=True)
        (self.ceo_dir / "critiques").mkdir(parents=True, exist_ok=True)
        
        print(f"🧠 DIRECTOR initialized for {self.current_date}")
        print(f"📁 Working in: {self.ceo_dir}")

    def _read_json_safe(self, file_path: Path, default: Any = None) -> Any:
        """Safely read JSON file with default fallback."""
        try:
            if file_path.exists():
                with open(file_path) as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️  Warning: Could not read {file_path}: {e}")
        return default or {}

    def _read_yaml_safe(self, file_path: Path, default: Any = None) -> Any:
        """Safely read YAML file with default fallback."""
        try:
            if file_path.exists():
                with open(file_path) as f:
                    return yaml.safe_load(f)
        except Exception as e:
            print(f"⚠️  Warning: Could not read {file_path}: {e}")
        return default or {}

    def gather_intelligence(self) -> Dict[str, Any]:
        """Gather all intelligence inputs for strategic planning."""
        print("📊 Gathering intelligence...")
        
        intelligence = {
            "constitution": self._read_yaml_safe(self.ceo_dir / "constitution.yaml"),
            "knowledge_index": self._read_json_safe(self.ceo_dir / "knowledge" / "_index.json"),
            "knowledge_gaps": self._read_json_safe(self.ceo_dir / "knowledge" / "_gaps.json"),
            "subscriptions": self._read_yaml_safe(self.ceo_dir / "sources" / "subscriptions.yaml"),
            "current_missions": self._read_json_safe(self.ceo_dir / "state" / "missions.json"),
            "agent_reports": self._gather_agent_reports(),
            "critiques": self._read_json_safe(self.ceo_dir / "critiques" / "pending.json", [])
        }
        
        # Print summary
        print(f"  📋 Constitution: {'✓' if intelligence['constitution'] else '✗'}")
        print(f"  🧠 Knowledge frameworks: {intelligence['knowledge_index'].get('total_frameworks', 0)}")
        # Handle knowledge gaps format (could be list or dict)
        gaps = intelligence['knowledge_gaps']
        if isinstance(gaps, list):
            gap_count = len(gaps)
        else:
            gap_count = len(gaps.get('gaps', []))
        print(f"  ❓ Knowledge gaps: {gap_count}")
        print(f"  📡 Subscriptions: {len(intelligence['subscriptions'].get('sources', []))}")
        print(f"  📝 Recent agent reports: {len(intelligence['agent_reports'])}")
        print(f"  🎯 Active missions: {len(intelligence['current_missions'].get('missions', []))}")
        
        return intelligence

    def _gather_agent_reports(self) -> List[Dict]:
        """Gather recent agent reports."""
        reports_dir = self.ceo_dir / "state" / "agent-reports"
        if not reports_dir.exists():
            return []
            
        reports = []
        for report_file in reports_dir.glob("*.json"):
            try:
                with open(report_file) as f:
                    report = json.load(f)
                    report['file'] = report_file.name
                    reports.append(report)
            except Exception as e:
                print(f"⚠️  Warning: Could not read {report_file}: {e}")
                
        # Sort by date, most recent first
        reports.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return reports[:10]  # Last 10 reports

    def call_claude_opus(self, prompt: str) -> str:
        """Call Claude Opus API for deep strategic thinking."""
        print("🤔 Consulting Claude Opus for strategic analysis...")
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from api import call_claude
            return call_claude("You are a strategic AI advisor.", prompt, model="claude-sonnet-4-20250514", max_tokens=4000)
        except Exception as e:
            print(f"❌ Error calling Claude Opus: {e}")
            return f"ERROR: Could not get strategic analysis - {e}"

    def generate_strategic_plan(self, intelligence: Dict[str, Any]) -> Dict[str, Any]:
        """Generate strategic plan using Claude Opus."""
        
        # Build context prompt
        prompt = f"""You are the DIRECTOR of an Agentic CEO system. Today is {self.current_date}.

Your role: Strategic planning, prioritization, and high-level decision making.

CURRENT INTELLIGENCE:

CONSTITUTION & PURPOSE:
{json.dumps(intelligence['constitution'], indent=2)}

KNOWLEDGE BASE STATUS:
- Total frameworks: {intelligence['knowledge_index'].get('total_frameworks', 0)}
- Domains covered: {list(intelligence['knowledge_index'].get('domains', {}).keys())}

KNOWLEDGE GAPS:
{json.dumps(intelligence['knowledge_gaps'], indent=2)}

AVAILABLE SOURCES:
{json.dumps(intelligence['subscriptions'], indent=2)}

CURRENT MISSIONS STATUS:
{json.dumps(intelligence['current_missions'], indent=2)}

RECENT AGENT REPORTS:
{json.dumps(intelligence['agent_reports'][:5], indent=2)}  # Last 5 for context

PENDING CRITIQUES:
{len(intelligence['critiques'])} critiques awaiting review

---

TASK: Generate today's strategic plan as the CEO brain.

Consider:
1. What should be our strategic focus today?
2. What HUNTS should we launch? A hunt is an autonomous deep-research mission on a specific question. The hunter agent will search YouTube, articles, papers — recursively chasing sub-components until it builds deep understanding. Assign 1-3 hunts with specific research questions.
3. What missions should we assign to Scout, Analyst, and Critic agents?
4. What knowledge gaps are most critical to address?
5. What sources should we prioritize for information gathering?
6. How do recent agent activities inform our priorities?
7. Should we run the evolve agent to analyze system performance and suggest improvements?

Output a JSON object with this exact structure:
{{
  "current_cycle": "{self.current_date}",
  "focus": "Brief statement of today's strategic focus",
  "hunts": [
    {{
      "id": "uuid-here",
      "question": "The specific research question to hunt",
      "priority": "high|medium|low",
      "reason": "Why this question matters for our purpose",
      "budget": 1.00,
      "max_sources": 30,
      "max_depth": 3
    }}
  ],
  "missions": [
    {{
      "id": "uuid-here",
      "agent": "scout|analyst|critic|evolve",
      "priority": "high|medium|low", 
      "task": "Specific actionable task",
      "reason": "Why this matters strategically right now",
      "status": "pending"
    }}
  ],
  "reflections": "Your thoughts about the system's current state, strategic direction, and key decisions behind this plan",
  "completed": []
}}

REMEMBER YOUR PURPOSE: Build something connected that can make an impact on the world for prosperity and victory. Be aggressive about hunting knowledge. Be exhaustive. Chase understanding recursively. Don't settle for surface-level.

Be strategic, be specific, be actionable. This is your CEO moment."""

        analysis = self.call_claude_opus(prompt)
        
        # Parse the JSON response
        try:
            # Extract JSON from the response
            import re
            json_match = re.search(r'\{.*\}', analysis, re.DOTALL)
            if json_match:
                plan_data = json.loads(json_match.group(0))
                
                # Generate UUIDs for missions that don't have them
                for mission in plan_data.get('missions', []):
                    if not mission.get('id') or mission['id'] == 'uuid-here':
                        mission['id'] = str(uuid.uuid4())
                        
                return plan_data
            else:
                print("⚠️  Could not extract JSON from Claude response")
                return self._fallback_plan(analysis)
                
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON parse error: {e}")
            return self._fallback_plan(analysis)

    def _fallback_plan(self, raw_analysis: str) -> Dict[str, Any]:
        """Create a fallback plan if Claude response can't be parsed."""
        return {
            "current_cycle": self.current_date,
            "focus": "System initialization and knowledge gathering",
            "missions": [
                {
                    "id": str(uuid.uuid4()),
                    "agent": "scout",
                    "priority": "high",
                    "task": "Establish baseline knowledge collection from available sources",
                    "reason": "System appears to be in early stages - need foundational intelligence",
                    "status": "pending"
                }
            ],
            "reflections": f"Director unable to parse full strategic analysis. Raw output: {raw_analysis[:500]}...",
            "completed": []
        }

    def save_plan_and_report(self, plan: Dict[str, Any]) -> None:
        """Save the strategic plan and generate director report."""
        
        # Save missions.json
        missions_file = self.ceo_dir / "state" / "missions.json"
        with open(missions_file, 'w') as f:
            json.dump(plan, f, indent=2)
        print(f"💾 Saved strategic plan to {missions_file}")
        
        # Create director report
        report = {
            "agent": "director",
            "timestamp": datetime.now().isoformat(),
            "cycle_date": self.current_date,
            "focus": plan.get("focus", ""),
            "missions_assigned": len(plan.get("missions", [])),
            "priority_breakdown": {
                "high": len([m for m in plan.get("missions", []) if m.get("priority") == "high"]),
                "medium": len([m for m in plan.get("missions", []) if m.get("priority") == "medium"]),
                "low": len([m for m in plan.get("missions", []) if m.get("priority") == "low"])
            },
            "reflections": plan.get("reflections", ""),
            "status": "completed"
        }
        
        # Save director report
        report_file = self.ceo_dir / "state" / "agent-reports" / f"director-{self.current_date}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"📋 Saved director report to {report_file}")

    def run_planning_cycle(self) -> None:
        """Execute full strategic planning cycle."""
        print("🎯 DIRECTOR: Starting strategic planning cycle")
        print("=" * 50)
        
        # Gather intelligence
        intelligence = self.gather_intelligence()
        
        # Generate strategic plan
        plan = self.generate_strategic_plan(intelligence)
        
        # Save plan and report
        self.save_plan_and_report(plan)
        
        # Display summary
        print("\n✅ STRATEGIC PLAN GENERATED")
        print("=" * 50)
        print(f"🎯 Focus: {plan.get('focus', '')}")
        print(f"📋 Missions assigned: {len(plan.get('missions', []))}")
        
        for mission in plan.get("missions", []):
            priority_emoji = {"high": "🔥", "medium": "📝", "low": "💡"}.get(mission.get("priority", ""), "❓")
            print(f"  {priority_emoji} {mission.get('agent', '')} - {mission.get('task', '')[:60]}...")
        
        print(f"\n💭 Key reflections: {plan.get('reflections', '')[:100]}...")
        print("\nDirector cycle complete. ✨")

    def show_status(self) -> None:
        """Show current system status without planning."""
        print("📊 DIRECTOR STATUS")
        print("=" * 50)
        
        # Load current missions
        missions = self._read_json_safe(self.ceo_dir / "state" / "missions.json")
        
        if not missions:
            print("❌ No current strategic plan found")
            return
            
        print(f"📅 Current cycle: {missions.get('current_cycle', 'Unknown')}")
        print(f"🎯 Strategic focus: {missions.get('focus', '')}")
        
        print(f"\n📋 MISSIONS ({len(missions.get('missions', []))} total)")
        for mission in missions.get("missions", []):
            status_emoji = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}.get(mission.get("status"), "❓")
            priority_emoji = {"high": "🔥", "medium": "📝", "low": "💡"}.get(mission.get("priority"), "❓")
            
            print(f"  {status_emoji} {priority_emoji} [{mission.get('agent', '')}] {mission.get('task', '')}")
            if mission.get("reason"):
                print(f"    └─ {mission.get('reason', '')}")
        
        completed = missions.get('completed', [])
        if completed:
            print(f"\n✅ COMPLETED ({len(completed)})")
            for item in completed[-5:]:  # Last 5
                print(f"  ✅ {item}")
        
        print(f"\n💭 Last reflections: {missions.get('reflections', '')}")

    def weekly_reflection(self) -> None:
        """Run deeper weekly reflection and system analysis."""
        print("🔍 DIRECTOR: Weekly Reflection Mode")
        print("=" * 50)
        
        # This would be a deeper analysis - for now, run regular planning
        # In the future, this could analyze trends, effectiveness, etc.
        print("📈 Analyzing weekly patterns and effectiveness...")
        
        # Gather more historical data
        intelligence = self.gather_intelligence()
        
        # Enhanced prompt for weekly reflection
        reflection_prompt = f"""You are conducting your WEEKLY REFLECTION as the Director of an Agentic CEO system.

Today is {self.current_date}. Look back at the past week's activities and forward to strategic direction.

CURRENT STATE:
{json.dumps(intelligence, indent=2)}

WEEKLY REFLECTION TASKS:
1. Assess the effectiveness of recent missions and agent performance
2. Identify patterns in knowledge gaps and learning
3. Evaluate source quality and information flow
4. Reflect on strategic direction and course corrections needed
5. Plan longer-term strategic initiatives (beyond daily missions)

Provide deep strategic insights and recommendations for the coming week.
Include both tactical adjustments and strategic pivots if needed.

Consider: What's working? What isn't? Where should we double down? What should we stop doing?"""

        reflection = self.call_claude_opus(reflection_prompt)
        
        # Save as special reflection report
        reflection_report = {
            "agent": "director",
            "type": "weekly_reflection", 
            "timestamp": datetime.now().isoformat(),
            "week_ending": self.current_date,
            "reflection": reflection,
            "status": "completed"
        }
        
        report_file = self.ceo_dir / "state" / "agent-reports" / f"director-weekly-{self.current_date}.json"
        with open(report_file, 'w') as f:
            json.dump(reflection_report, f, indent=2)
            
        print(f"📋 Weekly reflection saved to {report_file}")
        print("\n🔍 WEEKLY REFLECTION SUMMARY")
        print("=" * 50)
        print(reflection[:500] + "..." if len(reflection) > 500 else reflection)


def main():
    parser = argparse.ArgumentParser(description="Director Agent - Strategic Planning")
    parser.add_argument("--reflect", action="store_true", help="Weekly reflection mode")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--ceo-dir", default=str(Path(__file__).parent.parent), 
                       help="CEO system directory")
    
    args = parser.parse_args()
    
    try:
        director = DirectorAgent(args.ceo_dir)
        
        if args.status:
            director.show_status()
        elif args.reflect:
            director.weekly_reflection()
        else:
            director.run_planning_cycle()
            
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
