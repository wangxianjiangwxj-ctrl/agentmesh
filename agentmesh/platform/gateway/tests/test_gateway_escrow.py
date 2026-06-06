"""Tests for gateway escrow routes."""

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


def test_hold_escrow(client):
    """Test holding escrow for a task with valid amount and task_id."""
    headers = {"X-API-Key": "test-key"}
    resp = client.post(
        "/api/v1/escrow/hold",
        json={
            "task_id": "task-1",
            "amount": 100,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "held"
    assert data["task_id"] == "task-1"
    assert data["amount"] == 100
