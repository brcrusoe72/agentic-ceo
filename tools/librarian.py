#!/usr/bin/env python3
"""
LIBRARIAN - Knowledge Base Organizer for Agentic CEO System

Organizes framework JSON files, finds patterns, identifies gaps, and maintains
the master index of the knowledge base.
"""

import json
import os
import sys
import argparse
import uuid
from datetime import datetime
import logging
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Optional, Tuple, Set
import re

import anthropic

# Third-party imports (install if needed)
from api import call_claude, get_api_key

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('librarian')

class LibrarianConfig:
    """Configuration for the Librarian agent."""
    
    def __init__(self):
        self.base_dir = Path.cwd()
        self.knowledge_dir = self.base_dir / "knowledge"
        self.state_dir = self.base_dir / "state" / "agent-reports"
        
        # Ensure directories exist
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.index_file = self.knowledge_dir / "_index.json"
        self.connections_file = self.knowledge_dir / "_connections.json"
        self.gaps_file = self.knowledge_dir / "_gaps.json"
        
        # API configuration
        self.model = "claude-sonnet-4-20250514"
        self.api_key = self._get_anthropic_api_key()
    
    def _get_anthropic_api_key(self) -> Optional[str]:
        """Get Anthropic API key from auth profiles or environment."""
        # Try environment first
        if 'ANTHROPIC_API_KEY' in os.environ:
            return os.environ['ANTHROPIC_API_KEY']
        
        # Try auth profiles
        auth_file = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"
        try:
            with open(auth_file) as f:
                auth_data = json.load(f)
                
            # Find anthropic profile
            for profile_id, profile in auth_data.get('profiles', {}).items():
                if profile.get('provider') == 'anthropic':
                    return profile.get('token')
                    
        except Exception as e:
            logger.warning(f"Could not read auth profiles: {e}")
        
        return None

class FrameworkLoader:
    """Loads and validates framework JSON files."""
    
    def __init__(self, config: LibrarianConfig):
        self.config = config
    
    def load_all_frameworks(self) -> List[Dict]:
        """Load all framework JSON files from knowledge subdirectories."""
        frameworks = []
        
        for domain_dir in self.config.knowledge_dir.iterdir():
            if not domain_dir.is_dir() or domain_dir.name.startswith('_'):
                continue
            
            logger.info(f"Scanning domain: {domain_dir.name}")
            domain_frameworks = self._load_domain_frameworks(domain_dir)
            frameworks.extend(domain_frameworks)
        
        logger.info(f"Loaded {len(frameworks)} frameworks total")
        return frameworks
    
    def _load_domain_frameworks(self, domain_dir: Path) -> List[Dict]:
        """Load frameworks from a specific domain directory."""
        frameworks = []
        
        for file_path in domain_dir.glob("*.json"):
            try:
                with open(file_path) as f:
                    framework = json.load(f)
                
                # Validate and enrich framework
                framework = self._validate_framework(framework, file_path)
                if framework:
                    frameworks.append(framework)
                    
            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")
        
        return frameworks
    
    def _validate_framework(self, framework: Dict, file_path: Path) -> Optional[Dict]:
        """Validate and enrich a framework with metadata."""
        required_fields = ['id', 'name', 'type']
        
        # Check required fields
        for field in required_fields:
            if field not in framework:
                logger.warning(f"Framework missing required field '{field}': {file_path}")
                return None
        
        # Add metadata
        framework['domain'] = file_path.parent.name
        framework['path'] = str(file_path.relative_to(self.config.knowledge_dir))
        
        # Ensure confidence field
        if 'confidence' not in framework:
            framework['confidence'] = 0.8  # Default confidence
        
        # Normalize tags
        if 'tags' in framework:
            framework['tags'] = [tag.lower().strip() for tag in framework['tags']]
        
        return framework

class IndexBuilder:
    """Builds the master index of all frameworks."""
    
    def __init__(self, config: LibrarianConfig):
        self.config = config
    
    def build_index(self, frameworks: List[Dict]) -> Dict:
        """Build the master index from frameworks."""
        logger.info("Building master index...")
        
        # Count by domain and type
        domains = Counter()
        types = Counter()
        all_tags = Counter()
        
        entries = []
        
        for framework in frameworks:
            # Count statistics
            domain = framework.get('domain', 'unknown')
            ftype = framework.get('type', 'unknown')
            domains[domain] += 1
            types[ftype] += 1
            
            # Count tags
            for tag in framework.get('tags', []):
                all_tags[tag] += 1
            
            # Create index entry
            entry = {
                'id': framework['id'],
                'name': framework['name'],
                'type': ftype,
                'domain': domain,
                'confidence': framework.get('confidence', 0.8),
                'path': framework['path']
            }
            entries.append(entry)
        
        # Build index structure
        index = {
            'version': 1,
            'built_at': datetime.now().isoformat(),
            'total_frameworks': len(frameworks),
            'domains': dict(domains),
            'types': dict(types),
            'top_tags': all_tags.most_common(20),
            'entries': entries
        }
        
        return index
    
    def save_index(self, index: Dict):
        """Save index to file."""
        with open(self.config.index_file, 'w') as f:
            json.dump(index, f, indent=2)
        logger.info(f"Index saved to {self.config.index_file}")

