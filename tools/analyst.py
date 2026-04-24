#!/usr/bin/env python3
"""
ANALYST - Knowledge Extraction Agent for Agentic CEO System

Extracts structured knowledge objects from content sources:
- YouTube videos (via yt-dlp + Whisper fallback)
- Web articles (via requests + BeautifulSoup)
- Local files (PDF, text)

Outputs typed JSON objects to knowledge/{domain}/ directories.
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse

import requests
import yt_dlp
from api import call_claude as _call_claude
from bs4 import BeautifulSoup
from faster_whisper import WhisperModel

# Working directory setup
CEO_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = CEO_DIR / "knowledge"
STATE_DIR = CEO_DIR / "state"


class ContentExtractor:
    """Extract content from various sources."""

    def __init__(self):
        self.whisper_model = None

    def extract_youtube_content(self, url: str) -> Dict[str, str]:
        """Extract transcript from YouTube video."""
        print(f"Processing YouTube URL: {url}")
        
        # Try to get auto-captions first
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en'],
            'skip_download': True,
            'quiet': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Unknown Title')
                uploader = info.get('uploader', 'Unknown')
                upload_date = info.get('upload_date', '')
                
                # Try to get subtitles
                if info.get('subtitles') or info.get('automatic_captions'):
                    print("Found captions, extracting...")
                    # Extract captions
                    transcript = self._extract_captions_with_ydl(url)
                    if transcript:
                        return {
                            'title': title,
                            'author': uploader,
                            'date': upload_date,
                            'content': transcript
                        }
                
                print("No captions found, falling back to audio transcription...")
                # Fallback to audio transcription
                transcript = self._transcribe_audio(url, info)
                return {
                    'title': title,
                    'author': uploader,
                    'date': upload_date,
                    'content': transcript
                }
                
        except Exception as e:
            raise Exception(f"Failed to process YouTube video: {e}")

    def _extract_captions_with_ydl(self, url: str) -> str:
        """Extract captions using yt-dlp."""
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en'],
            'skip_download': True,
            'quiet': True,
            'outtmpl': '/tmp/%(title)s.%(ext)s'
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
                # Look for downloaded subtitle files
                for file in Path('/tmp').glob('*.vtt'):
                    with open(file, 'r', encoding='utf-8') as f:
                        vtt_content = f.read()
                    
                    # Clean up VTT format
                    transcript = self._clean_vtt_content(vtt_content)
                    file.unlink()  # Clean up
                    return transcript
                    
        except Exception:
            pass
        
        return ""

    def _clean_vtt_content(self, vtt_content: str) -> str:
        """Clean VTT subtitle content."""
        lines = vtt_content.split('\n')
        transcript_lines = []
        
        for line in lines:
            line = line.strip()
            # Skip timestamp lines and metadata
            if '-->' in line or line.startswith('WEBVTT') or line.startswith('NOTE') or not line:
                continue
            
            # Remove HTML tags
            line = re.sub(r'<[^>]+>', '', line)
            if line:
                transcript_lines.append(line)
        
        # Deduplicate consecutive identical lines
        deduped = []
        for line in transcript_lines:
            if not deduped or line != deduped[-1]:
                deduped.append(line)
        
        return ' '.join(deduped)

    def _transcribe_audio(self, url: str, info: Dict) -> str:
        """Transcribe audio using Whisper."""
        if not self.whisper_model:
            print("Loading Whisper model (base)...")
            self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        
        # Download audio
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '/tmp/%(title)s.%(ext)s',
            'quiet': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
                # Find downloaded audio file
                for file in Path('/tmp').glob(f"{info.get('title', 'audio')}*"):
                    if file.suffix in ['.mp4', '.m4a', '.webm', '.mp3']:
                        print(f"Transcribing audio file: {file}")
                        segments, _ = self.whisper_model.transcribe(str(file))
                        transcript = ' '.join([segment.text for segment in segments])
                        file.unlink()  # Clean up
                        return transcript.strip()
                        
        except Exception as e:
            raise Exception(f"Audio transcription failed: {e}")
        
        return ""

    def extract_article_content(self, url: str) -> Dict[str, str]:
        """Extract content from web article."""
        print(f"Processing article URL: {url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title
            title = soup.find('title')
            title = title.get_text().strip() if title else 'Unknown Title'
            
            # Extract author (try various selectors)
            author = 'Unknown'
            for selector in ['.author', '.byline', '[rel="author"]', '.post-author']:
                author_elem = soup.select_one(selector)
                if author_elem:
                    author = author_elem.get_text().strip()
                    break
            
            # Extract date
            date = ''
            for selector in ['time', '.date', '.published', '[datetime]']:
                date_elem = soup.select_one(selector)
                if date_elem:
                    date = date_elem.get('datetime') or date_elem.get_text()
                    break
            
            # Extract main content
            # Try common content selectors
            content = ''
            for selector in ['article', '.content', '.post-content', '.entry-content', 'main', '.article-body']:
                content_elem = soup.select_one(selector)
                if content_elem:
                    # Remove script and style elements
                    for script in content_elem(['script', 'style']):
                        script.decompose()
                    content = content_elem.get_text()
                    break
            
            # Fallback: get all paragraph text
            if not content:
                paragraphs = soup.find_all('p')
                content = '\n'.join([p.get_text() for p in paragraphs])
            
            # Clean up content
            content = re.sub(r'\n\s*\n', '\n', content)  # Remove multiple newlines
            content = content.strip()
            
            return {
                'title': title,
                'author': author,
                'date': date,
                'content': content
            }
            
        except Exception as e:
            raise Exception(f"Failed to extract article content: {e}")

    def extract_file_content(self, file_path: str) -> Dict[str, str]:
        """Extract content from local file."""
        print(f"Processing local file: {file_path}")
        
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        try:
            if path.suffix.lower() == '.pdf':
                # For now, just return error - PDF extraction would need additional dependency
                raise Exception("PDF extraction not implemented yet. Please convert to text format.")
            
            # Read as text file
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return {
                'title': path.name,
                'author': 'Local File',
                'date': datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                'content': content
            }
            
        except Exception as e:
            raise Exception(f"Failed to read file: {e}")


class KnowledgeExtractor:
    """Extract structured knowledge using Claude."""
    
    def __init__(self, model: str = "sonnet"):
        self.model_names = {
            'haiku': 'claude-3-haiku-20240307',
            'sonnet': 'claude-sonnet-4-20250514',
            'opus': 'claude-opus-4-20250514'
        }
        self.model = self.model_names[model]
        # Using shared api.py gateway (no direct API client needed)

    # Client handled by api.py gateway

    def extract_knowledge(self, content: Dict[str, str], domain: str = None) -> List[Dict]:
        """Extract structured knowledge objects from content."""
        extraction_prompt = f"""
