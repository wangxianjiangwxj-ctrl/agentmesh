"""Tests for gateway reputation routes."""

import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.deps import reset_db


@pytest.fixture(autouse=True)
def _reset():
    reset_db()


@pytest.fixture
def client():
    return TestClient(create_app())


def test_submit_review(client):
    headers = {"X-API-Key": "test-key"}
    resp = client.post(
        "/api/v1/reviews/submit",
        json={
            "task_id": "task-review-1",
            "target_id": "agent-target",
            "score": 4,
            "comment": "Good work",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "review_id" in data
    assert data["task_id"] == "task-review-1"
    assert data["target_id"] == "agent-target"
    assert data["score"] == 4


def test_get_reputation(client):
    headers = {"X-API-Key": "test-key"}
    resp = client.get(
        "/api/v1/reputation/agent-someone",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["agent_id"] == "agent-someone"
    assert "reputation_score" in data
    assert "total_reviews" in data
