"""Tests for gateway identity routes (register + lookup)."""

import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.deps import reset_db


@pytest.fixture(autouse=True)
def _reset():
    """Reset all service singletons before each test."""
    reset_db()


@pytest.fixture
def client():
    return TestClient(create_app())


def test_register_agent(client):
    """Test registering a new agent with name and auth token."""
    resp = client.post(
        "/api/v1/agents/register",
        json={"name": "test-agent", "auth_token": "token-1"},
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "agent_id" in data
    assert data["name"] == "test-agent"
    assert "did" in data
    assert "public_key" in data


def test_get_agent(client):
    """Test retrieving a registered agent by ID."""
    # Register first
    reg = client.post(
        "/api/v1/agents/register",
        json={"name": "get-me", "auth_token": "token-2"},
        headers={"X-API-Key": "test-key"},
    )
    assert reg.status_code == 200
    agent_id = reg.json()["agent_id"]

    # Then get
    resp = client.get(
        f"/api/v1/agents/{agent_id}",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["agent_id"] == agent_id
    assert data["name"] == "get-me"


def test_get_agent_not_found(client):
    """Test retrieving a non-existent agent returns 404."""
    resp = client.get(
        "/api/v1/agents/nonexistent-id",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 404
    assert "agent not found" in resp.text.lower() or "not found" in resp.text
