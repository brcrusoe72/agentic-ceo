# Agentic CEO

**An autonomous multi-agent research system that acquires knowledge, builds a persistent worldview, and improves itself.**

3,700+ knowledge entries. 173 research hunts. 7 specialized agents. 35 days of autonomous operation. ~$24/month.

---

## What This Is

A system of specialized AI agents that work together to research, extract, organize, challenge, and synthesize knowledge — autonomously. It ran daily from March 3 to April 6, 2026, accumulating a structured knowledge base across 68 domains without human intervention beyond setting initial goals.

Not a chatbot. Not a RAG pipeline. A research organism.

**Read the full technical deep-dive:** [How I Built a Multi-Agent Research System That Ran Autonomously for 35 Days →](docs/DEEP_DIVE.md)

---

## Architecture

```
                    ┌─────────────┐
                    │  DIRECTOR   │  Plans, prioritizes, resolves
                    │  (the CEO)  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ KNOWLEDGE   │  3,700+ entries
                    │    BASE     │  68 domains
                    │ (blackboard)│  All agents read/write
                    └──┬──┬──┬──┬┘
                       │  │  │  │
            ┌──────────┘  │  │  └──────────┐
            │             │  │             │
      ┌─────▼───┐  ┌─────▼──▼──┐  ┌──────▼────┐
      │  WOLF   │  │  JACKAL   │  │  NEXUS    │
      │ (hunts) │  │(scavenges)│  │(connects) │
      └─────────┘  └───────────┘  └───────────┘
            │             │              │
            │       ┌─────▼─────┐       │
            │       │  CRITIC   │       │
            │       │(challenges)│       │
            │       └───────────┘       │
            │                           │
      ┌─────▼───────────────────────────▼─────┐
      │            INWARD CYCLE                │
      │  Observer → Critic → Evolver           │
      │  (watches)  (challenges)  (improves)   │
      └───────────────────────────────────────┘
```

### Design Choice: Blackboard Over Message Passing

All agents communicate through a shared file-based knowledge base — not by talking to each other. This means:

- **Observable:** Every thought is a file. You can read every decision the system made.
- **Loosely coupled:** Agents don't know about each other. Add or remove agents without rewiring.
- **Persistent:** Nothing is lost. The knowledge base is version-controlled.
- **Auditable:** Trace any conclusion back to its source, extraction, and critique.

---

## The Agents

### Outward Cycle (World-Facing)

| Agent | What It Does | Key Detail |
|-------|-------------|------------|
| **Director** | Sets daily research priorities based on knowledge gaps | Reads the constitution, reviews what's missing, writes missions |
| **Wolf** | Hunts for answers using a 5-phase predator protocol | Stalks → test-bites → commits or abandons → extracts → synthesizes |
| **Jackal** | Scavenges Wolf's kills for overlooked insights | Never searches the web — re-reads what Wolf found with fresh eyes |
| **Nexus** | Finds cross-domain connections across the knowledge base | "3 independent evidence lines point to the same opportunity" |
| **Dissolve** | Strips complexity theater from regulations and standards | Turns 200-page FSMA documents into actionable guides |
| **Equalizer** | Democratizes insider knowledge | Makes expert-level information accessible to non-experts |
| **Bridge** | Closes the gap between knowing and doing | Produces step-by-step action plans from research findings |

### Inward Cycle (Self-Facing)

| Agent | What It Does | Key Detail |
|-------|-------------|------------|
| **Observer** | Measures everything — kill rates, cost per insight, source reliability | Grades each hunt A through F |
| **Critic** | Challenges assumptions, flags blind spots, demands evidence | Reviews any framework rated above 0.9 confidence |
| **Evolver** | Implements improvements based on Critic's recommendations | Adjusts search strategies, tunes thresholds, reallocates budget |

---

## The Wolf Protocol

The core research engine. Not a web scraper — a predator.

```
Phase 0: TERRITORY (5% budget)
  What do we already know? What gaps remain?

Phase 1: STALK (15% budget)
  Broad search. Score results against known gaps.
  Select 5-7 targets. Ignore everything else.

Phase 2: TEST BITE (20% budget)
  Fetch first 1,000 characters of each target.
  Commit or abandon. Most sources are thin. Walk away fast.

Phase 3: KILL (50% budget)
  Full extraction on committed targets only.
  Value hierarchy: Organs (contradictions) > Meat (gap-fillers) > Bones (confirmations)

Phase 4: FEED (10% budget)
  What changed? Which gaps closed? Which opened?
  Where should the next hunt go?
```

**Real metrics from 173 hunts:**
- Average kill rate: 40-60% (targets committed / targets stalked)
- Average cost per hunt: $0.13–$0.30
- Average frameworks per hunt: 10-20
- Best source: arxiv.org (96.6% success rate, 5.67 frameworks/fetch)
- Dead sources identified: medium.com, reddit.com (0% extraction across all attempts)

---

## The Curiosity Engine

The system doesn't just research what it's told to. It maintains a list of things it finds genuinely interesting:

- Complex adaptive systems and emergence
- History of failed predictions by experts
- Biomimicry in engineering
- Mathematical paradoxes and what they reveal about logic
- The history of railroad standardization (and what it teaches about protocol design)
- How blind cavefish adapt — and what it says about vestigial systems in software

