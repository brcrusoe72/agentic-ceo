# Executive Brief — 2026-04-06

# Executive Brief: Autonomous Research System — State of Knowledge
**April 6, 2026 | 3,645 frameworks across 68 domains | 101 hunts completed**

---

## What We Know

**1. Agent payments are vaporware with a real escape hatch.** Visa VIC, Mastercard Verifiable Intent, and Skyfire have zero production volume. No public APIs, no sandbox docs, no merchant integrations. But Hunt 089c found something useful: a minimum viable agent transaction stack is *composable today* from existing primitives — OAuth 2.0 DPoP + Biscuit token attenuation + Circle USDC programmable wallets. The protocol sequence has been sketched and the pieces fit. Nobody's built it outside hackathons, but the blockers are organizational, not technical.

**2. Manufacturing analytics platforms survive on lock-in, not value.** Tulip uses three-layer lock-in (app migration disguised as export, proprietary data models, derived-data ownership ambiguity). MachineMetrics suppresses churn through architectural lock-in. Most platforms avoid ISA-95/OPC-UA compliance because interoperability is the enemy of retention. Data portability is the gap nobody advertises — and the wedge a vendor-neutral tool exploits.

**3. The vendor-neutral data layer everyone wants doesn't have a known price tag.** Two separate hunts (0251e65e, 13534dd9) targeted UNS/OPC-UA deployment costs for mid-market manufacturers. Both hit 86% abandon rates. Nobody — not HiveMQ, not Cirrus Link, not HighByte — has published real deployment costs at 100-machine scale. The market is pre-transparent.

**4. AI in manufacturing is an organizational problem wearing a technical costume.** Across 466 manufacturing frameworks and 18 manufacturing-strategy cross-domain entries, the pattern is consistent: the blocker isn't algorithms, it's the gap between process frameworks (DMAIC, Six Sigma) and software architecture. The people who understand the floor don't build software; the people who build software don't understand the floor.

---

## What's Converging

Three independent evidence lines point to the same opportunity: **a lightweight, vendor-neutral analytics layer for small/mid manufacturers is an open lane.**

- Lock-in research confirms incumbents *depend* on data captivity (not superior analytics)
- Cost opacity for UNS/data layers means buyers can't comparison-shop — first credible price anchor wins
- The DMAIC-to-AI bridge is unmapped in practice — Six Sigma practitioners have the domain trust but no tooling that speaks their language

This is exactly where the OEE Tool sits. The $0.15/report price point, Excel-in/PDF-out simplicity, and zero-lock-in architecture aren't just features — they're the counter-positioning against every incumbent.

---

## What We Don't Know

- **Actual UNS deployment economics.** Two hunts, zero usable cost data. This is the #1 gap — if the data layer costs $500K, the OEE Tool is a standalone product; if it costs $50K, the tool could be the analytics layer that rides on top.
- **Real churn data from manufacturing SaaS.** We know lock-in exists but don't know *how well it works* — are customers actually trapped, or leaving anyway?
- **Whether the composable agent payment stack has regulatory clearance** for non-human KYC (Circle's programmable wallets may still require human identity upstream).

---

## What To Do Next

1. **Price the data layer yourself.** The hunts failed because this data isn't published. Call 3 integrators (HiveMQ partner, Cirrus Link reseller, independent SI) and ask for ballpark quotes on a 50-machine floor. First-hand pricing intelligence is worth more than 10 hunts.

2. **Write the "Data Portability Report Card" for manufacturing platforms.** The research is 83% complete. Publish it — it positions Crusoe Advisory as the vendor-neutral voice and generates inbound from manufacturers who didn't know they were locked in.

3. **Stop hunting agent payments.** The composable stack finding (Hunt 089c) is the ceiling of what open-source research can deliver. Further hunts will hit the same walls. Either build a prototype or shelve it.