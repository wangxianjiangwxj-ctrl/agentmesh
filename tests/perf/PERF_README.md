# AgentMesh A2A Provider — Performance Test Suite

## Overview

This directory contains P2-level performance baselines for the AgentMesh
A2A protocol adapter. The suite covers three providers:

| Provider | Description | I/O | Start required |
|----------|-------------|-----|----------------|
| `MemoryProvider` | Pure in-memory, no network | CPU only | No |
| `A2AFacade` | MemoryProvider + TaskManager wrapper | CPU + dict ops | No |
| `HttpProvider` | HTTP client to local A2A server | Loopback TCP | Yes (auto) |

All in-memory tests run without external services and are safe for
CI pipelines. HTTP tests require FastAPI + uvicorn and start their own
ephemeral server.

## Quick Start

```bash
# Run all perf tests
cd /path/to/agentmesh
python3 -m pytest tests/perf/ -v --durations=10

# Run only in-memory tests (CI-safe, no dependencies beyond pytest)
python3 -m pytest tests/perf/ -v -k "not Http" --durations=10

# Run a specific test class
python3 -m pytest tests/perf/test_provider_latency.py -v \
    -k "TestMemoryProviderLatency"

# Run throughput tests only
python3 -m pytest tests/perf/test_throughput.py -v

# Run with verbose timing output
python3 -m pytest tests/perf/ -v -s --durations=0

# Run a single named test
python3 -m pytest tests/perf/test_provider_latency.py::TestMemoryProviderLatency::test_send_message_mean_p99 -v
```

## Test Structure

```
tests/perf/
  conftest.py               # Fixtures, helpers, threshold config
  test_provider_latency.py  # Latency baselines (mean/median/P99)
  test_throughput.py        # Throughput & concurrency tests
  PERF_README.md            # This file
```

### conftest.py — Common Infrastructure

Key exports:

- **Provider fixtures**: `memory_provider`, `facade`, `http_provider`
  (all module-scoped for amortized construction)
- **Task fixtures**: `sample_task_full`, `sample_task_minimal`,
  `sample_task_completed`
- **TimingStats**: Dataclass with mean, median, P99, stddev, ops/sec
- **`measure_latency(fn, iterations, warmup)`**: Measures N timed calls
  with pre-warmup; returns TimingStats
- **`run_concurrent(fn, num_workers, iterations_per_worker)`**: Runs
  a callable across N threads, returns aggregated TimingStats
- **`get_rss_mb()`**: Current resident set size in MB (via getrusage)
- **`LATENCY_THRESHOLDS`**: `LatencyThresholds` dataclass — single source
  of truth for pass/fail limits
- **`THROUGHPUT_THRESHOLDS`**: `ThroughputThresholds` dataclass for TPS
  floor values
- **`RESOURCE_THRESHOLDS`**: `ResourceThresholds` for memory/CPU caps

### test_provider_latency.py — Latency Baselines

Tests for each provider's core operations. Each test:

1. Collects N timed iterations after M warmup calls
2. Asserts that **mean** and **P99** fall within configured thresholds
3. Reports all stats via stdout (visible with `-s` flag)

| Class | Operations | Iterations | Thresholds |
|-------|-----------|------------|------------|
| `TestMemoryProviderLatency` | send, get, cancel, ping, 404 | 1000 / 500 | `<500us` mean, `<2ms` P99 |
| `TestA2AFacadeLatency` | send, get, cancel | 500 | `<1ms` mean, `<5ms` P99 |
| `TestHttpProviderLatency` | send, ping, get | 200 | `<50ms` mean (localhost) |
| `TestProviderComparison` | facade vs memory ratio | 500 | `<5x` slowdown |

### test_throughput.py — Throughput & Concurrency

Tests measure operations-per-second under sequential and concurrent load.

| Class | What it tests | Load |
|-------|--------------|------|
| `TestMemoryProviderSequentialThroughput` | Single-threaded send/get/mixed TPS | 2000 iterations |
| `TestMemoryProviderConcurrentThroughput` | 2/4/8 worker concurrent send/mixed | 250 iter/worker |
| `TestA2AFacadeThroughput` | Sequential send/get TPS via Facade | 1000 iterations |
| `TestResourceUsage` | Memory baseline, growth, leak check | 10K tasks |
| `TestConcurrencyScaling` | Scaling curve (1/2/4/8 workers) | 200 iter/worker |

## Expected Baselines

### Latency (M1 Mac mini / equivalent)

