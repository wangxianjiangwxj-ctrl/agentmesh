"""Tests for gateway task routes."""

import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.deps import reset_db


@pytest.fixture(autouse=True)
def _reset():
    """Reset database state before each test."""
    reset_db()


@pytest.fixture
def client():
    """Create a FastAPI test client for gateway endpoint testing."""
    return TestClient(create_app())


@pytest.fixture
def headers():
    """Default test API headers."""
    return {"X-API-Key": "test-key"}


def test_create_task(client, headers):
    """Test creating a new task with title, description, and escrow."""
    resp = client.post(
        "/api/v1/tasks",
        json={
            "title": "Design a poster",
            "description": "1080x1920, tech style",
            "escrow_amount": 100,
            "publisher_share": 0.4,
            "executor_share": 0.6,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "task_id" in data
    assert data["title"] == "Design a poster"
    assert data["status"] == "open"


def test_list_tasks(client, headers):
    """Test listing tasks after creating one."""
    # Create a task first
    client.post(
        "/api/v1/tasks",
        json={
            "title": "Task 1",
            "description": "desc",
            "escrow_amount": 50,
            "publisher_share": 0.5,
            "executor_share": 0.5,
        },
        headers=headers,
    )

    resp = client.get("/api/v1/tasks", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "tasks" in data
    assert len(data["tasks"]) >= 1
