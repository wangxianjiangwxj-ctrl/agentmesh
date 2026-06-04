# CI Benchmark Integration Proposal

## Objective

Integrate the benchmarks defined in B-1 (Benchmark Framework), B-2 (Performance Test Suite), and B-3 (Performance Report) into the AgentMesh CI pipeline. This ensures that every nightly build produces performance metrics, detects regressions automatically, and maintains a historical baseline for performance tracking.

## Solution

A dedicated GitHub Actions workflow that runs nightly (via cron) and on demand (via `workflow_dispatch`), executing the benchmark and performance test suites, generating a comparison report against the latest baseline, and uploading the report as a build artifact.

### Workflow Triggers

- **Schedule**: Daily at 06:00 UTC (`cron: '0 6 * * *'`)
- **Manual**: `workflow_dispatch` button in the GitHub Actions UI

## Workflow Structure

```yaml
jobs:
  benchmark:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install .[dev]

      - name: Run benchmarks
        run: pytest tests/benchmarks/ --benchmark-json=benchmark-results.json

      - name: Run performance tests
        run: pytest tests/performance/ --junitxml=perf-results.xml

      - name: Generate comparison report
        run: |
          python scripts/compare-benchmarks.py \
            --baseline baseline.json \
            --current benchmark-results.json \
            --output performance-report.md

      - name: Upload report artifact
        uses: actions/upload-artifact@v4
        with:
          name: performance-report-${{ github.run_id }}
          path: |
            benchmark-results.json
            perf-results.xml
            performance-report.md

      - name: Check for regressions
        id: check-regression
        run: |
          python scripts/regression-check.py \
            --baseline baseline.json \
            --current benchmark-results.json \
            --threshold 0.10

      - name: Mark job as failed on regression
        if: steps.check-regression.outputs.regression == 'true'
        run: |
          echo "Performance regression detected (threshold: 10%)"
          exit 1
```

## Pass/Fail Criteria

The benchmark job is considered **passing** when all of the following hold:

| Criterion | Description | Threshold |
|---|---|---|
| No execution error | All benchmark and performance tests run to completion | -- |
| No throughput regression | `ops/sec` (or equivalent) does not drop below the baseline | <= 10% decrease |
| No latency regression | P95/P99 latency does not exceed the baseline | <= 20% increase |
| No memory regression | Peak memory usage does not exceed the baseline | <= 15% increase |

A **failure** is triggered if any criterion is violated. The job exits with code 1, and an alert is visible in the GitHub Actions UI.

## Baseline Reference

The following data from the B-3 report serves as the initial performance baseline:

| Metric | Value | Source |
|---|---|---|
| Message encoding/decoding throughput | ~5,000 ops/sec | B-3 v1.0rc1 report |
| P95 latency | <10 ms | B-3 v1.0rc1 report |
| Memory footprint (idle) | ~45 MB | B-3 v1.0rc1 report |
| Memory footprint (active, 1K messages) | ~72 MB | B-3 v1.0rc1 report |

These values come from the first official performance report generated in B-3. After each successful nightly run, the new results replace the baseline for the next comparison. The baseline JSON file is stored in the repository as `docs/benchmarks/baseline.json`.

## Artifacts and Reporting

- **JSON results**: Raw benchmark data for programmatic consumption
- **XML results**: JUnit-format performance test results (compatible with GitHub Actions test summary)
- **Markdown report**: Human-readable summary with before/after comparison
- **GitHub Pages**: The latest report is optionally published to the AgentMesh docs site for wider visibility

## Future Enhancements

1. Automatic PR commenting when benchmarks run on PR trigger
2. Historical trend chart (stored in GitHub Actions cache)
3. InfluxDB / Grafana integration for long-term performance dashboards
4. Performance budgets defined in `pyproject.toml` for declarative regression thresholds
