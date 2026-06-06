"""Tests for gateway escrow routes."""

import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.deps import reset_db, get_escrow_service


@pytest.fixture(autouse=True)
def _reset():
    reset_db()


@pytest.fixture
def client():
    return TestClient(create_app())


def test_hold_escrow(client):
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
