"""Testes do passthrough genérico da Network Integration v1 (cloud + local).

Cobre:
  - integration_get: subpath inválido, host_id ausente (cloud), sucesso cloud,
    modo local (kind=local) resolvendo /proxy/network/integration/v1 e ignorando host_id.
  - integration_write: método inválido, write-gate (mode=read), body não-dict, sucesso.
  - resolução de path correta (Cloud Connector vs console local) inspecionando a URL upstream.
"""
import httpx

from app import config as _cfg
from app import devices as _dev
from app.services import _http
from app.services import unifi


def _mock(monkeypatch, device_id, handler):
    """Injeta um MockTransport no pool de clients para o device."""
    device = _dev.get(device_id)
    monkeypatch.setitem(
        _http._clients,
        device_id,
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )


def _use_local_device(monkeypatch):
    """Registra um device 'local-console' (kind=local) e devolve o id."""
    monkeypatch.setattr(_cfg, "DEVICES_RAW", {
        "local-console": {
            "name": "Console Local",
            "host": "10.0.0.1",
            "port": 443,
            "api_token": "local-token",
            "verify_ssl": False,
            "timeout": 5,
            "mode": "admin",
            "kind": "local",  # → extra.kind == "local"
        }
    })
    _dev.load()
    return "local-console"


class TestIntegrationGet:
    async def test_subpath_invalido_traversal(self):
        out = await unifi.integration_get("test-device", "../etc/passwd", "host123")
        assert out["erro"] is True
        assert "subpath inválido" in out["mensagem"]

    async def test_subpath_vazio(self):
        out = await unifi.integration_get("test-device", "", "host123")
        assert out["erro"] is True

    async def test_cloud_sem_host_id(self):
        out = await unifi.integration_get("test-device", "sites")
        assert out["erro"] is True
        assert "host_id obrigatório" in out["mensagem"]

    async def test_cloud_monta_path_do_connector(self, monkeypatch):
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["path"] = req.url.path
            return httpx.Response(200, json={"data": [{"id": "s1"}], "totalCount": 1})

        _mock(monkeypatch, "test-device", handler)
        out = await unifi.integration_get("test-device", "sites", "host123", paged=False)
        assert not out.get("erro")
        assert seen["path"] == "/v1/connector/consoles/host123/network/integration/v1/sites"

    async def test_local_monta_path_direto_e_ignora_host(self, monkeypatch):
        dev_id = _use_local_device(monkeypatch)
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["path"] = req.url.path
            return httpx.Response(200, json={"data": []})

        _mock(monkeypatch, dev_id, handler)
        # host_id propositalmente ausente — deve ser ignorado p/ device local
        out = await unifi.integration_get(dev_id, "sites/s1/clients", paged=False)
        assert not out.get("erro")
        assert seen["path"] == "/proxy/network/integration/v1/sites/s1/clients"


class TestIntegrationWrite:
    async def test_metodo_invalido(self):
        out = await unifi.integration_write("test-device", "sites", method="GET", host_id="h1")
        assert out["erro"] is True
        assert "método inválido" in out["mensagem"]

    async def test_write_gate_bloqueia_read_only(self, monkeypatch):
        monkeypatch.setattr(_cfg, "DEVICES_RAW", {
            "ro-device": {"name": "RO", "host": "up.test", "api_token": "t", "mode": "read"}
        })
        _dev.load()
        out = await unifi.integration_write("ro-device", "sites/s1/networks", body={"x": 1}, host_id="h1")
        assert out["erro"] is True
        assert "somente-leitura" in out["mensagem"]

    async def test_body_nao_dict(self):
        out = await unifi.integration_write("test-device", "sites", body="naodict", host_id="h1")
        assert out["erro"] is True
        assert "body deve ser objeto JSON" in out["mensagem"]

    async def test_sucesso_post_envia_corpo(self, monkeypatch):
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["method"] = req.method
            seen["path"] = req.url.path
            seen["body"] = req.content
            return httpx.Response(200, json={"id": "new1"})

        _mock(monkeypatch, "test-device", handler)
        out = await unifi.integration_write(
            "test-device", "sites/s1/wifi/broadcasts",
            method="POST", body={"name": "IoT"}, host_id="host123",
        )
        assert not out.get("erro")
        assert seen["method"] == "POST"
        assert seen["path"] == (
            "/v1/connector/consoles/host123/network/integration/v1/sites/s1/wifi/broadcasts"
        )
        assert b"IoT" in seen["body"]
