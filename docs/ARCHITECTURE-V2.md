# Agentic CEO — V2 Architecture: The Closed Loop

_Designed 2026-03-05. The system that watches the world and watches itself._

## The Loop

```
                    ┌─────────────────────────────────────┐
                    │           GOAL LAYER                 │
                    │  (Human sets direction, not tasks)   │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │        OUTWARD CYCLE                 │
                    │                                      │
                    │  Director ──→ Hunter ──→ Nexus       │
                    │                            │         │
                    │              Builder ◄─────┘         │
                    │                │                     │
                    │     Dissolve ◄─┤                     │
                    │     Equalizer◄─┤                     │
                    │     Bridge   ◄─┘                     │
                    │                                      │
                    │  OUTPUT: knowledge, frameworks,      │
                    │  tools, guides, intelligence         │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │        INWARD CYCLE                  │
                    │                                      │
                    │  Observer ──→ Critic ──→ Evolver     │
                    │     │                      │         │
                    │     │    ┌──────────────────┘        │
                    │     │    │                            │
                    │     ▼    ▼                            │
                    │  SYSTEM CONFIG / PROMPTS / WEIGHTS    │
                    │  (rewrites search strategies,        │
                    │   tunes thresholds, adjusts budget   │
                    │   allocation, updates kill chain)     │
                    │                                      │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │        IMMUNE SYSTEM                  │
                    │                                      │
                    │  Sentinel — is anything broken?       │
                    │  Healer   — auto-fix what's broken   │
                    │  Auditor  — is anything drifting?     │
                    │  Costkeeper — are we burning money?   │
                    │                                      │
                    │  OUTPUT: health status, auto-repairs, │
                    │  cost alerts, drift warnings          │
                    └──────────────┬──────────────────────┘
                                   │
                              (feeds back into
                               next Outward Cycle)
```

## Agents — Complete Registry

### Outward Cycle (World-Facing)

| Agent | Role | Input | Output | Model |
|-------|------|-------|--------|-------|
| **Director** | Strategic planning — what should we learn next? | Knowledge gaps, Critic feedback, human goals | Mission priorities, hunt questions | Opus |
| **Hunter** | Recursive research — chase understanding | Questions from Director | Raw knowledge, frameworks, thinking logs | Sonnet (extraction) |
| **Nexus** | Pattern detection — what connects? | All frameworks in knowledge base | Connections, emerging patterns, recommendations, syntheses | Sonnet |
| **Builder** | Tool creation — close the sense→act gap | Nexus recommendations | Working tools, adapters | Sonnet |
| **Dissolve** | Strip complexity theater | Knowledge base entries | Plain Language Action Guides | Sonnet |
| **Equalizer** | Democratize hoarded knowledge | Knowledge base entries | Benchmark Reports | Sonnet |
| **Bridge** | Close participation gaps | Knowledge base entries | Step-by-step Bridge Guides | Sonnet |

### Inward Cycle (Self-Facing)

| Agent | Role | Input | Output | Model |
|-------|------|-------|--------|-------|
| **Observer** | Watch everything, measure everything | Hunt logs, Nexus output, cost data, kill chain stats | Performance metrics, signal-to-noise ratios, efficiency scores | Haiku |
| **Critic** | Challenge the Observer's findings | Observer metrics + system state | Critiques, blind spot alerts, bias warnings, improvement hypotheses | Opus |
| **Evolver** | Implement changes based on Critic output | Critic recommendations + system config | Modified prompts, thresholds, strategies, search queries | Sonnet |

### Immune System (Health-Facing)

| Agent | Role | Input | Output | Model |
|-------|------|-------|--------|-------|
| **Sentinel** | Detect failures and degradation | Process logs, API responses, kill chain results | Alerts, failure classifications | Haiku |
| **Healer** | Auto-fix detected issues | Sentinel alerts + system state | Patches, restarts, fallback activations | Sonnet |
| **Auditor** | Detect drift — is the system changing in ways nobody intended? | Knowledge base over time, config history, Observer metrics | Drift reports, alignment warnings | Opus |
| **Costkeeper** | Track and optimize spend | API call logs, token counts, per-agent costs | Cost reports, budget recommendations, ROI per hunt | Haiku |

