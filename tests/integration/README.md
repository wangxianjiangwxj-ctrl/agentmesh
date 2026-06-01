# AgentMesh A2A Layer 2 Integration Tests

Integration tests for the A2A JSON-RPC 2.0 protocol over real HTTP communication.

## Test Structure

```
tests/integration/
├── __init__.py                    # Package marker
├── README.md                     # This file
├── conftest.py                   # Fixtures (server, client, task_id, facade)
├── test_protocol_flow.py         # Protocol flow tests (send, get, cancel, lifecycle, concurrent)
└── test_streaming.py             # Streaming/SSE tests (placeholder)
```

## What's Covered

| Test File | Test Group | Coverage |
|-----------|-----------|----------|
| `test_protocol_flow.py` | `TestServerStartup` | Server health, endpoint metadata, agent card, error handling, JSON-RPC compliance |
| `test_protocol_flow.py` | `TestTaskSend` | tasks.send: task ID, state, artifacts, messages, server tracking |
| `test_protocol_flow.py` | `TestTaskGet` | tasks.get: existing task, nonexistent task, state, id matching |
| `test_protocol_flow.py` | `TestTaskCancel` | tasks.cancel: existing task, nonexistent task, server state update |
| `test_protocol_flow.py` | `TestProtocolLifecycle` | Full lifecycle: send -> get -> cancel -> verify, sequential tasks, idempotent cancel |
| `test_protocol_flow.py` | `TestConcurrentTasks` | 3 concurrent sends, concurrent gets, mixed send/get/cancel operations |
| `test_protocol_flow.py` | `TestJSONRPCCompliance` | jsonrpc field, id matching, error codes, unknown method codes |
| `test_streaming.py` | `TestTaskNotify` | JSON-RPC notification stub (ack, event passthrough) |
| `test_streaming.py` | `TestSSEStreaming` | Skipped placeholder (SSE not yet implemented) |

**Total test count: ~25+ individual test cases**

## Prerequisites

- Python 3.10+
- pytest >= 7.0
- The SDK module at `sdk/a2a_provider.py` (importable from repo root)

No external dependencies beyond Python standard library. The integration server uses only `http.server` and `urllib.request`.

## Running Tests

```bash
# From the agentmesh repo root (recommended)
cd /path/to/agentmesh

# Run all integration tests
python -m pytest tests/integration/ -v

# Run a specific test file
python -m pytest tests/integration/test_protocol_flow.py -v

# Run a specific test class
python -m pytest tests/integration/test_protocol_flow.py::TestServerStartup -v

# Run with coverage
python -m pytest tests/integration/ -v --cov=sdk/a2a_provider

# Run with verbose output to see request/response details
python -m pytest tests/integration/ -v --log-cli-level=DEBUG

# Skip slow tests (concurrent tests can take a few seconds)
python -m pytest tests/integration/ -v -m "not slow"
```

## Configuration

All settings are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `A2A_TEST_HOST` | `127.0.0.1` | Server bind address |
| `A2A_TEST_PORT` | `0` (random) | Server port (0 = random available port) |
| `A2A_TEST_TIMEOUT` | `10.0` | HTTP client timeout (seconds) |

## Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `a2a_server` | function | Starts/tears down an A2A HTTP server per test |
| `a2a_client` | function | HTTP client connected to the fixture's server |
| `sample_task_id` | function | Generates a unique task ID per test |
| `a2a_facade` | function | A2AFacade with fresh MemoryProvider for in-memory reference |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  test_protocol_flow.py                                          │
│                                                                 │
│  ┌────────────┐    HTTP POST (JSON-RPC 2.0)    ┌────────────┐  │
│  │  a2a_client │ ────────────────────────────>  │ a2a_server │  │
│  │  (fixture)  │ <────────────────────────────  │ (fixture)  │  │
│  └────────────┘    HTTP 200 JSON Response      └────────────┘  │
│                                                         │       │
│                                               ┌─────────┴─────┐ │
│                                               │ A2ATaskManager │ │
│                                               │ MemoryProvider  │ │
│                                               └───────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

The server runs in-process as a background thread (daemon). Each test function gets a fresh server instance for full isolation. The server supports:

- **POST /a2a** — JSON-RPC 2.0 endpoint (tasks.send, tasks.get, tasks.cancel, tasks.notify)
- **GET /health** — Health check (returns `{"status": "ok"}`)
- **GET /a2a** — Service metadata

## CI Integration

The CI workflow (`ci-v2-final.yml`) runs the `test-sdk` job which executes:
```bash
cd sdk
python -m pytest ../tests/unit/ -v --cov=a2a_provider
```

To add integration tests to CI, update the `test-sdk` job:
```yaml
- name: SDK integration tests
  run: |
    cd sdk
    python -m pytest ../tests/integration/ -v --cov=a2a_provider --cov-report=term-missing --cov-report=xml
  env:
    PYTHONPATH: sdk
```

## Adding New Tests

1. Create a new test class (or add to existing) in `test_protocol_flow.py`
2. Use `a2a_client` fixture for HTTP communication
3. Use `a2a_server` fixture to inspect server-side state
4. Tag slow tests with `@pytest.mark.slow`
5. For SSE tests, update `test_streaming.py` when the endpoint is available

## Current Limitations

- SSE streaming is not yet implemented (tests are skipped)
- The server processes tasks synchronously (simulated 20ms delay)
- No authentication/authorization testing
- No load testing beyond 3 concurrent tasks