TASK: Extract structured knowledge objects from the provided content.

EXTRACTION TYPES (you must categorize each extraction as one of these):
- FRAMEWORK: A reusable mental model or decision heuristic
- CLAIM: A testable assertion with evidence rating (rate confidence 0.0-1.0)
- CASE_STUDY: A real-world example with context and outcome
- CONTRARIAN: A view that challenges conventional wisdom
- TECHNIQUE: A specific how-to method or process
- CONNECTION: A link between two existing concepts

REQUIREMENTS:
1. Extract 3-10 knowledge objects from the content
2. Each must be genuinely valuable and non-trivial
3. Focus on actionable insights, not generic statements
4. Include direct quotes from the source material when possible
5. Rate confidence based on evidence strength in the source

CONTENT TO ANALYZE:
Title: {content['title']}
Author: {content['author']}
Date: {content['date']}

Content:
{content['content'][:8000]}  # Truncate if too long

OUTPUT FORMAT:
Return a JSON array of objects, each with this exact structure:

```json
[
  {{
    "type": "framework|claim|case_study|contrarian|technique|connection",
    "name": "short descriptive name",
    "description": "1-3 sentences explaining the concept clearly",
    "domain": "ai-systems|strategy|manufacturing|leadership|finance|technology|marketing|etc",
    "confidence": 0.8,
    "tags": ["tag1", "tag2"],
    "implications": ["what this means for decisions/actions"],
    "raw_quote": "verbatim quote from source supporting this extraction"
  }}
]
```

