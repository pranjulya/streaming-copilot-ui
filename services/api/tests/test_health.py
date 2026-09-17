import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_live_ok(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "live"}


def test_ready_requires_db(client):
    r = client.get("/health/ready")
    assert r.status_code in (200, 503)
    assert r.headers["content-type"].startswith("application/json") or "problem+json" in r.headers["content-type"]
