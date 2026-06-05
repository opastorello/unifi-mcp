"""Contrato do cliente HTTP upstream multi-target (services/_http)."""
import httpx

from app import devices as _dev
from app.services import _http


async def test_device_nao_encontrado_retorna_erro():
    out = await _http.get_json("nao-existe", "/qualquer")
    assert out["erro"] is True
    assert "nao-existe" in out["mensagem"]


async def test_get_json_ok_com_mock_transport(monkeypatch):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    out = await _http.get_json("test-device", "/users")
    assert out == {"ok": True}


async def test_corpo_vazio_2xx_e_sucesso(monkeypatch):
    """Endpoints de ação UniFi (POST .../actions) respondem 200/204 sem body.
    Corpo vazio + 2xx tem de ser sucesso, não erro de decode (regressão)."""
    for code in (200, 204):
        def handler(_req: httpx.Request, _c=code) -> httpx.Response:
            return httpx.Response(_c, content=b"")

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await _http.request_json("test-device", "POST", "/devices/x/actions")
        assert out.get("erro") is None, out
        assert out["ok"] is True
        assert out["status"] == code


async def test_5xx_esgota_retries_e_vira_erro(monkeypatch):
    from app import config as _cfg
    monkeypatch.setattr(_cfg, "MAX_RETRIES", 1)

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(_http.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="down")

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    out = await _http.request_json("test-device", "POST", "/x")
    assert out["erro"] is True
    assert "503" in out["mensagem"]
    assert calls["n"] == 2
