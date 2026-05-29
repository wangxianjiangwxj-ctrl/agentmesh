"""Shared test fixtures for AgentMesh test suite."""

import os
import sys

import pytest

# Add SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))


@pytest.fixture
def sample_task():
    """A standard well-formed A2A task."""
    return {
        "id": "test_task_001",
        "status": {"state": "submitted"},
        "payload": {"query": "What is the weather in Shanghai?"},
        "metadata": {"source": "test"},
    }


@pytest.fixture
def completed_task():
    """A task in COMPLETED state."""
    return {
        "id": "compl_task_001",
        "status": {"state": "completed"},
        "payload": {},
        "artifacts": {"result": "42"},
    }


@pytest.fixture
def task_with_children():
    """A parent task with two children."""
    return {
        "parent": {"id": "parent_001", "status": {"state": "submitted"}},
        "children": [
            {"id": "child_001", "status": {"state": "submitted"}, "metadata": {"parent": "parent_001"}},
            {"id": "child_002", "status": {"state": "working"}, "metadata": {"parent": "parent_001"}},
        ],
    }