class ConnectionFinder:
    """Finds connections between frameworks using LLM."""
    
    def __init__(self, config: LibrarianConfig):
        self.config = config
        self.client = None
        if config.api_key:
            self.client = anthropic.Anthropic(api_key=config.api_key)
    
    def find_connections(self, frameworks: List[Dict], domain_filter: Optional[str] = None) -> List[Dict]:
        """Find connections between frameworks."""
        if not self.client:
            logger.error("No Anthropic API key available - cannot find connections")
            return []
        
        logger.info("Finding connections between frameworks...")
        
        # Filter frameworks if domain specified
        if domain_filter:
            frameworks = [f for f in frameworks if f.get('domain') == domain_filter]
            logger.info(f"Filtering to {len(frameworks)} frameworks in domain '{domain_filter}'")
        
        connections = []
        
        # Process in batches to avoid token limits
        batch_size = 10
        for i in range(0, len(frameworks), batch_size):
            batch = frameworks[i:i + batch_size]
            batch_connections = self._find_batch_connections(batch, frameworks)
            connections.extend(batch_connections)
        
        logger.info(f"Found {len(connections)} connections")
        return connections
    
    def _find_batch_connections(self, batch: List[Dict], all_frameworks: List[Dict]) -> List[Dict]:
        """Find connections for a batch of frameworks."""
        connections = []
        
        for framework_a in batch:
            for framework_b in all_frameworks:
                if framework_a['id'] == framework_b['id']:
                    continue
                
                # Skip if we already processed this pair
                pair_id = tuple(sorted([framework_a['id'], framework_b['id']]))
                
                connection = self._analyze_connection(framework_a, framework_b)
                if connection:
                    connections.append(connection)
        
        return connections
    
    def _analyze_connection(self, framework_a: Dict, framework_b: Dict) -> Optional[Dict]:
        """Analyze connection between two frameworks using LLM."""
        try:
            prompt = self._build_connection_prompt(framework_a, framework_b)
            
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            
            result = self._parse_connection_response(response.content[0].text, framework_a, framework_b)
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing connection: {e}")
            return None
    
    def _build_connection_prompt(self, framework_a: Dict, framework_b: Dict) -> str:
        """Build prompt for connection analysis."""
        return f"""Analyze the relationship between these two frameworks:

FRAMEWORK A:
Name: {framework_a['name']}
Type: {framework_a.get('type', 'unknown')}
Domain: {framework_a.get('domain', 'unknown')}
Description: {framework_a.get('description', 'No description')}
Tags: {', '.join(framework_a.get('tags', []))}

FRAMEWORK B:
Name: {framework_b['name']}
Type: {framework_b.get('type', 'unknown')}
Domain: {framework_b.get('domain', 'unknown')}
Description: {framework_b.get('description', 'No description')}
Tags: {', '.join(framework_b.get('tags', []))}

Determine if there is a meaningful relationship between these frameworks.

Respond in this exact format:
CONNECTION: yes|no
TYPE: supports|contradicts|extends|specializes|prerequisite
STRENGTH: 0.0-1.0
DESCRIPTION: Brief description of the relationship

Only respond "CONNECTION: yes" if there is a clear, meaningful relationship."""
    
    def _parse_connection_response(self, response: str, framework_a: Dict, framework_b: Dict) -> Optional[Dict]:
        """Parse LLM response into connection object."""
        try:
            lines = response.strip().split('\n')
            parsed = {}
            
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    parsed[key.strip().lower()] = value.strip()
            
            if parsed.get('connection', '').lower() != 'yes':
                return None
            
            connection_type = parsed.get('type', 'supports')
            strength_str = parsed.get('strength', '0.5')
            description = parsed.get('description', 'Related frameworks')
            
            # Parse strength
            try:
                strength = float(strength_str)
                strength = max(0.0, min(1.0, strength))  # Clamp to 0-1
            except:
                strength = 0.5
            
            return {
                'id': str(uuid.uuid4()),
                'type': connection_type,
                'framework_a': framework_a['id'],
                'framework_b': framework_b['id'],
                'description': description,
                'strength': strength,
                'discovered_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error parsing connection response: {e}")
            return None
    
    def save_connections(self, connections: List[Dict]):
        """Save connections to file."""
        with open(self.config.connections_file, 'w') as f:
            json.dump(connections, f, indent=2)
        logger.info(f"Connections saved to {self.config.connections_file}")

class GapAnalyzer:
    """Identifies knowledge gaps using LLM."""
    
    def __init__(self, config: LibrarianConfig):
        self.config = config
        self.client = None
        if config.api_key:
            self.client = anthropic.Anthropic(api_key=config.api_key)
    
    def identify_gaps(self, frameworks: List[Dict], index: Dict, connections: List[Dict]) -> List[Dict]:
        """Identify knowledge gaps in the framework collection."""
        if not self.client:
            logger.error("No Anthropic API key available - cannot identify gaps")
            return []
        
        logger.info("Identifying knowledge gaps...")
        
        gaps = []
        
        # Analyze sparse domains
        gaps.extend(self._find_sparse_domain_gaps(index))
        
        # Analyze missing opposing views
        gaps.extend(self._find_opposing_view_gaps(frameworks, connections))
        
        # Analyze shallow coverage
        gaps.extend(self._find_shallow_coverage_gaps(frameworks))
        
        # Analyze stale content
        gaps.extend(self._find_stale_gaps(frameworks))
        
        logger.info(f"Identified {len(gaps)} knowledge gaps")
        return gaps
    
    def _find_sparse_domain_gaps(self, index: Dict) -> List[Dict]:
        """Find domains with sparse coverage."""
        gaps = []
        domains = index.get('domains', {})
        
        # Consider domains with < 3 frameworks as sparse
        for domain, count in domains.items():
            if count < 3:
                gaps.append({
                    'id': str(uuid.uuid4()),
                    'type': 'sparse_domain',
                    'domain': domain,
                    'description': f"Domain '{domain}' has only {count} framework(s) - needs more comprehensive coverage",
                    'priority': 'high' if count == 1 else 'medium',
                    'suggested_search': f"comprehensive frameworks and methodologies for {domain}",
                    'discovered_at': datetime.now().isoformat()
                })
        
        return gaps
    
    def _find_opposing_view_gaps(self, frameworks: List[Dict], connections: List[Dict]) -> List[Dict]:
        """Find areas lacking opposing viewpoints."""
        gaps = []
        
        # Group frameworks by domain
        domains = defaultdict(list)
        for framework in frameworks:
            domains[framework.get('domain', 'unknown')].append(framework)
        
        # Check each domain for contradictory connections
        for domain, domain_frameworks in domains.items():
            has_contradictions = any(
                conn['type'] == 'contradicts' 
                for conn in connections 
                if any(f['id'] in [conn['framework_a'], conn['framework_b']] for f in domain_frameworks)
            )
            
            if not has_contradictions and len(domain_frameworks) > 1:
                gaps.append({
                    'id': str(uuid.uuid4()),
                    'type': 'missing_opposing_view',
                    'domain': domain,
                    'description': f"Domain '{domain}' lacks contradictory or alternative viewpoints",
                    'priority': 'medium',
                    'suggested_search': f"alternative approaches and criticisms of {domain} methodologies",
                    'discovered_at': datetime.now().isoformat()
                })
        
        return gaps
    
    def _find_shallow_coverage_gaps(self, frameworks: List[Dict]) -> List[Dict]:
        """Find areas with shallow coverage."""
        gaps = []
        
        # Look for frameworks with short descriptions or few details
        for framework in frameworks:
            description = framework.get('description', '')
            if len(description) < 100:  # Arbitrary threshold
                gaps.append({
                    'id': str(uuid.uuid4()),
                    'type': 'shallow_coverage',
                    'domain': framework.get('domain', 'unknown'),
                    'description': f"Framework '{framework['name']}' has minimal description and needs deeper analysis",
                    'priority': 'low',
                    'suggested_search': f"detailed analysis and implementation of {framework['name']}",
                    'discovered_at': datetime.now().isoformat()
                })
        
        return gaps
    
    def _find_stale_gaps(self, frameworks: List[Dict]) -> List[Dict]:
        """Find potentially stale content."""
        gaps = []
        
        # For now, just note this as a future enhancement
        # In a real system, we'd check last_updated timestamps
        
        return gaps
    
    def save_gaps(self, gaps: List[Dict]):
        """Save gaps to file."""
        with open(self.config.gaps_file, 'w') as f:
            json.dump(gaps, f, indent=2)
        logger.info(f"Gaps saved to {self.config.gaps_file}")

class ReportGenerator:
    """Generates synthesis reports."""
    
    def __init__(self, config: LibrarianConfig):
        self.config = config
        self.client = None
        if config.api_key:
            self.client = anthropic.Anthropic(api_key=config.api_key)
    
    def generate_report(self, frameworks: List[Dict], connections: List[Dict], gaps: List[Dict]) -> Dict:
        """Generate a synthesis report."""
        logger.info("Generating synthesis report...")
        
        # Basic statistics
        stats = self._calculate_statistics(frameworks, connections, gaps)
        
        # LLM-powered synthesis (if available)
        synthesis = None
        if self.client:
            synthesis = self._generate_synthesis(frameworks, connections, gaps)
        
        report = {
            'id': str(uuid.uuid4()),
            'generated_at': datetime.now().isoformat(),
            'agent': 'librarian',
            'version': '1.0',
            'statistics': stats,
            'synthesis': synthesis,
            'frameworks_analyzed': len(frameworks),
            'connections_found': len(connections),
            'gaps_identified': len(gaps)
        }
        
        return report
    
    def _calculate_statistics(self, frameworks: List[Dict], connections: List[Dict], gaps: List[Dict]) -> Dict:
        """Calculate basic statistics."""
        # Domain distribution
        domains = Counter(f.get('domain', 'unknown') for f in frameworks)
        
        # Connection types
        connection_types = Counter(c['type'] for c in connections)
        
        # Gap types and priorities
        gap_types = Counter(g['type'] for g in gaps)
        gap_priorities = Counter(g['priority'] for g in gaps)
        
        return {
            'total_frameworks': len(frameworks),
            'total_connections': len(connections),
            'total_gaps': len(gaps),
            'domain_distribution': dict(domains),
            'connection_types': dict(connection_types),
            'gap_types': dict(gap_types),
            'gap_priorities': dict(gap_priorities),
            'avg_confidence': sum(f.get('confidence', 0.8) for f in frameworks) / max(len(frameworks), 1)
        }
    
    def _generate_synthesis(self, frameworks: List[Dict], connections: List[Dict], gaps: List[Dict]) -> Optional[str]:
        """Generate LLM-powered synthesis."""
        try:
            prompt = self._build_synthesis_prompt(frameworks, connections, gaps)
            
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return response.content[0].text
            
        except Exception as e:
            logger.error(f"Error generating synthesis: {e}")
            return None
    
    def _build_synthesis_prompt(self, frameworks: List[Dict], connections: List[Dict], gaps: List[Dict]) -> str:
        """Build prompt for synthesis generation."""
        # Summarize key information
        domains = Counter(f.get('domain', 'unknown') for f in frameworks)
        connection_types = Counter(c['type'] for c in connections)
        
        return f"""Analyze this knowledge base and provide insights:

FRAMEWORKS: {len(frameworks)} total
Domains: {dict(domains)}

CONNECTIONS: {len(connections)} total
Types: {dict(connection_types)}

KNOWLEDGE GAPS: {len(gaps)} identified

Please provide:
1. Key patterns you observe across frameworks
2. Areas of consensus vs disagreement
3. Most critical knowledge gaps to address
4. Recommendations for knowledge base improvement

Keep your analysis under 1000 words and focus on actionable insights."""
    
    def save_report(self, report: Dict):
        """Save report to timestamped file."""
        timestamp = datetime.now().strftime("%Y-%m-%d")
        report_file = self.config.state_dir / f"librarian-{timestamp}.json"
        
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Report saved to {report_file}")

class Librarian:
    """Main Librarian agent orchestrator."""
    
    def __init__(self):
        self.config = LibrarianConfig()
        self.loader = FrameworkLoader(self.config)
        self.index_builder = IndexBuilder(self.config)
        self.connection_finder = ConnectionFinder(self.config)
        self.gap_analyzer = GapAnalyzer(self.config)
        self.report_generator = ReportGenerator(self.config)
        
        # Check API key
        if not self.config.api_key:
            logger.warning("No Anthropic API key found - LLM features will be disabled")
    
    def run_full_cycle(self, domain_filter: Optional[str] = None):
        """Run the complete organization cycle."""
        logger.info("Starting full Librarian cycle...")
        
        # Load frameworks
        frameworks = self.loader.load_all_frameworks()
        
        if not frameworks:
            logger.warning("No frameworks found - initializing empty knowledge base")
            self._initialize_empty_kb()
            return
        
        # Build index
        index = self.index_builder.build_index(frameworks)
        self.index_builder.save_index(index)
        
        # Find connections
        connections = self.connection_finder.find_connections(frameworks, domain_filter)
        self.connection_finder.save_connections(connections)
        
        # Identify gaps
        gaps = self.gap_analyzer.identify_gaps(frameworks, index, connections)
        self.gap_analyzer.save_gaps(gaps)
        
        # Generate report
        report = self.report_generator.generate_report(frameworks, connections, gaps)
        self.report_generator.save_report(report)
        
        logger.info("Full cycle completed successfully")
    
    def reindex_only(self):
        """Rebuild index without LLM operations."""
        logger.info("Rebuilding index only...")
        
        frameworks = self.loader.load_all_frameworks()
        
        if not frameworks:
            logger.warning("No frameworks found - creating empty index")
            index = {
                'version': 1,
                'built_at': datetime.now().isoformat(),
                'total_frameworks': 0,
                'domains': {},
                'types': {},
                'top_tags': [],
                'entries': []
            }
        else:
            index = self.index_builder.build_index(frameworks)
        
        self.index_builder.save_index(index)
        logger.info("Reindex completed")
    
    def connections_only(self, domain_filter: Optional[str] = None):
        """Find connections only."""
        logger.info("Finding connections only...")
        
        frameworks = self.loader.load_all_frameworks()
        if not frameworks:
            logger.error("No frameworks found")
            return
        
        connections = self.connection_finder.find_connections(frameworks, domain_filter)
        self.connection_finder.save_connections(connections)
        
        logger.info("Connection analysis completed")
    
    def gaps_only(self):
        """Identify gaps only."""
        logger.info("Identifying gaps only...")
        
        frameworks = self.loader.load_all_frameworks()
        if not frameworks:
            logger.error("No frameworks found")
            return
        
        # Load existing index and connections
        try:
            with open(self.config.index_file) as f:
                index = json.load(f)
        except:
            index = self.index_builder.build_index(frameworks)
        
        try:
            with open(self.config.connections_file) as f:
                connections = json.load(f)
        except:
            connections = []
        
        gaps = self.gap_analyzer.identify_gaps(frameworks, index, connections)
        self.gap_analyzer.save_gaps(gaps)
        
        logger.info("Gap analysis completed")
    
    def report_only(self):
        """Generate report only."""
        logger.info("Generating report only...")
        
        frameworks = self.loader.load_all_frameworks()
        
        # Load existing connections and gaps
        try:
            with open(self.config.connections_file) as f:
                connections = json.load(f)
        except:
            connections = []
        
        try:
            with open(self.config.gaps_file) as f:
                gaps = json.load(f)
        except:
            gaps = []
        
        report = self.report_generator.generate_report(frameworks, connections, gaps)
        self.report_generator.save_report(report)
        
        logger.info("Report generation completed")
    
    def _initialize_empty_kb(self):
        """Initialize empty knowledge base files."""
        logger.info("Initializing empty knowledge base...")
        
        # Empty index
        empty_index = {
            'version': 1,
            'built_at': datetime.now().isoformat(),
            'total_frameworks': 0,
            'domains': {},
            'types': {},
            'top_tags': [],
            'entries': []
        }
        self.index_builder.save_index(empty_index)
        
        # Empty connections
        self.connection_finder.save_connections([])
        
        # Empty gaps
        self.gap_analyzer.save_gaps([])
        
        logger.info("Empty knowledge base initialized")

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="LIBRARIAN - Knowledge Base Organizer")
    parser.add_argument('--reindex', action='store_true', 
                       help='Just rebuild the index (no LLM, fast)')
    parser.add_argument('--connections', action='store_true',
                       help='Find connections between frameworks')
    parser.add_argument('--gaps', action='store_true',
                       help='Identify knowledge gaps')
    parser.add_argument('--report', action='store_true',
                       help='Generate synthesis report')
    parser.add_argument('--domain', type=str,
                       help='Focus on specific domain')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    librarian = Librarian()
    
    try:
        if args.reindex:
            librarian.reindex_only()
        elif args.connections:
            librarian.connections_only(args.domain)
        elif args.gaps:
            librarian.gaps_only()
        elif args.report:
            librarian.report_only()
        else:
            # Full cycle
            librarian.run_full_cycle(args.domain)
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
