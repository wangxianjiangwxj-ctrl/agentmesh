from fastapi.testclient import TestClient
from gateway.app import create_app

client = TestClient(create_app())


def test_health():
    """Test the health check endpoint returns 200 and status ok."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
