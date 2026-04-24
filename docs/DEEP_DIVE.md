# How I Built a Multi-Agent Research System That Ran Autonomously for 35 Days

*3,704 knowledge entries. 173 research hunts. 68 domains. ~$25 total. Here's how it works and what I learned.*

---

I wanted a system that could research things while I slept.

Not a chatbot I had to prompt. Not a RAG pipeline I had to feed. A system that wakes up, decides what to learn, goes and learns it, challenges its own conclusions, measures its own performance, and improves itself — then does it again tomorrow.

So I built one. It ran autonomously from March 3 to April 6, 2026. This is a technical walkthrough of the architecture, the failures, and the things I didn't expect.

---

## The Problem With Single-Agent Research

The obvious approach: give Claude a research question, let it search the web, read the results, and write a synthesis. I tried this first. It works for simple questions. It falls apart for anything that requires depth.

The context window fills up. The agent can't hold 500 articles and reason about them simultaneously. It can't discover new sources while analyzing old ones. It has one perspective and one blind spot. And it produces exactly what you'd expect — competent, surface-level, unsurprising answers.

The second approach — a pipeline (search → extract → store → query) — is better. Each stage is focused. But it's linear. It doesn't decide what to learn next. It doesn't notice contradictions. It doesn't challenge itself. And it never produces anything surprising, because surprise requires connecting things that weren't supposed to be connected.

What I wanted was something closer to how a research team works: different people with different skills, reading different things, arguing about what it means, and collectively arriving at understanding that none of them would reach alone.

---

## The Architecture: Blackboard + Specialists

I chose a blackboard architecture — all agents communicate through a shared file-based knowledge base rather than talking to each other directly. This was the single most important design decision.

```
                    ┌─────────────┐
                    │  DIRECTOR   │  Plans what to learn
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ KNOWLEDGE   │  Shared state (files)
                    │    BASE     │  All agents read/write
                    └──┬──┬──┬──┬┘
                       │  │  │  │
            ┌──────────┘  │  │  └──────────┐
            │             │  │             │
         Wolf         Jackal          Nexus
        (hunts)     (scavenges)    (connects)
                                       │
                                    Critic
                                  (challenges)
                                       │
                              Observer → Evolver
                            (measures)  (improves)
```

**Why files and not a database?** Three reasons:

1. **Observability.** I can open any file and see what the system is thinking. JSON entries are human-readable. Agent reports are markdown. I watched the system's worldview evolve in real-time by reading files.

2. **Debuggability.** When a hunt produces bad output, I can read the thinking log, the sources, the extraction, and the synthesis as separate files. Try debugging a conversation log in a message-passing system.

3. **Zero infrastructure.** No Postgres, no Redis, no Docker (for the knowledge base). Files on disk. Git for version history. The system ran on my laptop.

The tradeoff is that file I/O is slower than a database and doesn't support concurrent writes well. At the scale I was running (dozens of entries per day, not thousands), this never mattered.

---

## The Agents

### The Director — What Should We Learn Next?

The Director doesn't search the web or read articles. It thinks about what to learn. Every morning, it:

