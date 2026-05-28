# AgentMesh Examples — Progressive Learning Path

From understanding the A2A protocol to deploying with the CLI.
Each example builds on the previous one.

## Example Index

| # | Name | Type | Complexity | Run |
|---|------|------|-----------|-----|
| [01](01-two-agent-research/) | Two-Agent Research | HTML (interactive) | Basic | Browser |
| [02](02-three-agent-review/) | Three-Agent Review | HTML (interactive) | Intermediate | Browser |
| [03](03-cross-a2a-collaboration/) | Cross-A2A Collaboration | HTML (interactive) | Advanced | Browser |
| [04](04-local-bridge/) | Local A2A Bridge | Python (MemoryProvider) | Basic | Python 3.10+ |
| [05](05-remote-a2a-server/) | Remote A2A Server/Client | Python (HttpProvider) | Intermediate | Python 3.10+ |
| [06](06-cli-workflow/) | CLI Workflow | Shell (agentmesh CLI) | Advanced | CLI installed |

### Additional Examples

| File | Type | Description |
|------|------|-------------|
| [a2a-bridge-http.py](./a2a-bridge-http.py) | Python | A2A bridge over HTTP (alternative to 05) |
| [a2a-bridge-memory.py](./a2a-bridge-memory.py) | Python | A2A bridge in-memory (alternative to 04) |
| [crewai-integration.py](./crewai-integration.py) | Python | CrewAI + A2A integration example |
| [langgraph-integration.py](./langgraph-integration.py) | Python | LangGraph + A2A integration example |

### Learning Path

```
Protocol Understanding ──► SDK Development ──► CLI Deployment
     01/02/03                 04/05                 06
     (HTML Demos)           (Python SDK)        (CLI Commands)
```

### 01-03: A2A Protocol Understanding (HTML)

Interactive HTML demos showing A2A agent communication concepts.
- Open `index.html` in any browser — no setup required
- Visual representation of messages, tasks, and agent interactions

### 04-05: SDK Development (Python)

Self-contained Python scripts using AgentMesh SDK v0.3 A2A patterns.

| Example | Provider | Network | Dependencies |
|---------|----------|---------|-------------|
| 04 — Local Bridge | MemoryProvider | None | Python 3.10+ (no SDK) |
| 05 — Remote Server | HttpProvider | localhost | Python 3.10+ (no SDK) |

### 06: CLI Deployment (Shell)

End-to-end CLI workflow: `serve` → `connect` → message exchange.
- Auto-detects `agentmesh` CLI; falls back to simulation mode
- Covers real-world deployment scenario

---

## Quick Start

### View HTML Demos (01-03)

```bash
# Open any index.html in your browser
open examples/01-two-agent-research/index.html
```

### Run Python Examples (04-05)

```bash
# Local in-process bridge
cd examples/04-local-bridge
python a2a-bridge-local.py

# Remote server/client
cd examples/05-remote-a2a-server
python a2a-remote-bridge.py
```

### Run CLI Example (06)

```bash
cd examples/06-cli-workflow
bash a2a-cli-serve-connect.sh
```

---

## Repository Structure

```
examples/
├── README.md                        # This file
├── 01-two-agent-research/           # HTML: Two-Agent Research Demo
├── 02-three-agent-review/           # HTML: Three-Agent Review Demo
├── 03-cross-a2a-collaboration/      # HTML: Cross-A2A Collaboration Demo
├── 04-local-bridge/                 # Python: Local MemoryProvider Bridge
├── 05-remote-a2a-server/            # Python: Remote HttpProvider Bridge
├── 06-cli-workflow/                 # Shell: CLI serve/connect Workflow
├── langgraph-integration.py         # LangGraph integration example
└── output/                          # Output directory (for 06)
```

---

## Notes

- Examples 01-03 contributed by team (HTML demos)
- Examples 04-06 contributed by team (SDK + CLI demos)
- `cli/` at repo root contains the agentmesh CLI source code (distinct from usage examples here)
- All Python examples use Python 3.10+ syntax
- Shell example auto-detects CLI availability and falls back gracefully
