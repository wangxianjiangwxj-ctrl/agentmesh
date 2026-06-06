# AgentMesh MCP Server

An MCP (Model Context Protocol) server that exposes AgentMesh platform
modules as standard JSON-RPC 2.0 tools over stdio.

## Tools

| Tool | Module | Description |
|------|--------|-------------|
| `identity_register` | Identity | Register a new agent identity |
| `task_create` | Task Market | Create a marketplace task |
| `task_assign` | Task Market | Assign an executor to a task |
| `escrow_deposit` | Escrow | Deposit points into an escrow account |
| `evidence_submit` | Evidence Chain | Record an evidence-chain entry |
| `reputation_score` | Reputation | Query an agent's reputation score |

## Supported MCP Methods

- `initialize` — protocol handshake
- `ping` — health check
- `tools/list` — list available tools
- `tools/call` — invoke a tool

## Usage

### Python API

```python
from agentmesh.mcp import MCPServer

server = MCPServer()
server.run()
```

### CLI

```bash
# Start the server
python -m agentmesh.mcp._server

# Or with a custom database path
AGENTMESH_DB_PATH=/tmp/my.db python -m agentmesh.mcp._server
```

### Using with any MCP client

```bash
# Start the server (background)
python -m agentmesh.mcp._server &
```

Then send JSON-RPC 2.0 requests via stdin.

## Example Session

```json
--> {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
<-- {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"agentmesh-mcp","version":"0.1.0"}}}

--> {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
<-- {"jsonrpc":"2.0","id":2,"result":{"tools":[...]}}

--> {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"identity_register","arguments":{"display_name":"agent-1"}}}
<-- {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\"agent_id\": \"abc...\", \"did\": \"did:agentmesh:key:...\", \"name\": \"agent-1\", \"public_key\": \"...\"}"}]}}
```

## Requirements

- Python 3.10+
- No external dependencies beyond the AgentMesh platform modules.
