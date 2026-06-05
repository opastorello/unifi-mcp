from fastapi.testclient import TestClient

from app.main import app


def test_root_is_json_index():
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["mcp"] == "/mcp"
    assert body["api"] == "/api"
    assert "version" in body
    assert "devices" in body


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "devices_loaded" in body


def test_info_shape():
    with TestClient(app) as client:
        r = client.get("/api/unifi/info")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["service"], str) and body["service"]
    assert "version" in body and "env" in body
    assert "devices_configured" in body
    assert "devices" in body


def test_list_devices():
    with TestClient(app) as client:
        r = client.get("/api/unifi/devices-list")
    assert r.status_code == 200
    body = r.json()
    assert "devices" in body
    assert body["total"] >= 1
    for d in body["devices"]:
        assert "device_id" in d
        assert "api_token" not in d
