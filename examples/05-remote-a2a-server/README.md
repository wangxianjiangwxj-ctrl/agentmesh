# 05 — Remote A2A Server & Client (HttpProvider)

An agent connecting to a remote A2A service endpoint over HTTP.

## Scenario

This script simultaneously starts:
- A simulated remote A2A Server (HTTP JSON-RPC endpoint)
- A local Agent Client connecting via HttpProvider

Built with Python standard library only (`http.server` + `urllib` + `asyncio`) — no external SDK required.

## Prerequisites

- Python 3.10+
- No external SDK dependencies (self-contained)

## Usage

```bash
cd examples/05-remote-a2a-server
python a2a-remote-bridge.py
```

## Expected Output

```
[A2A Server] 启动在 http://localhost:18080
[Client] 发现远程 Agent: Remote AI Agent
[Client] 能力: text-generation, summarization, data-analysis
[Client] Task 已发送 (task-remote-xxx)
[Client] 轮询 #N: COMPLETED (X.Xs)
[Client] SUCCESS: 远程服务返回分析结果
[A2A Server] 停止
```

## Key Concepts Demonstrated

| Concept | Description |
|---------|-------------|
| HttpProvider | A2A communication over HTTP JSON-RPC |
| Server Lifecycle | Start/stop A2A Server programmatically |
| Client Discovery | Discover remote agent capabilities via AgentCard |
| Cross-Process | Communication between separate processes |

## Next Step

After mastering remote bridge, move to [06 — CLI Workflow](../06-cli-workflow/) to learn deployment with agentmesh CLI.
