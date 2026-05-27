# AgentMesh: Stop Losing Information in Multi-Agent Collaboration

**A2A lets agents talk. AgentMesh ensures nothing gets lost.**

---

## Your Multi-Agent System Is Losing Information — And You Don't Know It

You built a multi-agent system with LangGraph, CrewAI, or AutoGen.

Agent A retrieves → Agent B synthesizes → Agent C reviews.

It looks good. But have you asked:

**What key information did B drop when synthesizing A's output? Did C misinterpret A's conclusions? After 3 hops, how much of the original signal remains?**

The answer is: you don't know.

Existing multi-agent frameworks care about "agents can talk to each other." They don't care about "did they get it right?"

We ran 9 experiments to quantify the information loss in multi-agent collaboration.

---

## Experiment Setup

- **Agents**: 2-4 per chain (A→B→C→D)
- **Message types**: 5 (TaskRequest / TaskResult / QualityReview / FeedbackLoop / ContributionClaim)
- **Evaluation**: Manual review of summary, data, confidence, and fidelity at each hop
- **Sample**: 9 independent experiments (exp-001 through exp-009)

**Results confirm**: multi-agent collaboration measurably loses information.

---

## Core Findings

| Problem | Role | Rate (without AgentMesh) | Can You Detect It? |
|---------|------|--------------------------|-------------------|
| Format conflicts | A→B | 100% (exp-003/005, N=4) | Yes, but manual debugging each time |
| Critical omissions — B drops A's key data | B (synthesizer) | Control: 3 vs Template: 0 (N=6) | Not without comparing source text |
| Fact distortion — C exaggerates individual results | C (reviewer) | Naturally occurring (exp-006) | Requires dedicated review |
| Information decay — A→B fidelity drops to 0.585 | A→B→C | 15-35% loss per hop | Invisible without tracking tools |

**The most striking data point**: After 3 hops, cumulative fidelity drops to 0.414 — over half the information is lost or distorted during transfer.

---

## AgentMesh: 4 Problems, 4 Mechanisms

| Problem | Role | Mechanism | Result |
|---------|------|-----------|--------|
| What to say — A doesn't know the message format | A | Format template (5 required fields) | Conflicts 100%→0%, N=4 |
| What's missing — B omits A's key info | B (synthesizer) | Content template (structured constraints) | Omissions 3→0, N=6 |
| What's wrong — C distorts A's conclusions | C (reviewer) | Reviewer agent safety net | Detection rate 100%, N=4 |
| What to recover — D fixes A→B→C drift | D (synthesizer) | Retroactive correction | 4 hops > 3 hops, N=1 |

### 1. Format Template — "What to say" (A→B)

5 required fields: schema_version, message_id, message_type, sender, timestamp. Ensures every message has a consistent structure.

In our tests (exp-003, exp-005): 100% conflict rate without templates → 0% with templates.

### 2. Content Template — "What's missing" (B→C)

Structured constraints prevent B from dropping A's critical fields (summary, data, confidence, fidelity).

In our tests (exp-005): Control group B missed 3 critical pieces of information. Template-guided group: 0 omissions.

### 3. Reviewer Safety Net — "What's wrong" (C→D)

An independent reviewer agent (C) checks for reasoning errors before passing results to D.

In our tests (exp-008, N=4: overgeneralization, false causality, omitted evidence, subjective claims), the reviewer caught all 4 error types.

### 4. Retroactive Correction — "What to recover" (D output)

A synthesizer agent (D) traces A→B→C output, identifies accumulated drift, and fixes it.

In our tests (exp-009): 4-hop chains (A→B→C→D) proved more robust than 3-hop chains — D recovered issues C had missed.

---

## 5-Minute Quick Start

```bash
pip install agentmesh-sdk
```

```python
from agentmesh_sdk import CollaborationFlow

flow = CollaborationFlow("AI Agent Security Survey", use_signing=False)
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

# A retrieves → sends to B (with fidelity annotation)
flow.step_retrieval("scout-alpha", "forge-beta",
    summary="Found 5 AI security papers",
    data={"sources": 5},
    confidence=0.85, fidelity=0.9)

# B synthesizes → coordinator (with fidelity annotation)
flow.step_integration("forge-beta", "coordinator",
    summary="Synthesized: 5 sources across 4 research directions",
    data={"key_findings": 4, "gaps": 2},
    confidence=0.78, fidelity=0.65)

report = flow.full_report()
print(f"Conflict rate: {report['validation']['conflict_rate']}%")
print(f"Fidelity: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"Contributions: {report['allocation']['shares']}")
```

Output:

```
Conflict rate: 0.0%
Fidelity: 0.585
Contributions: {'scout-alpha': 0.5095, 'forge-beta': 0.4905}
```

**Aha Moment**: After just 2 hops, cumulative fidelity drops to 0.585 — over 40% of information lost. Without AgentMesh, this decay is invisible.

---

## How It Relates to A2A

A2A (Agent-to-Agent Protocol) enables agents built on different frameworks to communicate.

AgentMesh adds the layer that A2A leaves out: fidelity tracking and contribution allocation.

We built an A2A adapter that passes fidelity and confidence metadata through the A2A protocol. This adapter has been verified end-to-end via HTTP JSON-RPC — any A2A-compatible server can exchange messages with AgentMesh agents while preserving fidelity data.

---

## Links

- **GitHub**: [github.com/wangxianjiangwxj-ctrl/agentmesh](https://github.com/wangxianjiangwxj-ctrl/agentmesh)
- **Documentation**: [wangxianjiangwxj-ctrl.github.io/agentmesh](https://wangxianjiangwxj-ctrl.github.io/agentmesh/)
- **Web Demo**: [Fidelity Visualization](https://wangxianjiangwxj-ctrl.github.io/agentmesh/demo/fidelity-demo.html)
- **Install**: `pip install agentmesh-sdk` (PyPI pending, or `pip install git+https://github.com/wangxianjiangwxj-ctrl/agentmesh.git`)

---

**AgentMesh — A2A lets agents talk. AgentMesh ensures nothing gets lost and contributions are quantified.**
