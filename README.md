# Agentic CEO

Research orchestration scripts that plan questions, retrieve sources, extract findings,
and maintain a file-based knowledge base. This repository is a research prototype;
it does not autonomously acquire customers or establish that an idea is worth building.

## Current status — 2026-10-13

The source includes 40 Python scripts. Historical reports describe a March–April
2026 research run; its private knowledge base and billing records are not included.
Those counts and costs are historical observations, not current service guarantees.

The dependency and runtime configuration is mixed: `tools/api.py` invokes the
`openclaw agent` CLI, while `tools/director.py` still requires an Anthropic credential
at initialization. Installing Python packages and setting one API key is insufficient
to reproduce the full pipeline. `model` and `max_tokens` parameters in the shared
gateway wrapper are not forwarded to the CLI and do not enforce a spending cap.

## Safe first check

```bash
git clone https://github.com/brcrusoe72/agentic-ceo.git
cd agentic-ceo
python3 tools/orchestrator.py --status
```

This read-only status command works with the Python standard library. A fresh clone
reports an empty knowledge base. There is no `requirements.txt` in this repository.
Research scripts additionally import Requests, PyYAML, Beautiful Soup, pdfplumber,
and optional media packages; inspect the selected script before installing its dependencies.

## Pipeline and boundaries

`tools/orchestrator.py` runs Director → assigned hunts → Scout → queued Analyst
ingestion → Librarian → Critic → optional Evolve. Other scripts provide Jackal,
Nexus, Observer, essay writing, opportunity scoring, and builders; their presence
does not mean the default orchestrator runs them all.

Research execution requires a configured OpenClaw CLI, the applicable model
credentials, writable state directories, and AgentSearch where used. Several callers
still assume unauthenticated localhost search. An authenticated AgentSearch deployment
must be wired and tested before calling those research paths. A successful status
check is not a successful live research cycle.

## Goal and definition of progress

See [OPERATING_MODEL.md](OPERATING_MODEL.md). For business work, the unit of progress
is a customer-accepted deliverable with reproducible evidence. Knowledge entries,
generated specifications, opportunity scores, simulated revenue, and tool count
are not substitutes. The [constitution](constitution.yaml) supplies this guidance
to the Director; it is prompt guidance, not an enforced permissions or budget system.

## Architecture and historical examples

- [Original architecture](docs/ARCHITECTURE.md)
- [Closed-loop design](docs/ARCHITECTURE-V2.md)
- [Wolf and Jackal design](docs/WOLF_JACKAL.md)
- [Historical technical account](docs/DEEP_DIVE.md)
- [Example hunt](docs/examples/cavefish-hunt.md)
- [Example executive brief](docs/examples/nexus-brief-2026-04-06.md)

MIT. Maintained by Brian Crusoe.
