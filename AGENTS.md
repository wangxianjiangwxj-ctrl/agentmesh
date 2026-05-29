# AgentMesh — Agent Developer Guide

This guide shows how to build agents that speak A2A with fidelity tracking.

## Overview

AgentMesh turns any agent into an A2A-compatible node with three primitives:

| Primitive | What it does |
|-----------|-------------|
| `A2AAdapter` | Register agent capabilities + send/receive A2A messages |
| `FidelityTracker` | Track information preservation across hops |
| `ContributionAllocator` | Quantify each agent's contribution to the final output |

## Quick Integration (Python)

### 1. Create an agent node

```python
from a2a_adapter import A2AAdapter, AgentCapability

agent = A2AAdapter(
    agent_name="analyst",
    capabilities=[
        AgentCapability(name="data_analysis", description="Analyze structured data"),
    ],
    fidelity_tracker=True,    # track info loss per hop
    contribution_tracker=True, # track contribution share
)
```

### 2. Handle incoming tasks

```python
@agent.on_task
async def handle_task(task):
    # task.payload contains the structured message
    # task.fidelity has the running fidelity score
    result = await your_logic(task.payload)
    return result
```

### 3. Send tasks to other agents

```python
response = await agent.send_task(
    target_agent="reviewer",
    payload={"query": "Analyze dataset A"},
    parent_task_id=current_task.id,  # links fidelity chain
)
```

### 4. Read fidelity + contribution reports

```python
run_report = agent.get_run_report(task_id=current_task.id)
print(f"Overall fidelity: {run_report.fidelity_score}")    # 0.0 - 1.0
print(f"Contributions: {run_report.contributions}")        # {"analyst": 0.6, "reviewer": 0.4}
```

## Framework Integrations

### LangGraph

```python
from langgraph.graph import StateGraph
from a2a_provider import AgentMeshProvider

provider = AgentMeshProvider()

# AgentMesh nodes wrap LangGraph nodes transparently
graph = StateGraph(MyState)
graph.add_node("agent_1", provider.wrap(my_langgraph_node))
graph.add_node("agent_2", provider.wrap(my_langgraph_node_2))
graph.add_edge("agent_1", "agent_2")
```

### CrewAI

See [`examples/crewai-integration/`](examples/crewai-integration/) for a complete CrewAI + AgentMesh bridge.

### AutoGen / Semantic Kernel / Any A2A

Any A2A-compatible agent can speak to AgentMesh nodes using the standard A2A message format. Just point your agent's A2A endpoint to an AgentMesh adapter URL.

## Fidelity Tracking in Depth

Fidelity = how much information is preserved when a message passes through an agent.

```python
from a2a_adapter import FidelityTracker

tracker = FidelityTracker()

# After each hop:
fidelity = tracker.compute_fidelity(
    original_payload=task.payload,     # what was sent to the agent
    produced_payload=agent_response,   # what the agent produced
    methodology="semantic_overlap",    # semantic, keyword, or exact
)
print(f"Agent preserved {fidelity:.1%} of information")
```

The cumulative fidelity across N hops is the product of each hop's fidelity:

```
cumulative = fidelity_1 × fidelity_2 × ... × fidelity_N
```

## Contribution Allocation

```python
from a2a_adapter import ContributionAllocator

allocator = ContributionAllocator()
report = allocator.allocate(
    task_history=run_history,  # full task trace
    method="shapley",          # Shapley value, equal, or proportional
)
for agent, share in report.contributions.items():
    print(f"{agent}: {share:.0%}")
```

## CLI Tools

```bash
# Start an AgentMesh adapter server
agentmesh serve --port 8000 --agents analyst:8001,reviewer:8002

# Connect to a running adapter and inspect fidelity
agentmesh connect localhost:8000
> fidelity: 0.87
> contributions: {"analyst": 0.52, "reviewer": 0.35, "summarizer": 0.13}
```

## Full Examples

| Example | What it demonstrates |
|---------|---------------------|
| [`04_fidelity_tracking.py`](examples/04_fidelity_tracking/) | Basic fidelity measurement |
| [`05_multi_agent_pipeline.py`](examples/05_multi_agent_pipeline/) | 3-agent pipeline with contribution tracking |
| [`06_custom_protocol.py`](examples/06_custom_protocol/) | Custom A2A message schema |
| [`a2a-bridge/`](examples/a2a-bridge/) | HTTP & memory-based A2A bridges |
| [`crewai-integration/`](examples/crewai-integration/) | Full CrewAI + AgentMesh example |

## Need Help?

- [Full Documentation](https://wangxianjiangwxj-ctrl.github.io/agentmesh/)
- [GitHub Issues](https://github.com/wangxianjiangwxj-ctrl/agentmesh/issues)
- [Quick Start](README.md#quick-start)
