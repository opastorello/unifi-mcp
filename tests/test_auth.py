"""Token protege REST E o endpoint MCP; só /health fica aberto."""
import pytest
from fastapi.testclient import TestClient

from app import config as _cfg
from app.main import app

TOKEN = "test-secret-token"


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(_cfg, "API_TOKEN", TOKEN)
    with TestClient(app) as client:
        yield client


def test_health_open_without_token(auth_on):
    assert auth_on.get("/health").status_code == 200


def test_rest_blocked_without_token(auth_on):
    assert auth_on.get("/api/unifi/info").status_code == 401


def test_rest_blocked_with_wrong_token(auth_on):
    r = auth_on.get("/api/unifi/info", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_rest_ok_with_token(auth_on):
    r = auth_on.get("/api/unifi/info", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert "version" in r.json()


def test_mcp_endpoint_blocked_without_token(auth_on):
    assert auth_on.get("/mcp").status_code == 401


def test_root_index_requires_token(auth_on):
    assert auth_on.get("/").status_code == 401
    assert auth_on.get("/", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_no_auth_when_token_empty():
    with TestClient(app) as client:
        assert client.get("/api/unifi/info").status_code == 200
