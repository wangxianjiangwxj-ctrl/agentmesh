# AgentMesh Test Suite

## Structure

```
tests/
├── README.md                # This file
├── unit/                    # Layer 1: Unit tests (fast, isolated)
│   ├── test_memory_provider.py   # MemoryProvider, TaskManager, Facade, A2AResult
│   └── test_protocol.py          # Message format, error handling, state machine
├── integration/             # Layer 2: Integration tests (needs server)
│   └── (planned)
└── e2e/                     # Layer 3: End-to-end tests (needs CLI)
    └── (planned)
```

## Running Tests

```bash
# From repo root
pytest tests/unit/ -v              # Layer 1: Unit tests (<5s, no deps)
pytest tests/integration/ -v       # Layer 2: Integration tests (~30s, needs server)
pytest tests/e2e/ -v               # Layer 3: E2E tests (~60s, needs CLI installed)
pytest tests/ -v                   # All tests
```

## CI Integration

- **Layer 1**: Runs on every PR commit (fast, no external deps)
- **Layer 1+2**: Runs on merge to `main`
- **Layer 3+4**: Manual or nightly trigger

## Dependencies

- Python 3.10+
- pytest >= 7.0 (for unit tests)
- Additional: aiohttp (for HttpProvider integration tests)

## Coverage Target

- Core A2A modules: >= 85%
- Integration paths: >= 70%