## Data Flow — What Connects To What

### Files (Shared State)

```
tools/ceo/
├── knowledge/               # The knowledge base (outward cycle writes, everyone reads)
│   ├── {domain}/            # Frameworks by domain
│   ├── dissolved/           # Plain language guides
│   ├── equalized/           # Benchmark reports
│   └── bridged/             # Bridge guides
│
├── state/
│   ├── hunts/               # Hunt logs, thinking, synthesis
│   ├── nexus/               # Connections, briefs, recommendations
│   ├── builder/             # Specs, builds, shipped tools
│   ├── pipeline/            # Run logs, summaries
│   ├── observer/            # ← NEW: performance metrics, signal/noise scores
│   │   ├── hunt-scores.json        # Per-hunt efficiency (frameworks/dollar, signal ratio)
│   │   ├── source-quality.json     # Per-domain source reliability scores
│   │   ├── kill-chain-stats.json   # Which strategies succeed/fail by domain
│   │   ├── framework-utility.json  # Which frameworks led to actions vs sat unused
│   │   └── daily-report.md         # Daily self-observation summary
│   ├── critic/              # ← NEW: critiques, bias alerts, improvement hypotheses
│   │   ├── critiques.json          # Structured critiques with evidence
│   │   ├── blind-spots.md          # What we're NOT seeing
│   │   └── hypotheses.json         # "If we change X, Y should improve"
│   ├── evolver/             # ← NEW: change log, before/after comparisons
│   │   ├── changes.json            # What was changed, why, by which Critic recommendation
│   │   ├── experiments.json        # A/B tests: old strategy vs new
│   │   └── rollbacks.json          # Changes that made things worse → reverted
│   ├── immune/              # ← NEW: health, cost, drift
│   │   ├── health.json             # Current system health status
│   │   ├── incidents.json          # Failure log with root cause + resolution
│   │   ├── costs.json              # Per-agent, per-hunt, per-day costs
│   │   ├── drift-report.md         # Is the system changing in unintended ways?
│   │   └── budget.json             # Current budget allocation + recommendations
│   ├── missions.json
│   ├── obstacles.json
│   └── tool-suggestions.json
│
├── config/                  # ← NEW: system configuration (Evolver writes here)
│   ├── hunt-config.json            # Budget, depth, source limits, relevance thresholds
│   ├── search-config.json          # Query strategies, domain weights, blocked domains
│   ├── kill-chain-config.json      # Strategy order, timeouts, retry policies
│   ├── model-config.json           # Which model for which agent, token limits
│   └── budget-config.json          # Daily/weekly budget caps, per-agent allocation
│
├── constitution.yaml        # Moral code — Auditor checks drift against this
└── tools/                   # Agent scripts
```

### Agent Communication Pattern

**Blackboard + Event Log.** No direct agent-to-agent calls. Every agent:
1. Reads shared state (knowledge/, state/)
2. Does its work
3. Writes results to shared state
4. Appends to event log: `state/events.jsonl`

The event log is how agents know what happened:
```jsonl
{"ts": "2026-03-05T15:00:00Z", "agent": "hunter", "event": "hunt_complete", "hunt_id": "e8165180", "sources": 15, "frameworks": 64, "cost": 0.31}
{"ts": "2026-03-05T15:05:00Z", "agent": "observer", "event": "scored_hunt", "hunt_id": "e8165180", "signal_ratio": 0.73, "cost_efficiency": 206}
{"ts": "2026-03-05T15:06:00Z", "agent": "critic", "event": "critique", "target": "hunter", "finding": "youtube_bias", "severity": "medium"}
{"ts": "2026-03-05T15:10:00Z", "agent": "evolver", "event": "config_change", "key": "search-config.youtube_weight", "old": 1.0, "new": 0.7, "reason": "critic:youtube_bias"}
```

## Orchestration — The Daily Cycle

