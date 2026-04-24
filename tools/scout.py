#!/usr/bin/env python3
"""
SCOUT Agent - Content Discovery for Agentic CEO System

Discovers content worth analyzing from various sources without using LLMs.
Designed to be cheap ($0 cost) and efficient.

Usage:
    python3 scout.py                           # Run full discovery cycle
    python3 scout.py --topic "AI agents"      # Focused search on a topic
    python3 scout.py --youtube-channel "URL"  # Check specific channel
    python3 scout.py --gaps                    # Search for knowledge gaps
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse, parse_qs
import re

import requests
import yaml
from bs4 import BeautifulSoup


class Scout:
    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path(__file__).parent.parent
        self.agent_search_url = "http://localhost:3939"
        self.duckduckgo_fallback = "https://lite.duckduckgo.com/lite/"
        
        # Track stats for reporting
        self.stats = {
            "sources_checked": 0,
            "new_found": 0,
            "queued": 0,
            "skipped": 0,
            "actions": [],
            "cost": 0.0  # Always $0 for Scout
        }
    
    def load_config_files(self) -> Dict:
        """Load all configuration files needed for discovery."""
        config = {}
        
        # Load subscriptions
        sub_file = self.base_dir / "sources" / "subscriptions.yaml"
        try:
            with open(sub_file) as f:
                config["subscriptions"] = yaml.safe_load(f)
        except FileNotFoundError:
            print(f"Warning: {sub_file} not found, using empty config")
            config["subscriptions"] = {"youtube_channels": [], "rss_feeds": [], "news_queries": []}
        
        # Load knowledge gaps
        gaps_file = self.base_dir / "knowledge" / "_gaps.json"
        try:
            with open(gaps_file) as f:
                config["gaps"] = json.load(f)
        except FileNotFoundError:
            print(f"Warning: {gaps_file} not found, using empty gaps")
            config["gaps"] = {"gaps": []}
        
        # Load missions
        missions_file = self.base_dir / "state" / "missions.json"
        try:
            with open(missions_file) as f:
                config["missions"] = json.load(f)
        except FileNotFoundError:
            print(f"Warning: {missions_file} not found, using empty missions")
            config["missions"] = {"missions": []}
        
        # Load ingest log
        ingest_file = self.base_dir / "state" / "ingest-log.json"
        try:
            with open(ingest_file) as f:
                config["ingested"] = json.load(f)
        except FileNotFoundError:
            print(f"Warning: {ingest_file} not found, using empty ingest log")
            config["ingested"] = {"entries": []}
        
        return config
    
    def is_content_ingested(self, url: str, config: Dict) -> bool:
        """Check if content has already been ingested."""
        ingested_urls = {entry.get("url", "") for entry in config["ingested"].get("entries", [])}
        return url in ingested_urls
    
    def search_agentsearch(self, query: str, limit: int = 10) -> List[Dict]:
        """Search using AgentSearch API (localhost:3939)."""
        try:
            response = requests.get(
                f"{self.agent_search_url}/search",
                params={"q": query, "limit": limit},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("results", [])
            else:
                print(f"AgentSearch returned status {response.status_code}")
                return []
        except requests.RequestException as e:
            print(f"AgentSearch API failed: {e}")
            return []
    
    def search_duckduckgo_fallback(self, query: str) -> List[Dict]:
        """Fallback search using DuckDuckGo Lite."""
        try:
            response = requests.get(
                self.duckduckgo_fallback,
                params={"q": query},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Scout/1.0)"}
            )
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                results = []
                
                # Parse DDG Lite results
                for link in soup.find_all('a', href=True):
                    href = link.get('href')
                    if href and href.startswith('http') and link.text.strip():
                        results.append({
                            "title": link.text.strip()[:200],
                            "url": href,
                            "snippet": ""
                        })
                        if len(results) >= 10:
                            break
                
                return results
            else:
                print(f"DuckDuckGo fallback failed with status {response.status_code}")
                return []
        except requests.RequestException as e:
            print(f"DuckDuckGo fallback failed: {e}")
            return []
    
    def search_content(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for content using primary and fallback methods."""
        print(f"Searching for: '{query}'")
        
        # Try AgentSearch first
        results = self.search_agentsearch(query, limit)
        if results:
            self.stats["actions"].append(f"AgentSearch for '{query}' — {len(results)} results")
            return results
        
        # Fallback to DuckDuckGo
        print("AgentSearch unavailable, trying DuckDuckGo fallback...")
        results = self.search_duckduckgo_fallback(query)
        if results:
            self.stats["actions"].append(f"DuckDuckGo fallback for '{query}' — {len(results)} results")
        else:
            self.stats["actions"].append(f"Search failed for '{query}'")
        
        return results
    
    def check_youtube_channel(self, channel_url: str) -> List[Dict]:
        """Check YouTube channel for recent videos using yt-dlp."""
        try:
            # Use yt-dlp to get video list
            cmd = [
                "yt-dlp", 
                "--flat-playlist", 
                "--print", "%(id)s %(title)s %(upload_date)s",
                f"{channel_url}/videos"
            ]
            
            import subprocess
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            if result.returncode != 0:
                print(f"yt-dlp failed for {channel_url}: {result.stderr}")
                return []
            
            videos = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split(' ', 2)
                    if len(parts) >= 3:
                        video_id, title = parts[0], ' '.join(parts[1:-1])
                        upload_date = parts[-1]
                        
                        # Only include recent videos (last 30 days)
                        try:
                            upload_dt = datetime.strptime(upload_date, "%Y%m%d")
                            if upload_dt > datetime.now() - timedelta(days=30):
                                videos.append({
                                    "title": title,
                                    "url": f"https://www.youtube.com/watch?v={video_id}",
                                    "upload_date": upload_date,
                                    "snippet": f"YouTube video from {upload_date}"
                                })
                        except ValueError:
                            # Skip if date parsing fails
                            continue
            
            return videos
            
        except subprocess.TimeoutExpired:
            print(f"yt-dlp timed out for {channel_url}")
            return []
        except Exception as e:
            print(f"Error checking YouTube channel {channel_url}: {e}")
            return []
    
    def estimate_tokens(self, title: str, snippet: str) -> int:
        """Rough token estimation for content (no LLM calls)."""
        # Very rough estimation: 1 token ≈ 4 characters
        text = f"{title} {snippet}"
        return len(text) // 4
    
    def score_relevance(self, content: Dict, config: Dict) -> tuple:
        """Score content relevance and determine priority (no LLM calls)."""
        title = content.get("title", "").lower()
        snippet = content.get("snippet", "").lower()
        url = content.get("url", "").lower()
        
        combined_text = f"{title} {snippet} {url}"
        
        # High priority keywords
        high_keywords = [
            "ai agent", "llm", "autonomous", "manufacturing", "oee", 
            "digital twin", "industry 4.0", "context engineering",
            "agentic", "multi-agent", "workflow automation"
        ]
        
        # Medium priority keywords  
        medium_keywords = [
            "artificial intelligence", "machine learning", "automation",
            "analytics", "dashboard", "monitoring", "optimization",
            "python", "api", "framework", "architecture"
        ]
        
        # Low priority keywords
        low_keywords = [
            "technology", "software", "data", "system", "tool",
            "business", "strategy", "enterprise", "solution"
        ]
        
        # Score based on keyword matches
        high_matches = sum(1 for kw in high_keywords if kw in combined_text)
        medium_matches = sum(1 for kw in medium_keywords if kw in combined_text)
        low_matches = sum(1 for kw in low_keywords if kw in combined_text)
        
        # Priority determination
        if high_matches >= 2:
            priority = "high"
            reason = f"High relevance: {high_matches} key terms"
        elif high_matches >= 1 or medium_matches >= 3:
            priority = "medium" 
            reason = f"Medium relevance: {high_matches} high + {medium_matches} medium terms"
        elif medium_matches >= 1 or low_matches >= 2:
            priority = "low"
            reason = f"Low relevance: {medium_matches} medium + {low_matches} low terms"
        else:
            priority = None
            reason = "No relevant keywords found"
        
        return priority, reason
    
    def determine_source_type(self, url: str) -> str:
        """Determine content type from URL."""
        url_lower = url.lower()
        
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        elif url_lower.endswith(('.pdf', '.PDF')):
            return "pdf"
        elif "podcast" in url_lower or "audio" in url_lower:
            return "podcast"
        else:
            return "article"
    
    def determine_domain_hint(self, title: str, snippet: str) -> str:
        """Determine domain hint from content."""
        text = f"{title} {snippet}".lower()
        
        if any(term in text for term in ["manufacturing", "oee", "factory", "production"]):
            return "manufacturing"
        elif any(term in text for term in ["ai", "agent", "llm", "autonomous"]):
            return "ai-systems"
        elif any(term in text for term in ["strategy", "business", "ceo", "leadership"]):
            return "strategy"
        elif any(term in text for term in ["analytics", "data", "dashboard"]):
            return "analytics"
        else:
            return "general"
    
    def process_search_results(self, results: List[Dict], config: Dict) -> List[Dict]:
        """Process search results and create queue entries."""
        queue_entries = []
        
        for result in results:
            self.stats["sources_checked"] += 1
            
            url = result.get("url", "")
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            
            # Skip if already ingested
            if self.is_content_ingested(url, config):
                self.stats["skipped"] += 1
                continue
            
            # Score relevance
            priority, reason = self.score_relevance(result, config)
            
            # Skip if not relevant enough
            if priority is None:
                self.stats["skipped"] += 1
                continue
            
            # Create queue entry
            queue_entry = {
                "url": url,
                "title": title,
                "source_type": self.determine_source_type(url),
                "discovered_at": datetime.now().isoformat(),
                "priority": priority,
                "reason": reason,
                "estimated_tokens": self.estimate_tokens(title, snippet),
                "domain_hint": self.determine_domain_hint(title, snippet)
            }
            
            queue_entries.append(queue_entry)
            self.stats["new_found"] += 1
            self.stats["queued"] += 1
        
        return queue_entries
    
    def run_discovery_cycle(self, config: Dict, focus_topic: str = None, gaps_only: bool = False) -> List[Dict]:
        """Run full content discovery cycle."""
        all_queue_entries = []
        
        # Search for knowledge gaps if requested or if gaps exist
        if gaps_only or config["gaps"].get("gaps"):
            for gap in config["gaps"].get("gaps", []):
                if isinstance(gap, dict) and "topic" in gap:
                    query = gap["topic"]
                    results = self.search_content(query)
                    entries = self.process_search_results(results, config)
                    all_queue_entries.extend(entries)
        
        # If focus topic provided, search for it
        if focus_topic:
            results = self.search_content(focus_topic)
            entries = self.process_search_results(results, config)
            all_queue_entries.extend(entries)
            return all_queue_entries
        
        # Skip other searches if gaps_only mode
        if gaps_only:
            return all_queue_entries
        
        # Search news queries from subscriptions
        for query_config in config["subscriptions"].get("news_queries", []):
            query = query_config.get("query", "")
            if query:
                results = self.search_content(query)
                entries = self.process_search_results(results, config)
                all_queue_entries.extend(entries)
        
        # Check YouTube channels
        for channel in config["subscriptions"].get("youtube_channels", []):
            channel_url = channel.get("url", "")
            if channel_url:
                print(f"Checking YouTube channel: {channel.get('name', channel_url)}")
                videos = self.check_youtube_channel(channel_url)
                if videos:
                    self.stats["actions"].append(f"Checked {channel.get('name', 'channel')} — {len(videos)} new videos")
                    entries = self.process_search_results(videos, config)
                    all_queue_entries.extend(entries)
                else:
                    self.stats["actions"].append(f"Checked {channel.get('name', 'channel')} — no new videos")
        
        # Search for current mission topics
        for mission in config["missions"].get("missions", []):
            if isinstance(mission, dict) and "topic" in mission:
                query = mission["topic"]
                results = self.search_content(query)
                entries = self.process_search_results(results, config)
                all_queue_entries.extend(entries)
        
        return all_queue_entries
    
    def update_source_queue(self, new_entries: List[Dict]) -> None:
        """Add new entries to source queue."""
        queue_file = self.base_dir / "state" / "source-queue.json"
        
        try:
            with open(queue_file) as f:
                queue_data = json.load(f)
        except FileNotFoundError:
            queue_data = {"queued": [], "processing": [], "completed": []}
        
        # Add new entries to queue
        queue_data["queued"].extend(new_entries)
        
        # Write back to file
        with open(queue_file, 'w') as f:
            json.dump(queue_data, f, indent=2)
    
    def write_report(self) -> None:
        """Write scout report to agent-reports directory."""
        report_dir = self.base_dir / "state" / "agent-reports"
        report_dir.mkdir(exist_ok=True)
        
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_file = report_dir / f"scout-{date_str}.json"
        
        report = {
            "agent": "scout",
            "timestamp": datetime.now().isoformat(),
            "sources_checked": self.stats["sources_checked"],
            "new_found": self.stats["new_found"],
            "queued": self.stats["queued"],
            "skipped": self.stats["skipped"],
            "actions": self.stats["actions"],
            "cost": "$0.00"  # Always $0 for Scout
        }
        
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Report written to {report_file}")
    
    def run(self, args) -> None:
        """Main run method."""
        print("🕵️ SCOUT Agent - Content Discovery")
        print(f"Working directory: {self.base_dir}")
        print()
        
        # Load configuration
        config = self.load_config_files()
        
        # Run discovery based on arguments
        if args.youtube_channel:
            print(f"Checking specific YouTube channel: {args.youtube_channel}")
            videos = self.check_youtube_channel(args.youtube_channel)
            if videos:
                entries = self.process_search_results(videos, config)
                self.update_source_queue(entries)
            else:
                print("No videos found or channel check failed")
                
        elif args.topic:
            print(f"Focused search for topic: {args.topic}")
            entries = self.run_discovery_cycle(config, focus_topic=args.topic)
            self.update_source_queue(entries)
            
        elif args.gaps:
            print("Searching specifically for knowledge gaps")
            entries = self.run_discovery_cycle(config, gaps_only=True)
            self.update_source_queue(entries)
            
        else:
            print("Running full discovery cycle...")
            entries = self.run_discovery_cycle(config)
            self.update_source_queue(entries)
        
        # Write report
        self.write_report()
        
        # Print summary
        print()
        print("📊 Discovery Summary:")
        print(f"  Sources checked: {self.stats['sources_checked']}")
        print(f"  New content found: {self.stats['new_found']}")
        print(f"  Items queued: {self.stats['queued']}")
        print(f"  Items skipped: {self.stats['skipped']}")
        print(f"  Cost: ${self.stats['cost']:.2f}")
        
        if self.stats["actions"]:
            print()
            print("🎬 Actions taken:")
            for action in self.stats["actions"]:
                print(f"  • {action}")


def main():
    parser = argparse.ArgumentParser(description="SCOUT Agent - Content Discovery")
    parser.add_argument("--topic", help="Search for specific topic")
    parser.add_argument("--youtube-channel", help="Check specific YouTube channel URL")
    parser.add_argument("--gaps", action="store_true", help="Search specifically for knowledge gaps")
    
    args = parser.parse_args()
    
    scout = Scout()
    scout.run(args)


if __name__ == "__main__":
    main()