Twice a week, the Director picks a curiosity topic, runs a full research cycle, and the Essayist writes a long-form essay. The results are published at [brcrusoe72.github.io/directors-notes](https://brcrusoe72.github.io/directors-notes).

Sample hunt: [How do blind cavefish repurpose visual neural tissue?](docs/examples/cavefish-hunt.md) — 4 kills, 18 frameworks, 8 organs, $0.18. Overturned the "repurposing" narrative: the tectum retains its excitatory architecture while selectively losing inhibitory circuits. The pleiotropic package hypothesis is dead.

---

## The Constitution

The system has values. They're enforced, not decorative.

```yaml
intellectual_honesty:
  - Never suppress contradicting evidence
  - Confidence scores must reflect actual uncertainty
  - "I don't know" is a valid and valuable output

anti_echo_chamber:
  - Actively seek opposing viewpoints on any topic with >5 frameworks
  - Critic must review any framework rated >0.9 confidence
  - Flag when all sources on a topic share the same bias

autonomy_boundaries:
  - May acquire and analyze content freely
  - Must NOT act on conclusions without human approval
  - Must NOT spend money without pre-authorized budgets
```

---

## What 35 Days Produced

| Metric | Count |
|--------|-------|
| Knowledge base entries | 3,704 |
| Research hunts completed | 173 |
| Domains covered | 68 |
| Agent reports generated | 61 |
| Pipeline summaries | 20 |
| Nexus executive briefs | 22 |
| Observer daily reports | 7 |
| Published essays | 4+ |
| Total cost | ~$25-30 |

### Knowledge Domains (sample)

`technology` · `strategy` · `manufacturing` · `ai-systems` · `finance` · `psychology` · `military-training` · `trust-mechanisms` · `procurement` · `supply-chain` · `food-safety` · `restaurant-operations` · `philosophy` · `economics` · `agriculture` · `nutrition` · `statistics` · `regulatory` · `contrarian`

---

## Running It

### Prerequisites

- Python 3.12+
- An Anthropic API key (Claude)
- [AgentSearch](https://github.com/brcrusoe72/agent-search) running on localhost:3939 (for web search)

### Setup

```bash
git clone https://github.com/brcrusoe72/agentic-ceo.git
cd agentic-ceo

pip install -r requirements.txt

export ANTHROPIC_API_KEY=your_key_here
```

### Run a Single Hunt

```bash
python tools/hunter.py "What are the actual deployment costs of UNS/OPC-UA at 100-machine scale?"
```

### Run the Full Daily Cycle

```bash
python tools/orchestrator.py
```

This runs: Director → Wolf hunts → Jackal scavenging → Nexus synthesis → Barrier cycle → Observer → Critic → Evolver

### Run Individual Agents

```bash
python tools/director.py              # Plan today's priorities
python tools/hunter.py "your question" # Single research hunt
python tools/jackal.py --last-hunt     # Scavenge the latest hunt
python tools/nexus.py                  # Cross-domain synthesis
python tools/observer.py               # Performance measurement
python tools/critic.py                 # Challenge assumptions
python tools/curiosity.py              # Pick something interesting to learn
python tools/essayist.py               # Write an essay from a curiosity hunt
```

---

## Architecture Docs

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — Original system design and rationale
- [ARCHITECTURE-V2.md](docs/ARCHITECTURE-V2.md) — The closed loop: outward + inward + immune cycles
- [WOLF_JACKAL.md](docs/WOLF_JACKAL.md) — Wolf & Jackal predator architecture (replaces linear Hunter)
- [DEEP_DIVE.md](docs/DEEP_DIVE.md) — Full technical blog post: "How I Built a Multi-Agent Research System"

## Example Outputs

- [Cavefish Neural Reallocation Hunt](docs/examples/cavefish-hunt.md) — A curiosity hunt that overturned a hypothesis
- [Executive Brief: April 6](docs/examples/nexus-brief-2026-04-06.md) — What the system knew after 35 days
- [Observer Daily Report](docs/examples/observer-report-2026-04-06.md) — Self-measurement: hunt grades, source reliability, kill chain stats
- [Curiosity Interests](docs/examples/curiosity-interests.json) — What the system finds interesting

---

## What I Learned

1. **Blackboard > message passing** for observable multi-agent systems. Files are debuggable. Conversations are not.
2. **The Wolf protocol's test-bite phase saves ~40% of extraction budget.** Most web content is thin. Test before committing.
3. **Jackal (lateral scavenging) finds things Wolf can't.** Focused research has blind spots. A second pass without a specific question consistently surfaces overlooked connections.
4. **The Critic is the most important agent.** Without adversarial review, knowledge bases become echo chambers. Requiring review of high-confidence frameworks prevents premature certainty.
5. **Curiosity-driven research produces disproportionately interesting outputs.** The cavefish hunt and the railroad standardization essay were both curiosity-driven. They connected to manufacturing and protocol design in ways no directed research would have found.
6. **Cost scales with knowledge, not compute.** At $0.80/day, the bottleneck is never the API bill — it's whether the system is asking the right questions.

---

## Built With

- [Claude](https://anthropic.com) (Opus for strategy/critique, Sonnet for extraction/synthesis)
- [AgentSearch](https://github.com/brcrusoe72/agent-search) (self-hosted search API)
- [OpenClaw](https://github.com/openclaw/openclaw) (agent orchestration)
- [Hugo](https://gohugo.io/) (essay publishing)
- Python, JSON files, and stubbornness

---

## License

MIT — the architecture and agent code are open. The knowledge base contents (3,700+ entries) are not included in this repo.

---

Built by [Brian Crusoe](https://github.com/brcrusoe72) · [Crusoe Advisory](https://crusoeadvisory.com)
