"""F-03 — /health?deep=true requires Bearer token when API_TOKEN is set."""
import pytest
from fastapi.testclient import TestClient

from app import config as _cfg
from app.main import app
from app.services import unifi as unifi_svc

TOKEN = "tkn"


@pytest.fixture
def auth_client(monkeypatch):
    """Client with API_TOKEN set and check_upstream stubbed."""
    monkeypatch.setattr(_cfg, "API_TOKEN", TOKEN)

    async def _fake_upstream(device_id: str):
        return {"device_id": device_id, "upstream": "ok"}

    monkeypatch.setattr(unifi_svc, "check_upstream", _fake_upstream)
    with TestClient(app) as client:
        yield client


def test_shallow_health_open_no_token(auth_client):
    r = auth_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_deep_health_no_auth_returns_401(auth_client):
    r = auth_client.get("/health?deep=true")
    assert r.status_code == 401
    assert r.json().get("erro") is True


def test_deep_health_wrong_token_returns_401(auth_client):
    r = auth_client.get("/health?deep=true", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert r.json().get("erro") is True


def test_deep_health_correct_token_returns_200(auth_client):
    r = auth_client.get("/health?deep=true", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body.get("upstream") == "ok"


def test_deep_health_allowed_without_token_in_dev(monkeypatch):
    """When API_TOKEN is empty (dev), deep=true is allowed without auth."""
    async def _stub(device_id: str):
        return {"device_id": device_id, "upstream": "ok"}

    monkeypatch.setattr(unifi_svc, "check_upstream", _stub)
    with TestClient(app) as client:
        r = client.get("/health?deep=true")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
