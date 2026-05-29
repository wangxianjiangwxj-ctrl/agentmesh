# 06 — CLI Serve/Connect Workflow (agentmesh CLI)

Demonstrates the full agentmesh CLI workflow: serve, connect, and message exchange.

## Scenario

Shows how to:
1. Start an A2A Server with `agentmesh serve`
2. Connect a client agent with `agentmesh connect`
3. Send tasks and poll results

## Prerequisites

- `agentmesh` CLI installed (`npm install -g @agentmesh/cli` or `pip install agentmesh`)
- If CLI is unavailable, the script runs in **simulation mode** showing expected output

## Usage

```bash
cd examples/06-cli-workflow
bash a2a-cli-serve-connect.sh
```

## Expected Output

```
[agentmesh CLI 示例] ...
Agent A 服务已启动 (port 8080)
......
示例运行结束
```

## Key Concepts Demonstrated

| Concept | Description |
|---------|-------------|
| agentmesh serve | Start an A2A Server from CLI |
| agentmesh connect | Connect a client agent to server |
| Task Management | Send, poll, and retrieve tasks |
| Error Handling | Auto-detect CLI availability, fallback to simulation |

## Notes

- The `cli/` directory at repo root contains the agentmesh CLI source code
- This example demonstrates CLI *usage*, not implementation
- Review [CLI documentation](../../cli/README.md) for full command reference