| Provider | Operation | Mean | P99 |
|----------|-----------|------|-----|
| MemoryProvider | send_message | < 500 us | < 2 ms |
| MemoryProvider | get_task | < 300 us | < 1 ms |
| MemoryProvider | cancel_task | < 300 us | < 1 ms |
| MemoryProvider | ping | < 200 us | < 500 us |
| MemoryProvider | 404 lookup | < 200 us | < 500 us |
| A2AFacade | send_task | < 1 ms | < 5 ms |
| A2AFacade | get_task | < 500 us | < 2 ms |
| HttpProvider (localhost) | send | < 50 ms | < 100 ms |
| HttpProvider (localhost) | ping | < 50 ms | < 100 ms |
| Facade vs Memory ratio | | < 5x | — |

### Throughput (single-threaded, M1 Mac mini)

| Provider | Operation | Min TPS |
|----------|-----------|---------|
| MemoryProvider | send_message (seq) | 5,000 ops/s |
| MemoryProvider | get_task (seq) | 8,000 ops/s |
| MemoryProvider | mixed send+get+cancel | 4,000 ops/s |
| MemoryProvider | concurrent send (4 workers) | 20,000 ops/s |
| A2AFacade | send_task (seq) | 3,000 ops/s |
| A2AFacade | get_task (seq) | 5,000 ops/s |

### Resource Usage

| Metric | Limit |
|--------|-------|
| RSS under 10K tasks | < 200 MB |
| RSS growth from baseline | < 50 MB |
| RSS after cleanup (8 threads) | + < 20 MB |

## CI Integration

```yaml
# GitHub Actions example — add to your workflow
perf-tests:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.9"
    - run: pip install -e ".[test]"
    # In-memory tests only (CI-safe, no server needed)
    - run: python -m pytest tests/perf/ -v -k "not Http" --junitxml=perf-results.xml
    # Full suite if FastAPI is available
    - run: pip install fastapi uvicorn
    - run: python -m pytest tests/perf/ -v --junitxml=perf-full-results.xml
```

### JUnit XML with `--junitxml=perf-results.xml`

All tests use standard pytest assertions, so they produce standard
JUnit output that CI runners (GitHub Actions, Jenkins, GitLab CI)
can parse for pass/fail visualization.

## Threshold Tuning

Thresholds are defined in `conftest.py` as dataclass instances:

```python
# Adjust for slower CI runners
LATENCY_THRESHOLDS.memory_send_mean = 0.002    # 2ms instead of 500us
THROUGHPUT_THRESHOLDS.memory_send_tps_min = 1000  # 1K instead of 5K
```

To temporarily disable a threshold assertion (for investigation):

```bash
python -m pytest tests/perf/ -v -s --durations=0 2>&1 | grep -E "\[(MemoryProvider|A2AFacade)\]"
```

## Adding New Tests

1. Create a new file `tests/perf/test_<feature>.py`
2. Import `measure_latency`, `run_concurrent`, thresholds from `conftest`
3. Define thresholds in `conftest.py` if new baselines are needed
4. Follow the pattern: warmup -> timed iterations -> assert thresholds

```python
def test_new_operation_latency(self, memory_provider):
    def op():
        result = memory_provider.new_operation(...)
        assert result.success

    stats = measure_latency(op, iterations=500, warmup=50,
                            label="MemoryProvider.new_operation")
    assert stats.mean < 0.001  # 1ms
```

## Design Principles

1. **No pytest-benchmark dependency** — uses `time.perf_counter()` and
   `statistics` (both stdlib). This avoids a dev-dependency chain.

2. **Self-healing fixtures** — `http_provider` auto-starts and
   auto-tears-down its server. Tests don't leave dangling processes.

3. **Assertions over logging** — every test has at least one assertion
   with a clear error message. A failed perf test is a red CI build.

4. **Warmup before measurement** — JIT compilation (PyPy) and
   Python's bytecode cache warm up before timed iterations begin.

5. **Module-scoped providers** — fixture setup cost is paid once
   per file, not per test.

6. **Explicit thresholds in one place** — all pass/fail values are
   in `conftest.py` dataclasses. No magic numbers in test functions.

## Troubleshooting

**Tests fail on slow machines / CI:**
- Increase thresholds in `conftest.py` (see "Threshold Tuning")
- Run with `-k "not Http"` to skip HTTP tests

**HttpProvider tests hang:**
- The `http_provider` fixture starts a subprocess; it waits up to 10s
  for the server to be ready. Check that `fastapi` and `uvicorn` are
  installed. Run `python -m pip install fastapi uvicorn`.

**Concurrent tests flaky:**
- Thread-level concurrency on CPython is limited by the GIL for
  CPU-bound work. These tests are most meaningful on PyPy or for
  I/O-bound operations.
- Reduce `num_workers` to 2 or 4 for more stable results.

**High P99 outliers:**
- First-time imports and Python's garbage collector can cause spikes.
  Warmup iterations mitigate most of this. If P99 is consistently
  high, consider `gc.disable()` during the timed section (but restore
  after).
