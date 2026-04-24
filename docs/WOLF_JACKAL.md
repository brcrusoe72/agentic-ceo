# Wolf & Jackal — Predator Architecture

_Designed 2026-03-06. Replaces Hunter v1 (vacuum cleaner model)._

---

## Philosophy

**Wolf** hunts. It picks a target, tests it, commits or abandons, and eats the organs first.  
**Jackal** scavenges. It follows the Wolf, picks carcasses clean, finds what the Wolf was too focused to see.

They are not the same animal. They do not share instincts.

---

## 🐺 WOLF (replaces Hunter)

### Core Behavior: Apex Predator

A wolf does 4 things. In this order. Nothing else.

#### Phase 0: TERRITORY (5% of budget)
Before hunting, know the ground. What do we already know about this question?
- Scan `knowledge/` for existing frameworks related to the question
- Scan previous hunt syntheses for prior findings
- Build a **knowledge map**: what's known, what's thin, what's missing
- Output: `hunt_gaps[]` — the specific unknowns worth chasing

**This is what makes it a wolf, not a dog.** Dogs chase anything. Wolves know what they need.

#### Phase 1: STALK (15% of budget)
Broad, cheap, fast. Identify the herd.
- Fire search queries (web + YouTube) — same as today
- But DON'T fetch content yet
- For each result: title, snippet, URL, source domain
- Score each result against `hunt_gaps[]` — does this source likely fill a gap?
- **Rank and select top 5-7 targets.** Everything else is ignored. Not queued. Ignored.
- Model: **Sonnet** (fast assessment — no Haiku, ever)

```python
class Stalk:
    """Fast, cheap assessment. Haiku-powered."""
    
    def score_target(self, title, snippet, url, gaps):
        """0-10 score. Uses Haiku to assess likely value against known gaps."""
        # Factors:
        # - Does title/snippet suggest NEW information? (+3)
        # - Does it address a specific gap? (+3)  
        # - Source quality (domain reputation from Observer scores) (+2)
        # - Contradiction potential (disagrees with known?) (+2)
        # Returns: score, target_gap, reasoning
        
    def select_targets(self, results, max_targets=7):
        """Pick the herd's weak spots. Ignore everything else."""
        scored = [(self.score_target(r), r) for r in results]
        scored.sort(reverse=True)
        return scored[:max_targets]
```

