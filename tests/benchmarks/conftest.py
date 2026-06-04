"""Benchmark fixtures and configuration for AgentMesh performance tests."""

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture(scope="session")
def benchmark_output_dir() -> Generator[Path, None, None]:
    """Temporary directory for benchmark output files."""
    with tempfile.TemporaryDirectory(prefix="agentmesh_bench_") as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(scope="session")
def small_message() -> bytes:
    """Small (sub-1KB) A2A message payload."""
    return b'{"role": "user", "content": "Hello, AgentMesh!", "metadata": {}}'


@pytest.fixture(scope="session")
def medium_message() -> bytes:
    """Medium (~100KB) A2A message payload."""
    content = "This is a medium-sized test payload. " * 5000
    return content.encode("utf-8")


@pytest.fixture(scope="session")
def large_message() -> bytes:
    """Large (~1MB) A2A message payload."""
    content = "Large payload chunk. " * 50000
    return content.encode("utf-8")



