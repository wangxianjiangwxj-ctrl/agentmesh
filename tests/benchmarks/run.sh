#!/usr/bin/env bash
# AgentMesh Benchmark Runner
# Usage: bash tests/benchmarks/run.sh [options]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="$PROJECT_DIR/benchmark_results"

echo "[AgentMesh Benchmarks] Running performance tests..."
echo "  Project: $PROJECT_DIR"
echo "  Output:  $OUTPUT_DIR"

mkdir -p "$OUTPUT_DIR"

# Run pytest benchmarks
cd "$PROJECT_DIR"
python3 -m pytest tests/benchmarks/ \
    --benchmark-only \
    --benchmark-json="$OUTPUT_DIR/benchmark_results.json" \
    --benchmark-columns="min,max,mean,stddev,rounds,ops,median" \
    -v \
    2>&1 | tee "$OUTPUT_DIR/benchmark_output.log"

echo ""
echo "[AgentMesh Benchmarks] Complete."
echo "  Results: $OUTPUT_DIR/benchmark_results.json"
echo "  Log:     $OUTPUT_DIR/benchmark_output.log"