#### Phase 2: TEST BITE (20% of budget)
For each selected target, take a taste before committing.
- Fetch first 1,000 chars only
- Quick Haiku assessment: "Is there meat here? Y/N + why"
- If no meat → abandon immediately (zero sunk cost)
- If meat → promote to KILL phase
- Expected survival rate: ~40-50% (wolves kill 14% of what they chase; we're more selective upfront)

```python
class TestBite:
    """Quick taste. Abandon if empty."""
    
    def bite(self, url, gap):
        """Fetch 1K chars, assess with Sonnet. Return: commit/abandon + reason."""
        content = fetch_content(url, max_chars=1000)
        assessment = call_claude(
            "You are testing whether this source contains valuable, non-obvious information. "
            "Be HARSH. Most sources are thin. Say COMMIT only if you see specific data, "
            "frameworks, or contrarian takes. Say ABANDON if it's generic, surface-level, or SEO filler.",
            f"GAP: {gap}\nFIRST 1000 CHARS:\n{content}",
            model="claude-sonnet-4-5-20250929"
        )
        # Parse: COMMIT or ABANDON + one-line reason
```

#### Phase 3: KILL (50% of budget)
Full extraction on committed targets only. This is where Sonnet earns its cost.
- Fetch full content
- Extract with a **hierarchical value system**:
  1. 🫀 **Organs** (highest value): What contradicts existing knowledge? What's surprising?
  2. 🩸 **Meat** (high value): What fills a specific gap? What's genuinely new?
  3. 🦴 **Bones** (low value): What confirms existing knowledge? (Log it, don't celebrate it)
- Sub-component generation is FILTERED through gaps — only chase sub-components that address unknowns
- Model: **Sonnet** (this is the only phase that needs real intelligence)

```python
class Kill:
    """Full extraction. Sonnet-powered. Prioritize organs over bones."""
    
    def extract(self, content, source, question, known_frameworks, gaps):
        """Extract with value hierarchy. Organs > Meat > Bones."""
        system = """You are extracting knowledge from a source. You know what we already know 
        and what gaps remain. Prioritize:
        
        ORGANS (mark as 'organ'): Information that CONTRADICTS or CHALLENGES existing understanding.
        MEAT (mark as 'meat'): Information that fills a SPECIFIC GAP in our knowledge.
        BONES (mark as 'bone'): Information that confirms what we already know.
        
        Be ruthless. If it's surface-level or generic, mark it as bone. 
        We eat organs first."""
```

#### Phase 4: FEED (10% of budget)
Synthesis — but wolf-style. Not a book report. A territorial update.
- What changed in our understanding? (Not: "what did we find")
- Which gaps closed? Which new gaps opened?
- Where should the NEXT hunt go?
- Update the knowledge map

```python
class Feed:
    """Post-kill synthesis. Update the territory map."""
    
    def digest(self, kills, gaps_before):
        """What changed? What's still unknown? Where next?"""
        gaps_closed = [g for g in gaps_before if any kill addresses g]
        gaps_opened = [new gaps discovered during kills]
        territory_update = {
            "organs_found": [contradictions and surprises],
            "gaps_closed": gaps_closed,
            "gaps_opened": gaps_opened,
            "next_hunt_targets": prioritized new questions,
            "confidence_delta": how much our understanding changed
        }
```

### Wolf Metrics (replace current)
- ❌ ~~Sources processed~~ → ✅ **Kill rate** (targets committed / targets stalked)
- ❌ ~~Frameworks extracted~~ → ✅ **Organs found** (contradictions + genuine novelty)
- ❌ ~~Cost per hunt~~ → ✅ **Cost per organ** (efficiency of surprising discovery)
- ❌ ~~Novelty curve~~ → ✅ **Gap closure rate** (unknowns resolved per hunt)
- NEW: **Abandon rate** (sources tested and walked away from — higher is better, means selectivity)

### Wolf Config
```json
{
  "stalk_model": "claude-sonnet-4-5-20250929",
  "bite_model": "claude-sonnet-4-5-20250929", 
  "kill_model": "claude-sonnet-4-5-20250929",
  "feed_model": "claude-sonnet-4-5-20250929",
  "max_targets": 7,
  "bite_chars": 1000,
  "min_bite_score": 6,
  "budget_split": {"territory": 0.05, "stalk": 0.15, "bite": 0.20, "kill": 0.50, "feed": 0.10},
  "kill_value_weights": {"organ": 3, "meat": 2, "bone": 0.5}
}
```

---

## 🐺 → 🦊 Transition Plan

Wolf replaces Hunter. Same file (`tools/hunter.py`), same CLI interface, same integration with run-cycle.sh. Internal restructure only.

**What stays:** search(), fetch_content(), save_frameworks(), knowledge base format, hunt state files, CLI args  
**What changes:** The Hunt class splits into phases (Territory → Stalk → TestBite → Kill → Feed)  
**What dies:** Linear source queue, uniform extraction, "process everything" mentality

---

## 🦊 JACKAL (new agent)

### Core Behavior: Lateral Scavenger

Jackal runs AFTER Wolf. It never searches the web. It never fetches new sources. It only works with what Wolf already killed.

#### Input
- Wolf's hunt results (frameworks, sources, synthesis)
- Full knowledge base
- Previous hunt syntheses

#### What Jackal Does

**1. Carcass Picking** — Re-read Wolf's extracted content looking for things Wolf missed.
Wolf hunts with a specific question. That focus is its strength AND its blind spot. Jackal reads the same content with NO specific question — just "what else is here?"

```python
class CarcassPicker:
    """Re-examine Wolf's sources for overlooked value."""
    
    def pick(self, source_content, wolf_extraction):
        """What did Wolf miss? What's in here that doesn't fit the question but matters?"""
        system = """You are re-examining content that was already analyzed for a specific question.
        The previous analysis extracted certain frameworks. Your job is different:
        
        1. What patterns exist that DON'T relate to the original question?
        2. What throwaway lines contain hidden insight?
        3. What assumptions does the author make that deserve questioning?
        4. What would a DIFFERENT field see in this same content?
        
        You are not confirming. You are looking sideways."""
```

**2. Cross-Kill Connections** — Find links between Wolf's kills that Wolf didn't see.
Wolf processes sources one at a time. Jackal sees them all at once and finds the threads.

```python
class ThreadFinder:
    """Connect Wolf's kills. Find patterns across sources."""
    
    def weave(self, all_kills):
        """What connects these sources that isn't obvious?"""
        # Look for:
        # - Same concept, different terminology (translation opportunities)
        # - Contradictions between sources Wolf didn't flag
        # - Implicit supply chains (A needs B, B needs C, who provides C?)
        # - Temporal patterns (is this field moving? Where?)
        # - Consensus without evidence (everyone says X, nobody cites why)
```

**3. Knowledge Base Archaeology** — Connect today's hunt to things from weeks ago.
This is Jackal's unique power. Wolf is present-focused. Jackal has long memory.

```python
class Archaeologist:
    """Connect new kills to old knowledge. Find the long threads."""
    
    def dig(self, new_frameworks, knowledge_base):
        """What from 3 hunts ago suddenly becomes relevant?"""
        # Search existing knowledge for:
        # - Frameworks that complement new findings
        # - Old gaps that new findings partially fill
        # - Patterns that only become visible with accumulated knowledge
        # - Contradictions between old and new (understanding evolved?)
```

**4. Emit Scavenger Report** — Output is fundamentally different from Wolf's synthesis.

Wolf outputs: "Here's what we learned about X."  
Jackal outputs: "Here's what you're not seeing."

```python
class ScavengerReport:
    """Jackal's output. Not a summary. A provocation."""
    
    def report(self, picked, threads, archaeology):
        """
        Structure:
        - OVERLOOKED: Things in the sources nobody asked about
        - CONNECTED: Threads between sources that aren't obvious
        - RESURFACED: Old knowledge that's suddenly relevant
        - SUSPICIOUS: Consensus without evidence, assumptions untested
        - QUESTIONS: What should the NEXT Wolf hunt chase?
        """
```

### Jackal Config
```json
{
  "model": "claude-sonnet-4-5-20250929",
  "max_sources_to_reexamine": 5,
  "knowledge_lookback_days": 30,
  "min_connection_confidence": 0.6,
  "run_after": "hunter"
}
```

### Jackal Metrics
- **Overlooked discoveries**: Insights found in Wolf's sources that Wolf missed
- **Cross-connections**: Links between sources Wolf didn't identify
- **Resurfaced knowledge**: Old frameworks made newly relevant
- **Question generation**: Quality of suggested next hunts (scored by Observer)

---

## Integration with CEO Cycle

```
run-cycle.sh (updated):

do_outward() {
    run_stage "Wolf"    "$TOOLS/hunter.py" "$question" ...   # Hunt
    run_stage "Jackal"  "$TOOLS/jackal.py" --last-hunt       # Scavenge Wolf's kills
    run_stage "Nexus"   "$TOOLS/nexus.py"                    # Synthesize
    run_stage "Barriers" "$TOOLS/barrier_cycle.py"           # Check barriers
}
```

Wolf runs. Jackal follows. Nexus synthesizes both. Observer scores both.

---

## Build Order

**Phase 1: Wolf refactor (Priority — 3-4 hours)**
1. Split Hunt class into Territory → Stalk → TestBite → Kill → Feed phases
2. Implement Stalk + TestBite assessment phases (Sonnet throughout)
3. Implement value hierarchy (organ/meat/bone) in extraction
4. Add gap-tracking (what's known vs. unknown)
5. Update metrics to wolf metrics
6. Keep CLI + run-cycle.sh integration identical

**Phase 2: Jackal build (2-3 hours)**
1. Create `tools/jackal.py` — reads Wolf's output, no web access
2. Implement CarcassPicker, ThreadFinder, Archaeologist
3. Scavenger report output format
4. Wire into run-cycle.sh after Hunter stage
5. Observer scoring for Jackal output

**Phase 3: Integration tuning (1-2 hours)**
1. Jackal questions feed into Nexus recommendations
2. Observer scores both Wolf and Jackal independently
3. Evolver adjusts configs for both based on performance
4. Cross-agent feedback: Jackal's "suspicious" findings become Wolf priority targets

---

## What This Kills

- Linear source queuing (replaced by Stalk → select → commit/abandon)
- Uniform extraction (replaced by organ/meat/bone hierarchy)
- "Process everything" mentality (replaced by deliberate abandonment)
- Search-only discovery (Jackal finds things without searching)
- Present-only focus (Jackal connects across time)

## What This Preserves

- Knowledge base format (JSON frameworks, domains, connections)
- Search infrastructure (AgentSearch API, YouTube)
- State management (hunt IDs, state files)
- run-cycle.sh stage pattern
- Observer/Critic/Evolver feedback loop
- Budget controls and cost tracking
