"""Shared test fixtures for AgentMesh test suite."""

import os
import sys

import pytest

# Add SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agentmesh"))


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
def multi_round_tasks():
    """3-task multi-round conversation sequence."""
    return [
        {
            "id": "mr_001",
            "status": {"state": "submitted"},
            "payload": {"text": "Round 1: initial greeting", "round": 1},
            "metadata": {"source": "multi_round", "round": 1},
        },
        {
            "id": "mr_002",
            "status": {"state": "submitted"},
            "payload": {"text": "Round 2: follow-up query", "round": 2},
            "metadata": {"source": "multi_round", "round": 2, "prev": "mr_001"},
        },
        {
            "id": "mr_003",
            "status": {"state": "submitted"},
            "payload": {"text": "Round 3: final confirmation", "round": 3},
            "metadata": {"source": "multi_round", "round": 3, "prev": "mr_002"},
        },
    ]


@pytest.fixture
def agent_chain():
    """Multi-agent chain (A→B→C) task definitions."""
    return {
        "agents": ["agent_a", "agent_b", "agent_c"],
        "tasks": [
            {"id": "chain_a_001", "agent": "agent_a", "text": "Discovery phase"},
            {"id": "chain_b_001", "agent": "agent_b", "text": "Analysis phase"},
            {"id": "chain_c_001", "agent": "agent_c", "text": "Reporting phase"},
        ],
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