1. Reads the constitution (a YAML file defining the system's values and boundaries)
2. Reviews knowledge gaps identified by the Librarian
3. Reads yesterday's research results
4. Writes today's missions — specific questions for the Wolf to hunt

The key insight: **strategy and execution are different cognitive modes.** When I had a single agent doing both, it produced busy work — researching whatever was easy rather than what was important. Separating the "what should we learn?" question from the "go learn it" execution immediately improved research quality.

The Director runs on Opus. This is the one place where deep reasoning matters more than speed.

### The Wolf — A Predator, Not a Vacuum

The Wolf is the core research engine. It replaced an earlier agent called "Hunter" that had a simple approach: search, fetch everything, extract frameworks. The Hunter worked but was wasteful. It processed every source equally, whether the source had real insight or was SEO filler.

The Wolf protocol has 5 phases with explicit budget allocation:

**Phase 0: Territory (5%)** — Before searching, check what we already know. Build a map of gaps. This prevents re-researching things we've already covered.

**Phase 1: Stalk (15%)** — Broad search. Score each result against the gap map. Select 5-7 targets. **Ignore everything else.** Not "queue for later" — ignore. This is where most research systems fail. They try to process everything. The Wolf deliberately leaves meat on the table.

**Phase 2: Test Bite (20%)** — Fetch the first 1,000 characters of each target. Quick assessment: is there actual substance here, or is this surface-level? **If no substance, abandon immediately.** Walk away. Zero sunk cost.

This phase saved roughly 40% of the extraction budget over 173 hunts. Most web content is thin. A 1,000-character test is enough to tell.

**Phase 3: Kill (50%)** — Full extraction, but with a value hierarchy:
- 🫀 **Organs** — Contradictions and surprises (highest value)
- 🩸 **Meat** — New information that fills a specific gap
- 🦴 **Bones** — Confirmations of what we already know (lowest value)

This hierarchy changed how the system learned. Instead of treating all information equally, it actively hunted for things that challenged existing understanding. Over 35 days, the "organs" — the contradictions — were consistently the most valuable outputs.

**Phase 4: Feed (10%)** — Synthesis. Not "what did we find" but "what changed in our understanding." Which gaps closed? Which new gaps opened? Where should the next hunt go?

**Real numbers from 173 hunts:**
- Average cost: $0.13–$0.30 per hunt
- Kill rate: 40-60% (targets committed / targets stalked)
- Best source: arxiv.org — 96.6% extraction success, 5.67 frameworks per fetch
- Worst sources: medium.com and reddit.com — 0% extraction success across all attempts. Both were eventually blacklisted.

### The Jackal — Finding What the Wolf Missed

This was the agent I almost didn't build. The Wolf hunts with a specific question. That focus is its strength — and its blind spot. It reads sources looking for answers to its question and ignores everything else in the text.

The Jackal runs after the Wolf. It never searches the web. It re-reads the same sources the Wolf already processed, but with no specific question. Just: "What else is here that nobody asked about?"

It does three things:

1. **Carcass picking** — Re-examine Wolf's sources for overlooked insights. What throwaway lines contain hidden value? What assumptions does the author make that deserve questioning?

2. **Cross-kill connections** — The Wolf processes sources one at a time. The Jackal sees all of today's kills at once and finds threads between them that aren't obvious.

3. **Knowledge base archaeology** — Connect today's findings to things from weeks ago. This is Jackal's unique power. The Wolf is present-focused. The Jackal has long memory.

In practice, the Jackal consistently found things the Wolf missed. A hunt about manufacturing lock-in produced Wolf findings about data portability — but the Jackal noticed that the same sources contained implicit evidence about vendor pricing strategies that nobody had asked about. That became a separate line of investigation.

### The Critic — The Most Important Agent

I almost cut the Critic to save costs. It's the most expensive agent per run (uses Opus for adversarial reasoning). I'm glad I didn't.

Without the Critic, the knowledge base becomes an echo chamber. The system reads sources that agree with each other, extracts frameworks that confirm each other, and builds confidence in conclusions that might be wrong.

The Critic's rules:
- Any framework rated above 0.9 confidence must be reviewed
- When all sources on a topic share the same bias, flag it
- Demand empirical evidence, not thought-leader opinion
- "I don't know" is a valid output

Over 35 days, the Critic downgraded the confidence of 23% of high-rated frameworks. In several cases, it identified that the system's "knowledge" on a topic was based entirely on one author's opinion repeated across multiple sources — not independent evidence. Without the Critic, those would have been treated as established facts.

### The Observer + Evolver — The Self-Improvement Loop

The Observer measures everything:
- Hunt grades (A through F) based on frameworks per dollar, signal-to-noise ratio, and source quality
- Source reliability tracking (which domains consistently produce good extractions)
- Kill chain effectiveness (which extraction strategies work on which sites)
- Cost per insight across all agents

The Evolver reads the Observer's reports and the Critic's recommendations, then adjusts the system: search strategies, extraction thresholds, budget allocation, source blacklists.

This is the closed loop that makes the system improve over time. By week 3, the Wolf was spending less time on low-yield sources and more on high-yield ones — not because I tuned it, but because the Observer measured source quality and the Evolver adjusted the configuration.

---

## The Curiosity Engine

The system doesn't just research what it's told to. The Director maintains a list of "fascinations" — things the system finds genuinely interesting:

- Complex adaptive systems and emergence
- History of failed predictions by experts
- Biomimicry in engineering
- How blind cavefish repurpose visual neural tissue
- What medieval guild structures teach about platform economics
- The parallels between immune systems and cybersecurity

Twice a week, the Director picks a curiosity topic, runs a full Wolf hunt, and the Essayist agent writes a long-form essay from the results. These are published at [brcrusoe72.github.io/directors-notes](https://brcrusoe72.github.io/directors-notes).

The curiosity hunts produced the most interesting outputs of the entire 35-day run. A hunt about cavefish neural adaptation overturned the standard "repurposing" narrative — the optic tectum doesn't get colonized by other modalities; it retains its excitatory architecture while selectively losing inhibitory circuits. The pleiotropic package hypothesis (eye loss and tectum remodeling as a single genetic module) turned out to be dead — hybrid crosses prove they segregate independently.

A hunt about railroad gauge standardization became an essay about protocol design. A hunt about wolf intervals in musical tuning became an essay about why all systems require deliberate compromise.

None of these connections would have emerged from directed research. They came from letting the system follow its curiosity and then connecting what it found to existing knowledge.

---

## What I Got Wrong

### 1. The "Process Everything" Instinct

The first version (Hunter v1) tried to extract value from every source it found. This was wrong. Most web content is filler. The Wolf's test-bite-and-abandon protocol — where 40-60% of targets are abandoned after a 1,000-character test — produces better results at lower cost than exhaustive processing.

The lesson: **selectivity is a feature, not a limitation.** A system that walks away from thin sources is smarter than one that processes them thoroughly.

### 2. Underestimating Lateral Discovery

I originally built the system without the Jackal. The Wolf did focused research, and that was fine. But when I added the Jackal — an agent whose entire job is to look sideways at what the Wolf already found — the quality of cross-domain connections jumped noticeably.

The lesson: **focused research has structural blind spots.** You need a second pass with no specific question.

### 3. Source Quality Varies 100x

Not all sources are equal, and the system learned this the hard way:

| Source | Success Rate | Frameworks/Fetch |
|--------|-------------|-----------------|
| arxiv.org | 96.6% | 5.67 |
| youtube.com | 93.3% | 5.41 |
| github.com | 90.9% | 5.36 |
| medium.com | 0% | 0 |
| reddit.com | 0% | 0 |

Medium and Reddit produced zero usable extractions across all attempts. Anti-scraping, paywalls, or just low information density — the result was the same. The Observer caught this and the Evolver blacklisted them. But they should have been blacklisted by day 3, not day 15. I need a faster source feedback loop.

### 4. The Cost of Confirmation

Early hunts had high framework counts but low novelty. The system was "learning" things it already knew in slightly different words. The organ/meat/bone value hierarchy fixed this — by explicitly deprioritizing confirmatory information and rewarding contradictions, the system shifted from accumulating to discovering.

### 5. The Constitution Matters More Than You Think

I wrote the constitution (values, boundaries, epistemic rules) as a nice-to-have. It turned out to be essential. Without the "never suppress contradicting evidence" rule, the system developed a subtle tendency to weight sources that agreed with existing frameworks higher than sources that challenged them. The Critic caught this — but only because the constitution gave it the authority to flag it.

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Days running | 35 |
| Knowledge base entries | 3,704 |
| Research hunts | 173 |
| Domains covered | 68 |
| Total cost | ~$25-30 |
| Cost per day | ~$0.80 |
| Cost per framework | ~$0.007 |
| Agent types | 7 outward + 3 inward + immune |
| Python files | 40 |
| Lines of Python | ~6,000 |
| Lines of architecture docs | ~2,000 |

---

## What I'd Do Differently

**Better source feedback loops.** The Observer should flag zero-yield sources after 3 attempts, not wait for a weekly review.

**Cheaper Critic runs.** The Critic uses Opus because adversarial reasoning is hard. But 80% of Critic runs conclude "this looks fine." A two-stage Critic — Sonnet for triage, Opus only for flagged items — would cut Critic costs by 60%.

**Structured debate between agents.** Right now, agents communicate through files. The Critic writes a critique, and the next day's Director reads it. A synchronous debate — Critic challenges a finding, Wolf defends it, Director adjudicates — would produce better conclusions. The infrastructure doesn't support this yet.

**Embeddings as an index layer.** The knowledge base is JSON files searched by the Librarian. At 3,700 entries, full-text search is fine. At 30,000 it won't be. Vector embeddings as an index over the existing file structure (not replacing it) is the obvious next step.

---

## Stack

- **Agents:** Python, calling Claude via Anthropic API (Opus for strategy/critique, Sonnet for extraction)
- **Search:** [AgentSearch](https://github.com/brcrusoe72/agent-search) (self-hosted, wraps SearXNG)
- **Knowledge base:** JSON files on disk, organized by domain
- **Orchestration:** [OpenClaw](https://github.com/openclaw/openclaw) for scheduling and sub-agent management
- **Publishing:** Hugo for essays, GitHub Pages for hosting
- **Infrastructure:** Runs on a laptop. No cloud, no Kubernetes, no Docker (except for AgentSearch).

---

## Source Code

The architecture docs, agent code, and representative examples are at [github.com/brcrusoe72/agentic-ceo](https://github.com/brcrusoe72/agentic-ceo).

The knowledge base contents (3,700+ entries) are not included — that's the research output, not the system.

---

*Built by [Brian Crusoe](https://github.com/brcrusoe72). I run manufacturing operations and build AI systems. More at [Crusoe Advisory](https://crusoeadvisory.com).*
