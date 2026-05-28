# AgentMesh

![CI](https://img.shields.io/github/actions/workflow/status/wangxianjiangwxj-ctrl/agentmesh/ci-v2-final.yml?branch=main)
![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)

A2A lets agents talk. AgentMesh ensures nothing gets lost and contributions are quantified.

AgentMesh is an open-source fidelity tracking and contribution allocation layer for multi-agent systems. It plugs into any agent framework (LangGraph, CrewAI, AutoGen, etc.) and adds:

- **Fidelity tracking** — see how much information is lost across agent hops
- **Contribution allocation** — quantify each agent's contribution to the final result
- **A2A protocol support** — interoperate with any A2A-compatible agent
- **L1 templates** — eliminate schema conflicts with simple structured templates

## Quick Start

```bash
pip install agentmesh-sdk
```

See [documentation](https://wangxianjiangwxj-ctrl.github.io/agentmesh/) for full guide.

## Key Findings (9 experiments)

| Metric | Result |
|--------|--------|
| Schema conflict rate (unguided) | 100% |
| Schema conflict rate (with L1 template) | 0% |
| Severe omissions (control vs template) | 3 vs 0 |
| Typical reasoning error detection | 100% (4/4) |
| Information loss in 3 hops | 53.2% |
