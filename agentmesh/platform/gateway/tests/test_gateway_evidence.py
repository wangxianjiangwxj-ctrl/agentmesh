"""Tests for gateway evidence routes."""

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


def test_record_evidence(client):
    headers = {"X-API-Key": "test-key"}
    # Register the agent first so it has a key pair for signing
    reg = client.post(
        "/api/v1/agents/register",
        json={"name": "test-agent", "auth_token": "test-key"},
        headers=headers,
    )
    assert reg.status_code == 200

    resp = client.post(
        "/api/v1/evidence/record",
        json={
            "task_id": "task-ev-1",
            "action": "task_created",
            "payload": {"task_id": "task-ev-1", "title": "test"},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "evidence_id" in data
    assert data["task_id"] == "task-ev-1"
    assert data["action"] == "task_created"
