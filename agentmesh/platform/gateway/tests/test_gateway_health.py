from fastapi.testclient import TestClient
from gateway.app import create_app

client = TestClient(create_app())


def test_health():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
