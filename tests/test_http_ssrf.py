"""Regression tests for SSRF + path-traversal guard in services/_http (multi-target)."""
import httpx
import pytest

from app import devices as _dev
from app.services import _http


def _mock_client(base: str) -> httpx.AsyncClient:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base)


async def test_absolute_url_imds_blocked():
    """SSRF: absolute URL to IMDS blocked."""
    out = await _http.request_json("test-device", "GET", "http://169.254.169.254/latest/meta-data/")
    assert out["erro"] is True
    assert "SSRF" in out["mensagem"] or "bloqueado" in out["mensagem"]


async def test_absolute_url_https_evil_blocked():
    out = await _http.request_json("test-device", "GET", "https://evil.com/x")
    assert out["erro"] is True
    assert "bloqueado" in out["mensagem"]


async def test_protocol_relative_evil_blocked():
    out = await _http.request_json("test-device", "GET", "//evil.com/x")
    assert out["erro"] is True
    assert "bloqueado" in out["mensagem"]


async def test_legitimate_path_allowed(monkeypatch):
    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        _mock_client(device.base_url),
    )
    out = await _http.request_json("test-device", "GET", "/users")
    assert out == {"ok": True}


async def test_request_raises_upstream_error_for_absolute_url():
    with pytest.raises(_http.UpstreamError, match="SSRF|bloqueado"):
        await _http.request("test-device", "GET", "http://169.254.169.254/latest/meta-data/")
