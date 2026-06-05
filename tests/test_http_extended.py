"""Testes estendidos do cliente HTTP upstream (app/services/_http.py).

Complementa test_http.py com cenarios nao cobertos:
  - Timeout no upstream (retry + metrica de timeout)
  - Connection error (retry + metrica)
  - JSON decode failure na resposta
  - Resposta nao-dict (lista) fica em {"data": [...]}
  - _build_client coloca Authorization quando api_token existe
  - _build_client sem api_token nao coloca Authorization
  - aclose_all() limpa o pool de clients
  - HTTP 4xx nao faz retry
"""
import httpx
import pytest

from app import config as _cfg
from app import devices as _dev
from app.services import _http


async def test_timeout_retries_and_returns_error(monkeypatch):
    """Timeout na upstream faz retry e retorna erro."""
    monkeypatch.setattr(_cfg, "MAX_RETRIES", 1)

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(_http.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("timeout")

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    out = await _http.get_json("test-device", "/slow")
    assert out["erro"] is True
    assert calls["n"] == 2  # 1 initial + 1 retry


async def test_connection_error_retries(monkeypatch):
    """Connection error faz retry corretamente."""
    monkeypatch.setattr(_cfg, "MAX_RETRIES", 2)

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(_http.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    out = await _http.get_json("test-device", "/down")
    assert out["erro"] is True
    assert calls["n"] == 3  # 1 initial + 2 retries


async def test_json_decode_error_returns_mensagem(monkeypatch):
    """Resposta nao-JSON do upstream retorna erro de decode."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<html>not json</html>", headers={"content-type": "text/html"}
        )

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    out = await _http.request_json("test-device", "GET", "/broken")
    assert out["erro"] is True
    assert "não-JSON" in out["mensagem"]


async def test_non_dict_response_wrapped_in_data(monkeypatch):
    """Resposta que e lista (nao dict) fica em {"data": [...]}."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    out = await _http.request_json("test-device", "GET", "/list")
    assert out == {"data": [1, 2, 3]}


async def test_4xx_does_not_retry(monkeypatch):
    """HTTP 4xx nao e retryable — retorna erro na primeira tentativa."""
    monkeypatch.setattr(_cfg, "MAX_RETRIES", 2)

    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={"detail": "not found"})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    out = await _http.request_json("test-device", "GET", "/missing")
    # 4xx retorna como erro via raise_for_status
    assert out["erro"] is True
    assert "404" in out["mensagem"]
    assert calls["n"] == 1  # sem retry


async def test_aclose_all_clears_pool(monkeypatch):
    """aclose_all() fecha clients e limpa o dict."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    assert "test-device" in _http._clients
    await _http.aclose_all()
    assert "test-device" not in _http._clients


def test_build_client_with_token():
    """_build_client inclui Authorization header quando api_token existe."""
    from app.devices import Device

    dev = Device(id="x", name="x", host="h.local", api_token="my-secret")
    client = _http._build_client(dev)
    assert client.headers["authorization"] == "Bearer my-secret"


def test_build_client_without_token():
    """_build_client NAO inclui Authorization quando api_token vazio."""
    from app.devices import Device

    dev = Device(id="x", name="x", host="h.local", api_token="")
    client = _http._build_client(dev)
    assert "authorization" not in client.headers


async def test_upstream_error_type_is_raised_raw(monkeypatch):
    """request() levanta UpstreamError apos esgotar retries."""
    monkeypatch.setattr(_cfg, "MAX_RETRIES", 0)

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    with pytest.raises(_http.UpstreamError):
        await _http.request("test-device", "GET", "/fail")