### Full Cycle (runs daily via pipeline.py + heartbeat)

```
Phase 1: OUTWARD (30-45 min)
  1. Director reviews knowledge gaps + Critic feedback → sets today's mission
  2. Hunter runs on mission question (kill chain, save incrementally)
  3. Nexus analyzes all knowledge including new hunt results
  4. Builder checks Nexus recommendations → builds tools if needed
  5. Barrier Cycle: Dissolve → Equalizer → Bridge

Phase 2: INWARD (5-10 min)
  6. Observer scores the outward cycle (signal/noise, cost efficiency, source quality)
  7. Critic reviews Observer's findings + checks for bias/drift
  8. Evolver implements approved changes to config

Phase 3: IMMUNE (2-5 min)
  9. Sentinel checks all systems health
  10. Costkeeper tallies spend, projects budget
  11. Auditor checks for drift against constitution (weekly, not daily)
  12. Healer patches anything broken

Phase 4: DELIVER (1 min)
  13. Generate summary blurb for human
  14. Save state for tomorrow
```

### Cost Budget (Target: <$1/day)

| Agent | Calls/Day | Model | Est. Cost |
|-------|-----------|-------|-----------|
| Director | 1 | Opus | $0.08 |
| Hunter | 15-20 | Sonnet | $0.30 |
| Nexus | 1 | Sonnet | $0.05 |
| Builder | 0-1 | Sonnet | $0.03 |
| Barriers | 3 | Sonnet | $0.10 |
| Observer | 1 | Haiku | $0.01 |
| Critic | 1 | Opus | $0.08 |
| Evolver | 0-1 | Sonnet | $0.03 |
| Sentinel | 1 | Haiku | $0.01 |
| Costkeeper | 1 | Haiku | $0.01 |
| Auditor | 0.14 (weekly) | Opus | $0.01 |
| Summary | 1 | Sonnet | $0.02 |
| **Total** | | | **~$0.73/day** |

## Principles

1. **Blackboard pattern** — no agent calls another directly. Shared files are the communication layer.
2. **Every agent is optional** — the system degrades gracefully. Skip Critic? System still works, just doesn't self-improve. Skip Sentinel? Still works, just won't auto-heal.
3. **Human sets goals, not tasks** — "Learn about agent marketplaces" not "Search Google for agent marketplace VC funding"
4. **Constitution is immutable by agents** — only human can change it. Auditor checks drift.
5. **Evolver changes are reversible** — every config change is logged with before/after. Rollback if metrics worsen.
6. **Cost is a first-class constraint** — Costkeeper can veto expensive hunts. Budget is finite.
7. **Inward cycle runs AFTER outward** — observe what just happened, not what might happen.
8. **Event log is append-only** — the single source of truth for what happened and when.

## Build Order

| Phase | What | Effort | Depends On |
|-------|------|--------|------------|
| **0** | Config files (hunt-config, search-config, etc.) | 1 hour | Nothing |
| **1** | Event log (events.jsonl + append helper) | 1 hour | Nothing |
| **2** | Observer agent | 3-4 hours | Event log |
| **3** | Critic agent (rewire existing) | 2-3 hours | Observer |
| **4** | Evolver agent (rewire existing evolve.py) | 3-4 hours | Critic + Config |
| **5** | Sentinel + Healer | 2-3 hours | Event log |
| **6** | Costkeeper | 2 hours | Event log |
| **7** | Auditor | 2-3 hours | Constitution + Observer |
| **8** | Wire into pipeline.py (phases 1-4) | 2 hours | All above |
| **9** | Director upgrade (reads Critic feedback) | 1-2 hours | Critic |

**Total: ~20-25 hours of build time.**

## The Vision

Month 1: System observes itself, identifies inefficiencies, suggests improvements.
Month 3: System implements its own improvements, tracks results, rolls back failures.
Month 6: Human checks in weekly. System runs autonomously, improves continuously, stays aligned via constitution + Auditor.

_This is not AGI. This is a well-designed feedback loop with guardrails. The intelligence emerges from the loop, not from any single agent._
