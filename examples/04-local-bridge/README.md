# 04 — Local Agent A2A Bridge (MemoryProvider)

Two agents communicating in-process via memory-based A2A protocol.

## Scenario

- **Scout Agent**: collects simulated data
- **Analyst Agent**: receives data and generates analysis report
- Communication happens entirely in-memory — no network required

## Prerequisites

- Python 3.10+
- No external SDK dependencies (self-contained)

## Usage

```bash
cd examples/04-local-bridge
python a2a-bridge-local.py
```

## Expected Output

```
[Scout Agent] 已注册 AgentCard
[Analyst Agent] 已注册 AgentCard
发送任务: scout -> analyst
... (polling progress)
任务完成! Task ID: task-001
状态: COMPLETED
分析报告: ...
```

## Key Concepts Demonstrated

| Concept | Description |
|---------|-------------|
| MemoryProvider | In-process A2A Server simulation |
| A2AFacade | A2A bridge facade for message conversion and task lifecycle |
| AgentCard | Agent capability description (name, skills, abilities) |
| Task Polling | Automatic task status polling until COMPLETED |

## Next Step

After mastering local bridge, move to [05 — Remote A2A Server](../05-remote-a2a-server/) to learn cross-process communication.
