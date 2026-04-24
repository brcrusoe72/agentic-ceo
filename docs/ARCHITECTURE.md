# Agentic CEO — System Architecture

_Designed 2026-03-03 by Roix for Bri_

---

## What This Is

An autonomous multi-agent system that acquires knowledge, extracts intelligence, builds a persistent worldview, and applies it to real decisions. It has a moral code, a purpose, and it learns relentlessly.

Not a chatbot. Not a pipeline. An **organism**.

---

## Why Multi-Agent (vs Single Agent)

**Option A: Single mega-agent** — one big prompt that does everything.
- ❌ Context window fills up fast. Can't hold 500 articles + reasoning + planning.
- ❌ No specialization. Jack of all trades, master of none.
- ❌ Can't run in parallel. Ingesting a video blocks decision-making.
- ❌ No internal debate. One perspective, one blind spot.

**Option B: Pipeline** — sequential stages (ingest → extract → store → query).
- ⚠️ Better than single agent. Each stage is focused.
- ❌ Linear. Can't discover new sources while analyzing old ones.
- ❌ No autonomy. Doesn't decide what to learn next.
- ❌ No emergent behavior. Output is predictable.

**Option C: Multi-agent with shared memory (chosen)**
- ✅ Parallel: Scout finds while Analyst extracts while Librarian organizes.
- ✅ Specialized: Each agent is tuned for one job.
- ✅ Observable: All communication goes through the knowledge base — you can watch it.
- ✅ Debatable: Critic challenges Analyst. Director resolves conflicts.
- ✅ Autonomous: Director sets its own agenda based on goals and gaps.
- ✅ Emergent: Agents surface patterns none of them could find alone.

---

## The Architecture: Blackboard + Orchestrator Hybrid

```
                    ┌─────────────┐
                    │  DIRECTOR   │  ← Plans, prioritizes, resolves
                    │  (the CEO)  │
                    └──────┬──────┘
                           │ reads goals, gaps, agent reports
                           │ writes missions, priorities
                    ┌──────▼──────┐
                    │ KNOWLEDGE   │  ← The shared brain
                    │    BASE     │  ← All agents read/write here
                    │ (blackboard)│
                    └──┬──┬──┬──┬─┘
                       │  │  │  │
            ┌──────────┘  │  │  └──────────┐
            │             │  │             │
      ┌─────▼───┐  ┌─────▼──▼──┐  ┌──────▼────┐
      │  SCOUT  │  │ ANALYST   │  │ LIBRARIAN  │
      │ (finds) │  │ (extracts)│  │ (organizes)│
      └─────────┘  └───────────┘  └────────────┘
                         │
                   ┌─────▼─────┐
                   │  CRITIC   │
                   │(challenges)│
                   └───────────┘
```

### Why Blackboard Pattern (vs Message Passing)

**Message passing** (agents send messages directly to each other):
- ❌ Hard to observe — conversations are ephemeral
- ❌ Tight coupling — Agent A must know Agent B exists
- ❌ State is scattered across conversations

**Blackboard** (agents read/write a shared knowledge base):
- ✅ All state is visible in files — Bri can read every thought
- ✅ Loose coupling — agents don't know about each other
- ✅ Persistent — nothing is lost
- ✅ Auditable — you can trace every decision
- ✅ Works with OpenClaw's sub-agent system natively

---

## The Agents

### 1. DIRECTOR (The CEO Brain)
**Role:** Strategic planning, goal-setting, priority allocation, conflict resolution.
**Runs:** On demand + daily planning cycle
**Reads:** Goals, knowledge gaps, agent reports, the constitution
**Writes:** Mission queue, priority rankings, strategic decisions
**Model:** Opus (needs deep reasoning)

The Director doesn't ingest content. It thinks about what to learn next, what matters, and why. It reviews what the other agents found and decides: "This contradicts our existing framework on X — Critic, investigate." Or: "We have 12 articles on AI agents but nothing on the economic counterarguments — Scout, find opposing views."

**Why separate from other agents:** Strategy and execution are different cognitive modes. Mixing them produces agents that are busy but not directed.