Be specific and demanding. Extract only high-value knowledge that someone could actually use.
"""

        try:
            response_text = _call_claude(
                "You are a knowledge extraction engine. Output only valid JSON.",
                extraction_prompt,
                model=self.model,
                max_tokens=4000
            )
            
            # Extract JSON from response
            json_start = response_text.find('[')
            json_end = response_text.rfind(']') + 1
            
            if json_start == -1 or json_end == 0:
                raise Exception("No JSON array found in response")
            
            json_text = response_text[json_start:json_end]
            extractions = json.loads(json_text)
            
            # Add metadata to each extraction
            for extraction in extractions:
                extraction['id'] = str(uuid.uuid4())
                extraction['source'] = {
                    'title': content['title'],
                    'url': content.get('url', ''),
                    'author': content['author'],
                    'date': content['date']
                }
                extraction['extracted_at'] = datetime.now().isoformat()
                
                # Set domain if provided
                if domain:
                    extraction['domain'] = domain
                elif 'domain' not in extraction:
                    extraction['domain'] = 'general'
            
            return extractions
            
        except Exception as e:
            raise Exception(f"Knowledge extraction failed: {e}")


class AnalystAgent:
    """Main analyst agent orchestrator."""
    
    def __init__(self):
        self.content_extractor = ContentExtractor()
        self.knowledge_extractor = None
        
    def process_source(self, source: str, model: str = "sonnet", domain: str = None, dry_run: bool = False) -> Dict:
        """Process a content source and extract knowledge."""
        
        # Determine source type and extract content
        if source.startswith(('http://', 'https://')):
            if 'youtube.com' in source or 'youtu.be' in source:
                content = self.content_extractor.extract_youtube_content(source)
                content['url'] = source
            else:
                content = self.content_extractor.extract_article_content(source)
                content['url'] = source
        else:
            content = self.content_extractor.extract_file_content(source)
            content['url'] = f"file://{os.path.abspath(source)}"
        
        print(f"\nExtracted content:")
        print(f"Title: {content['title']}")
        print(f"Author: {content['author']}")
        print(f"Content length: {len(content['content'])} characters")
        
        if dry_run:
            print(f"\nContent preview:")
            print(content['content'][:500] + "..." if len(content['content']) > 500 else content['content'])
            print(f"\nExtraction prompt would be sent to: {model}")
            return {'dry_run': True, 'content': content}
        
        # Extract knowledge
        if not self.knowledge_extractor or self.knowledge_extractor.model != model:
            self.knowledge_extractor = KnowledgeExtractor(model)
            
        extractions = self.knowledge_extractor.extract_knowledge(content, domain)
        
        # Save extractions
        saved_files = self._save_extractions(extractions)
        
        # Update logs and index
        self._update_ingest_log(source, extractions, saved_files)
        self._update_knowledge_index()
        
        # Print summary
        print(f"\n=== EXTRACTION SUMMARY ===")
        print(f"Source: {source}")
        print(f"Model: {model}")
        print(f"Extracted: {len(extractions)} knowledge objects")
        print(f"Domains: {set(e['domain'] for e in extractions)}")
        print(f"Types: {set(e['type'] for e in extractions)}")
        
        for i, ext in enumerate(extractions, 1):
            print(f"\n{i}. {ext['type'].upper()}: {ext['name']}")
            print(f"   Domain: {ext['domain']} | Confidence: {ext['confidence']}")
            print(f"   {ext['description']}")
        
        return {
            'source': source,
            'extractions': extractions,
            'files_saved': saved_files
        }

    def _save_extractions(self, extractions: List[Dict]) -> List[str]:
        """Save extracted knowledge objects to domain directories."""
        saved_files = []
        
        for extraction in extractions:
            domain = extraction['domain']
            domain_dir = KNOWLEDGE_DIR / domain
            domain_dir.mkdir(parents=True, exist_ok=True)
            
            # Save individual file
            filename = f"{extraction['id']}.json"
            file_path = domain_dir / filename
            
            with open(file_path, 'w') as f:
                json.dump(extraction, f, indent=2)
            
            saved_files.append(str(file_path))
        
        return saved_files

    def _update_ingest_log(self, source: str, extractions: List[Dict], saved_files: List[str]):
        """Update the ingest log."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_file = STATE_DIR / 'ingest-log.json'
        
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'source': source,
            'extraction_count': len(extractions),
            'domains': list(set(e['domain'] for e in extractions)),
            'types': list(set(e['type'] for e in extractions)),
            'files_created': saved_files,
            'extraction_ids': [e['id'] for e in extractions]
        }
        
        # Read existing log
        logs = []
        if log_file.exists():
            try:
                with open(log_file) as f:
                    data = json.load(f)
                    # Ensure logs is a list
                    if isinstance(data, list):
                        logs = data
                    else:
                        # If it's not a list, start fresh
                        logs = []
            except (json.JSONDecodeError, Exception):
                # If file is corrupted, start fresh
                logs = []
        
        # Append new entry
        logs.append(log_entry)
        
        # Save updated log
        with open(log_file, 'w') as f:
            json.dump(logs, f, indent=2)

    def _update_knowledge_index(self):
        """Update the knowledge index."""
        index_file = KNOWLEDGE_DIR / '_index.json'
        
        # Scan all knowledge files
        index = {
            'generated_at': datetime.now().isoformat(),
            'domains': {},
            'total_objects': 0
        }
        
        for domain_dir in KNOWLEDGE_DIR.iterdir():
            if domain_dir.is_dir() and not domain_dir.name.startswith('_'):
                domain_name = domain_dir.name
                domain_objects = []
                
                for file_path in domain_dir.glob('*.json'):
                    try:
                        with open(file_path) as f:
                            obj = json.load(f)
                        domain_objects.append({
                            'id': obj['id'],
                            'type': obj['type'],
                            'name': obj['name'],
                            'confidence': obj['confidence'],
                            'tags': obj['tags'],
                            'file': str(file_path.relative_to(KNOWLEDGE_DIR))
                        })
                    except Exception:
                        continue
                
                if domain_objects:
                    index['domains'][domain_name] = {
                        'count': len(domain_objects),
                        'types': list(set(obj['type'] for obj in domain_objects)),
                        'objects': domain_objects
                    }
                    index['total_objects'] += len(domain_objects)
        
        # Save index
        with open(index_file, 'w') as f:
            json.dump(index, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='ANALYST - Extract structured knowledge from content sources')
    parser.add_argument('source', help='Content source (URL or file path)')
    parser.add_argument('--model', choices=['haiku', 'sonnet', 'opus'], default='sonnet',
                       help='Claude model to use (default: sonnet)')
    parser.add_argument('--domain', help='Override domain classification')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show content and extraction prompt without calling LLM')
    
    args = parser.parse_args()
    
    try:
        agent = AnalystAgent()
        result = agent.process_source(
            source=args.source,
            model=args.model,
            domain=args.domain,
            dry_run=args.dry_run
        )
        
        if not args.dry_run:
            print(f"\n✅ Successfully processed {args.source}")
            print(f"📁 Files saved: {len(result['files_saved'])}")
        
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()