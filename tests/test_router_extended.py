"""Testes estendidos dos routers REST UniFi Site Manager Cloud.

Cobre:
  - GET /{device_id}/check com device válido (mock upstream)
  - GET /{device_id}/check com device inválido
  - Deep health sem devices configurados
  - Deep health com upstream respondendo OK
  - Deep health com upstream falhando
  - Rota / (root index) com fields corretos
"""
import httpx
from fastapi.testclient import TestClient

from app import config as _cfg
from app import devices as _dev
from app.main import app
from app.services import _http


def test_check_device_endpoint_invalid_device():
    with TestClient(app) as client:
        r = client.get("/api/unifi/nao-existe/check")
    assert r.status_code == 200
    body = r.json()
    assert body["erro"] is True
    assert "nao-existe" in body["mensagem"]


def test_check_device_endpoint_valid_device(monkeypatch):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "h1", "type": "UCG-Ultra"}]})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    with TestClient(app) as client:
        r = client.get("/api/unifi/test-device/check")
    assert r.status_code == 200
    body = r.json()
    assert body["device_id"] == "test-device"
    assert body["upstream"] == "ok"


def test_deep_health_no_devices(monkeypatch):
    monkeypatch.setattr(_cfg, "DEVICES_RAW", {})
    _dev.load()
    with TestClient(app) as client:
        r = client.get("/health?deep=true")
    assert r.status_code == 200
    body = r.json()
    assert body["upstream"] == "no_devices"


def test_deep_health_upstream_ok(monkeypatch):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "h1", "type": "UCG-Ultra"}]})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    with TestClient(app) as client:
        r = client.get("/health?deep=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["upstream"] == "ok"
    assert body["device"] == "test-device"


def test_deep_health_upstream_failing(monkeypatch):
    monkeypatch.setattr(_cfg, "MAX_RETRIES", 0)

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    with TestClient(app) as client:
        r = client.get("/health?deep=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["upstream"] == "unreachable"


def test_root_index_has_all_links():
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    required_keys = {"service", "version", "devices", "api", "docs", "mcp", "health", "metrics"}
    assert required_keys.issubset(set(body.keys()))


def test_get_hosts_endpoint_invalid_device():
    with TestClient(app) as client:
        r = client.get("/api/unifi/nao-existe/hosts")
    assert r.status_code == 200
    body = r.json()
    assert body["erro"] is True


def test_get_hosts_endpoint_valid(monkeypatch):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "h1", "type": "UCG-Ultra"}]})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    with TestClient(app) as client:
        r = client.get("/api/unifi/test-device/hosts")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body


def test_restart_device_endpoint_invalid_host(monkeypatch):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "Accepted"})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    with TestClient(app) as client:
        r = client.post(
            "/api/unifi/test-device/restart-device",
            json={"host_id": "../bad", "site_id": "s1", "device_uid": "d1"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["erro"] is True


def test_client_action_endpoint_invalid_action(monkeypatch):
    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={})),
            base_url=device.base_url,
        ),
    )
    with TestClient(app) as client:
        r = client.post(
            "/api/unifi/test-device/client-action",
            json={"host_id": "h1", "site_id": "s1", "client_id": "c1", "action": "DELETE"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["erro"] is True
    assert "action inválida" in body["mensagem"]