### 2. SCOUT (The Discoverer)
**Role:** Find new content sources. Monitor feeds. Discover what's worth learning.
**Runs:** Scheduled (2-3x daily) + on Director request
**Reads:** Priority topics, existing sources, knowledge gaps
**Writes:** Source queue (URLs + why they matter), new topic discoveries
**Model:** Haiku (fast, cheap — it's just finding links)

Scout watches:
- YouTube channels/playlists you subscribe to
- RSS feeds from blogs/newsletters
- News APIs (free tiers: NewsAPI, Google News RSS)
- Paid subscriptions (WSJ, HBR, etc. — getting money's worth)
- Twitter/X threads from specific thinkers
- Reddit threads in target subreddits
- Podcast feeds

**Why it's its own agent:** Discovery is a different skill than analysis. Scout optimizes for breadth and relevance filtering. It should find 50 things and recommend 5.

### 3. ANALYST (The Extractor)
**Role:** Ingest content, extract structured intelligence — frameworks, models, claims, evidence.
**Runs:** Whenever Scout queues something + on demand
**Reads:** Source queue, extraction templates, domain context
**Writes:** Structured framework files, raw analysis notes
**Model:** Sonnet (good balance of quality and cost for extraction)

This is `ytanalyze` evolved. But instead of summaries, it extracts typed objects:

```
FRAMEWORK — a reusable mental model or decision heuristic
CLAIM — a testable assertion with evidence
CASE_STUDY — a real-world example with context and outcome  
CONTRARIAN — a view that challenges conventional wisdom
TECHNIQUE — a specific how-to method
CONNECTION — a link between two existing frameworks
```

**Why structured output matters:** Summaries decay. You read them once and forget. Structured frameworks compose — you can query "show me all CONTRARIAN views on SaaS" or "what FRAMEWORKS apply to hiring decisions." That's the CEO capability.

### 4. LIBRARIAN (The Organizer)
**Role:** Maintain the knowledge base. Index, deduplicate, find patterns, build connections.
**Runs:** After each Analyst batch + weekly deep review
**Reads:** Everything in the knowledge base
**Writes:** Index files, connection maps, pattern reports, gap analyses
**Model:** Sonnet

The Librarian notices: "We have 8 frameworks about context engineering from 5 different sources. 6 agree on core principles. 2 diverge. Here's a synthesis." It also notices gaps: "We have deep coverage on AI infrastructure but nothing on regulatory risk."

**Why not merge with Analyst:** Analyst works source-by-source (microscope). Librarian works across sources (telescope). Different scope, different insight.

### 5. CRITIC (The Challenger)
**Role:** Stress-test frameworks. Find contradictions. Challenge assumptions. Play devil's advocate.
**Runs:** On Director request + after major new frameworks are added
**Reads:** Frameworks, claims, evidence
**Writes:** Critique reports, confidence adjustments, contradiction flags
**Model:** Opus (needs adversarial reasoning)

This is the most important agent that most systems skip. Without it, the knowledge base becomes an echo chamber of whatever YouTube algorithm serves up. Critic asks:
- "What's the evidence for this claim? Is it anecdotal or empirical?"
- "This framework contradicts the one from last week. Which holds up better?"
- "What would someone who disagrees with this say?"
- "What's the failure mode of this mental model?"

**Why this matters morally:** A system that only accumulates confirming evidence is dangerous. Critic is the conscience — it enforces intellectual honesty.

---

## The Constitution (Moral Code)

The system has values. They're not decorative.

```yaml
# constitution.yaml

purpose: >
  Acquire, organize, and synthesize knowledge to support
  better decisions. Serve the human's genuine long-term
  interests, not their impulses.

principles:
  intellectual_honesty:
    - Never suppress contradicting evidence
    - Confidence scores must reflect actual uncertainty
    - "I don't know" is a valid and valuable output
    
  epistemic_humility:
    - Weight empirical evidence over thought-leader opinion
    - Track prediction accuracy over time
    - Downgrade sources that are consistently wrong
    
  value_maximization:
    - Extract maximum insight per dollar spent on content
    - Prefer free sources when quality is equal
    - Track ROI on paid subscriptions (insights extracted / cost)
    
  anti_echo_chamber:
    - Actively seek opposing viewpoints on any topic with >5 frameworks
    - Critic must review any framework rated >0.9 confidence
    - Flag when all sources on a topic share the same bias
    
  transparency:
    - Every conclusion must cite its sources
    - Every decision must show its reasoning
    - The human can audit any part of the system at any time
    
  autonomy_boundaries:
    - May acquire and analyze content freely
    - May organize and synthesize freely
    - Must NOT act on conclusions without human approval
    - Must NOT spend money without pre-authorized budgets
    - Must flag when operating outside known domains

learning_drive: >
  The system should be hungry. Not satisfied with what it knows.
  Always looking for: gaps in understanding, emerging topics,
  updated evidence, frameworks that could be wrong.
  Knowledge that isn't challenged isn't trusted.
```

---

## The Knowledge Base Structure

```
ceo/
├── ARCHITECTURE.md          ← this file
├── constitution.yaml        ← moral code and values
├── state/
│   ├── missions.json        ← current Director priorities
│   ├── source-queue.json    ← Scout's discovery queue
│   ├── ingest-log.json      ← what's been processed
│   └── agent-reports/       ← each agent's latest output
├── knowledge/
│   ├── _index.json          ← master index of all frameworks
│   ├── _connections.json    ← cross-framework links
│   ├── _gaps.json           ← known unknowns
│   ├── ai-systems/          ← domain folder
│   │   ├── context-engineering.json
│   │   ├── memory-architecture-thesis.json
│   │   └── ...
│   ├── strategy/
│   ├── manufacturing/
│   ├── leadership/
│   ├── finance/
│   └── contrarian/          ← deliberately opposing views
├── sources/
│   ├── subscriptions.yaml   ← paid + free sources to monitor
│   ├── trust-scores.json    ← source reliability tracking
│   └── roi-tracker.json     ← value per dollar on paid content
├── critiques/
│   ├── pending.json         ← frameworks awaiting review
│   └── resolved/            ← past critiques + outcomes
└── tools/
    ├── ytanalyze.py         ← video ingestion (built)
    ├── article_ingest.py    ← article/news ingestion
    ├── podcast_ingest.py    ← podcast ingestion
    └── pdf_ingest.py        ← PDF/book ingestion
```

**Why files over database:** 
- Human-readable (Bri can open any file and see what's happening)
- Git-trackable (version history of the system's evolving worldview)
- Agent-readable (any LLM can process JSON/markdown)
- Zero infrastructure (no Postgres, no Docker, no maintenance)
- Later: add vector embeddings as an index layer, not a replacement

---

## How It Runs (Step by Step)

### Daily Cycle

**Morning (8 AM) — Director plans:**
1. Reads constitution (reminds itself of purpose + values)
2. Reviews knowledge gaps from Librarian
3. Reviews overnight Scout discoveries
4. Writes today's missions: "Priority: deep-dive on [topic]. Scout: find opposing views on [framework]. Analyst: process these 5 queued sources."

**Throughout day — Scout discovers:**
1. Checks RSS feeds, YouTube channels, news sources
2. Filters by relevance to current priorities + ongoing interests
3. Queues sources with rationale: "This video challenges our memory-architecture thesis — high priority"

**Throughout day — Analyst ingests:**
1. Pulls from source queue (highest priority first)
2. Runs appropriate ingest tool (ytanalyze, article parser, etc.)
3. Extracts structured frameworks, claims, connections
4. Writes to knowledge base

**Afternoon — Librarian organizes:**
1. Indexes new entries
2. Finds connections to existing frameworks
3. Identifies emerging patterns ("3 new sources this week all mention X")
4. Updates gap analysis

**Evening — Critic reviews:**
1. Reviews new high-confidence frameworks
2. Checks for contradictions with existing knowledge
3. Flags anything that needs deeper investigation
4. Writes critique reports

**Weekly — Director reflects:**
1. What did we learn this week?
2. What changed in our worldview?
3. What are we still wrong about?
4. What should next week's focus be?
5. Are paid subscriptions delivering value?

### On-Demand (Bri asks a question)

1. Director interprets the question
2. Librarian searches knowledge base for relevant frameworks
3. Analyst pulls additional context if needed
4. Critic stress-tests the proposed answer
5. Director synthesizes final response with citations

---

## Observability (How Bri Watches It Work)

Every agent writes to `state/agent-reports/` after each run:

```json
{
  "agent": "scout",
  "timestamp": "2026-03-03T14:00:00Z",
  "mission": "Find opposing views on memory-architecture thesis",
  "actions": [
    "Searched 'criticism of RAG and vector databases' — found 3 relevant articles",
    "Checked HackerNews for contrarian AI takes — found 1 thread with 200+ comments",
    "Monitored YouTube subscriptions — 2 new videos on AI agents, 1 relevant"
  ],
  "queued": [
    {"url": "...", "reason": "Directly argues against persistent context", "priority": "high"},
    {"url": "...", "reason": "Case study of RAG failure in production", "priority": "medium"}
  ],
  "cost": "$0.003"
}
```

Bri can:
- Read any agent report in real-time
- See the full knowledge base evolve (it's just files)
- Watch the Director's reasoning about priorities
- Read Critic's challenges and how they were resolved
- Track total spending and ROI

---

## Cost Projections

| Component | Frequency | Model | Est. Cost |
|---|---|---|---|
| Director planning | 1x daily | Opus | ~$0.15/day |
| Scout discovery | 3x daily | Haiku | ~$0.01/day |
| Analyst ingestion | 5-10 sources/day | Sonnet | ~$0.20/day |
| Librarian organizing | 1x daily | Sonnet | ~$0.10/day |
| Critic reviewing | 2-3x weekly | Opus | ~$0.10/day avg |
| On-demand queries | ~5/day | Opus | ~$0.25/day |

**Total: ~$0.80/day = ~$24/month**

Plus content costs:
- YouTube: free
- News RSS: free
- NewsAPI free tier: 100 req/day
- Optional paid subs: WSJ ($40/mo), HBR ($15/mo), etc.

---

## Build Status (2026-03-03)

| Component | Status | Notes |
|---|---|---|
| Constitution + KB structure | ✅ Built | Values, domains, file structure |
| Analyst agent | ✅ Built + tested | Extracts structured frameworks from videos/articles |
| Scout agent | ✅ Built + tested | Discovers 38+ sources per run, $0 cost |
| Librarian agent | ✅ Built | Reindex works; connection-finding needs batching |
| Director agent | ✅ Built + upgraded | Now assigns HUNTS with research questions |
| Critic agent | ✅ Built | Challenges frameworks, adjusts confidence |
| **Hunter agent** | ✅ Built + tested | **Recursive research — the core engine** |
| Orchestrator | ✅ Built | Full daily cycle: Director→Hunts→Scout→Analyst→Librarian→Critic |
| Self-improvement (evolve) | 🏗️ Building | Analyzes own code, suggests patches |
| Tool-building (adapters) | 🏗️ Building | Auto-builds tools when hitting obstacles |
| **Complexity Dissolver** | ✅ Built | Strips complexity theater from regulations/standards |
| **Knowledge Equalizer** | ✅ Built | Democratizes insider knowledge for small players |
| **Participation Bridge** | ✅ Built | Closes gap from awareness to action on opportunities |
| **Barrier Cycle orchestrator** | ✅ Built | Runs Dissolve → Equalize → Bridge in sequence |

## The Hunter — Core Innovation

The Hunter is what makes this system different. It doesn't wait to be told what to read.
It takes a QUESTION, searches everywhere, extracts frameworks, identifies sub-components
it doesn't understand, and RECURSES — going deeper autonomously.

First test: 10 sources, 40 frameworks, $0.30, recursive depth, synthesized into coherent understanding.

## Self-Improvement Loop

The system can analyze its own code and suggest improvements:
- Measures frameworks/dollar, source success rate, extraction quality
- Identifies inefficiencies (like the Librarian's O(n²) problem)
- Generates patches (saved for human review, not auto-applied)
- Tracks obstacles and builds adapter tools to overcome them

---

## Barrier-Breaking Subsystem

The system identified 100 psychological barriers across 30 domains via the barrier mapper.
Three autonomous agents target the top 3 barrier types:

```
                    ┌──────────────┐
                    │ BARRIER CYCLE│  ← barrier_cycle.py orchestrator
                    │  ORCHESTRATOR│
                    └──────┬───────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
     ┌──────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐
     │  DISSOLVER  │ │EQUALIZER │ │   BRIDGE    │
     │ (complexity)│ │(knowledge│ │(participation│
     │  19 hits    │ │ 14 hits) │ │  14 hits)   │
     └──────┬──────┘ └────┬─────┘ └──────┬──────┘
            │              │              │
            │   knowledge/ │   knowledge/ │   knowledge/
            │   dissolved/ │   equalized/ │   bridged/
            └──────────────┴──────┬───────┘
                                  │
                           ┌──────▼──────┐
                           │ KNOWLEDGE   │
                           │    BASE     │
                           └─────────────┘
```

**Data flow:** Dissolve and Equalize run first; Bridge reads their outputs to build
more informed action plans. Bridge also generates requests back to Dissolve/Equalize
when it finds gaps ("this participation barrier exists because of complexity theater
in regulation X — sending to Dissolve").

**Cost:** Each agent targets <$1.00/cycle. Full barrier cycle: ~$2-3.

**CLI:**
- `python3 tools/barrier_cycle.py` — full cycle
- `python3 tools/dissolve.py --target "FSMA 204"` — dissolve specific regulation
- `python3 tools/equalizer.py --domain "food-manufacturing"` — equalize specific domain
- `python3 tools/bridge.py --opportunity "government procurement"` — bridge specific opportunity

---

## What This Becomes

Month 1: A knowledge base with 100-200 extracted frameworks from videos, articles, podcasts.
Month 3: A searchable worldview with cross-referenced mental models, tracked predictions, challenged assumptions.
Month 6: A genuine strategic asset — an externalized second brain that's been reading, thinking, and organizing for 6 months straight, 24/7, with perfect recall.

The compounding effect is real. Each new piece of content gets analyzed in the context of everything before it. Connection density grows exponentially. The system at month 6 is qualitatively different from month 1.

---

_"The people who build persistent, searchable, AI-accessible knowledge systems will have AI that gets better at helping them over time."_ — The video we just analyzed. It was right.
