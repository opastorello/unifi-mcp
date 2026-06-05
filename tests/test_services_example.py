"""Testes unitários de app/services/unifi.py — lógica pura (UniFi Site Manager Cloud).

Cobre:
  - service_info() retorna campos obrigatórios
  - check_upstream() com mock de _http (GET /v1/hosts)
  - list_hosts() com mock upstream
  - get_host_detail() com host_id inválido
  - list_sites() com mock upstream
  - list_all_devices() com mock upstream
  - get_isp_metrics() valida interval
  - get_sdwan_config() com config_id inválido
  - get_console_sites() com host_id inválido e mock 403
  - get_console_devices() com IDs inválidos
  - get_device_detail() com IDs inválidos
  - get_console_clients() com mock upstream
  - get_console_networks() com mock upstream
  - get_console_info() com mock upstream
  - restart_device() com IDs inválidos e mock upstream
  - power_cycle_port() com port_idx inválido
  - client_action() com action inválida e mock upstream
"""
import httpx

from app import config as _cfg
from app import devices as _dev
from app.services import _http, unifi


class TestServiceInfo:
    def test_required_fields(self):
        info = unifi.service_info()
        assert "service" in info
        assert "version" in info
        assert "env" in info
        assert "devices_configured" in info
        assert "devices" in info
        assert "now" in info

    def test_version_matches_constant(self):
        info = unifi.service_info()
        assert info["version"] == unifi.SERVICE_VERSION

    def test_devices_count_matches(self):
        info = unifi.service_info()
        assert info["devices_configured"] == _dev.count()


class TestCheckUpstream:
    async def test_upstream_ok(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "host1", "type": "UCG-Ultra"}]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.check_upstream("test-device")
        assert out["device_id"] == "test-device"
        assert out["upstream"] == "ok"

    async def test_upstream_error(self, monkeypatch):
        monkeypatch.setattr(_cfg, "MAX_RETRIES", 0)

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="down")

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.check_upstream("test-device")
        assert out["erro"] is True

    async def test_device_not_found(self):
        out = await unifi.check_upstream("fantasma")
        assert out["erro"] is True
        assert "fantasma" in out["mensagem"]


class TestListHosts:
    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            payload = {"data": [{"id": "h1", "type": "UCG-Ultra", "owner": True}]}
            return httpx.Response(200, json=payload)

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.list_hosts("test-device")
        assert "data" in out

    async def test_invalid_device(self):
        out = await unifi.list_hosts("fantasma")
        assert out["erro"] is True


class TestGetHostDetail:
    async def test_invalid_host_id(self):
        out = await unifi.get_host_detail("test-device", "../../admin")
        assert out["erro"] is True
        assert "host_id inválido" in out["mensagem"]

    async def test_valid_host_id(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"id": "abc123", "type": "UCG-Ultra"}})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_host_detail("test-device", "abc123")
        assert "data" in out or "id" in out or not out.get("erro")


class TestListSites:
    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"siteId": "s1", "hostId": "h1"}]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.list_sites("test-device")
        assert "data" in out


class TestListAllDevices:
    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"hostId": "h1", "devices": []}]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.list_all_devices("test-device")
        assert "data" in out


class TestGetIspMetrics:
    async def test_valid_interval(self, monkeypatch):
        called_paths = []

        def handler(req: httpx.Request) -> httpx.Response:
            called_paths.append(req.url.path)
            return httpx.Response(200, json={"data": []})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        await unifi.get_isp_metrics("test-device", "1h")
        assert any("1h" in p for p in called_paths)

    async def test_invalid_interval_defaults_to_5m(self, monkeypatch):
        called_paths = []

        def handler(req: httpx.Request) -> httpx.Response:
            called_paths.append(req.url.path)
            return httpx.Response(200, json={"data": []})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        await unifi.get_isp_metrics("test-device", "30d")
        assert any("5m" in p for p in called_paths)


class TestGetSdwanConfig:
    async def test_invalid_config_id(self):
        out = await unifi.get_sdwan_config("test-device", "../../etc/passwd")
        assert out["erro"] is True
        assert "config_id inválido" in out["mensagem"]

    async def test_valid_config_id(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"id": "cfg1"}})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_sdwan_config("test-device", "cfg123")
        assert not out.get("erro")


class TestGetConsoleSites:
    async def test_invalid_host_id(self):
        out = await unifi.get_console_sites("test-device", "../bad")
        assert out["erro"] is True
        assert "host_id inválido" in out["mensagem"]

    async def test_403_not_owner(self, monkeypatch):
        """Erro 403 not-owner deve ser tratado como erro esperado."""
        monkeypatch.setattr(_cfg, "MAX_RETRIES", 0)

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "not the owner of this host"})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_console_sites("test-device", "host123")
        assert out["erro"] is True

    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"siteId": "s1"}]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_console_sites("test-device", "host123")
        assert "data" in out


class TestGetConsoleDevices:
    async def test_invalid_host_id(self):
        out = await unifi.get_console_devices("test-device", "../bad", "site1")
        assert out["erro"] is True
        assert "host_id inválido" in out["mensagem"]

    async def test_invalid_site_id(self):
        out = await unifi.get_console_devices("test-device", "host1", "../bad")
        assert out["erro"] is True
        assert "site_id inválido" in out["mensagem"]

    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "d1", "model": "U6-Pro"}]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_console_devices("test-device", "host1", "site1")
        assert "data" in out


class TestGetDeviceDetail:
    async def test_invalid_host_id(self):
        out = await unifi.get_device_detail("test-device", "../bad", "s1", "d1")
        assert out["erro"] is True
        assert "host_id inválido" in out["mensagem"]

    async def test_invalid_site_id(self):
        out = await unifi.get_device_detail("test-device", "h1", "../bad", "d1")
        assert out["erro"] is True
        assert "site_id inválido" in out["mensagem"]

    async def test_invalid_device_uid(self):
        out = await unifi.get_device_detail("test-device", "h1", "s1", "../bad")
        assert out["erro"] is True
        assert "device_uid inválido" in out["mensagem"]

    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"id": "d1", "model": "U6-Pro"}})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_device_detail("test-device", "h1", "s1", "d1")
        assert not out.get("erro")


class TestGetConsoleClients:
    async def test_invalid_host_id(self):
        out = await unifi.get_console_clients("test-device", "../bad", "s1")
        assert out["erro"] is True

    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "c1", "mac": "aa:bb:cc:dd:ee:ff"}]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_console_clients("test-device", "h1", "s1")
        assert "data" in out


class TestGetConsoleNetworks:
    async def test_invalid_site_id(self):
        out = await unifi.get_console_networks("test-device", "h1", "../bad")
        assert out["erro"] is True

    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "n1", "name": "LAN"}]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_console_networks("test-device", "h1", "s1")
        assert "data" in out


class TestGetConsoleInfo:
    async def test_invalid_host_id(self):
        out = await unifi.get_console_info("test-device", "../bad")
        assert out["erro"] is True

    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"version": "9.0.0"}})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.get_console_info("test-device", "h1")
        assert not out.get("erro")


class TestRestartDevice:
    async def test_invalid_host_id(self):
        out = await unifi.restart_device("test-device", "../bad", "s1", "d1")
        assert out["erro"] is True
        assert "host_id inválido" in out["mensagem"]

    async def test_invalid_device_uid(self):
        out = await unifi.restart_device("test-device", "h1", "s1", "../bad")
        assert out["erro"] is True
        assert "device_uid inválido" in out["mensagem"]

    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"message": "Accepted"})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.restart_device("test-device", "h1", "s1", "d1")
        assert not out.get("erro")


class TestPowerCyclePort:
    async def test_invalid_port_idx(self):
        out = await unifi.power_cycle_port("test-device", "h1", "s1", "d1", 0)
        assert out["erro"] is True
        assert "port_idx" in out["mensagem"]

    async def test_invalid_host_id(self):
        out = await unifi.power_cycle_port("test-device", "../bad", "s1", "d1", 3)
        assert out["erro"] is True
        assert "host_id inválido" in out["mensagem"]

    async def test_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"message": "Accepted"})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.power_cycle_port("test-device", "h1", "s1", "d1", 3)
        assert not out.get("erro")


class TestClientAction:
    async def test_invalid_action(self):
        out = await unifi.client_action("test-device", "h1", "s1", "c1", "DELETE")
        assert out["erro"] is True
        assert "action inválida" in out["mensagem"]

    async def test_invalid_host_id(self):
        out = await unifi.client_action(
            "test-device", "../bad", "s1", "c1", "AUTHORIZE_GUEST_ACCESS")
        assert out["erro"] is True
        assert "host_id inválido" in out["mensagem"]


class TestFleetHealthSummary:
    async def test_aggregates_from_sites(self, monkeypatch):
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/v1/hosts"):
                return httpx.Response(200, json={"data": [
                    {"id": "h1", "reportedState": {"name": "XDCAJ"}},
                    {"id": "h2", "reportedState": {"name": "XDMG"}},
                ]})
            return httpx.Response(200, json={"data": [
                {"siteId": "s1", "hostId": "h1", "meta": {"desc": "Default"},
                 "statistics": {"counts": {
                     "totalDevice": 6, "offlineDevice": 1,
                     "wifiClient": 13, "wiredClient": 16}}},
                {"siteId": "s2", "hostId": "h2", "meta": {"desc": "Default"},
                 "statistics": {"counts": {
                     "totalDevice": 4, "offlineDevice": 0,
                     "wifiClient": 9, "wiredClient": 10}}},
            ]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.fleet_health_summary("test-device")
        assert out["sites_total"] == 2
        assert out["consoles_total"] == 2
        assert out["devices"] == {"total": 10, "offline": 1, "online": 9}
        assert out["clients"] == {"wifi": 22, "wired": 26, "total": 48}
        assert out["sites_with_offline_devices"] == 1
        assert out["worst_sites"][0]["site"] == "XDCAJ"
        assert out["worst_sites"][0]["offline_devices"] == 1

    async def test_propagates_sites_error(self, monkeypatch):
        monkeypatch.setattr(_cfg, "MAX_RETRIES", 0)

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="down")

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.fleet_health_summary("test-device")
        assert out["erro"] is True


class TestListOfflineDevices:
    async def test_filters_not_online(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [
                {"hostId": "h1", "hostName": "XDCAJ", "devices": [
                    {"id": "d1", "mac": "aa", "name": "AP1", "model": "U6",
                     "ip": "10.0.0.5", "status": "online"},
                    {"id": "d2", "mac": "bb", "name": "AP2", "model": "U6",
                     "ip": "10.0.0.6", "status": "offline"},
                ]},
            ]})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.list_offline_devices("test-device")
        assert out["total"] == 1
        d = out["offline_devices"][0]
        assert d["name"] == "AP2"
        assert d["status"] == "offline"
        assert d["console"] == "XDCAJ"
        assert d["host_id"] == "h1"

    async def test_invalid_client_id(self):
        out = await unifi.client_action(
            "test-device", "h1", "s1", "../bad", "AUTHORIZE_GUEST_ACCESS")
        assert out["erro"] is True
        assert "client_id inválido" in out["mensagem"]

    async def test_authorize_guest_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"action": "AUTHORIZE_GUEST_ACCESS"})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.client_action(
            "test-device", "h1", "s1", "c1", "AUTHORIZE_GUEST_ACCESS")
        assert not out.get("erro")

    async def test_unauthorize_guest_success(self, monkeypatch):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"action": "UNAUTHORIZE_GUEST_ACCESS"})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.client_action(
            "test-device", "h1", "s1", "c1", "UNAUTHORIZE_GUEST_ACCESS")
        assert not out.get("erro")

    async def test_action_case_insensitive_and_params(self, monkeypatch):
        """Normaliza p/ maiúsculas e inclui params opcionais no corpo."""
        captured: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            import json as _j
            captured.update(_j.loads(req.content))
            return httpx.Response(200, json={"action": "AUTHORIZE_GUEST_ACCESS"})

        device = _dev.get("test-device")
        monkeypatch.setitem(
            _http._clients, "test-device",
            httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
        )
        out = await unifi.client_action(
            "test-device", "h1", "s1", "c1", "authorize_guest_access",
            time_limit_minutes=60, data_usage_limit_mb=1024)
        assert not out.get("erro")
        assert captured["action"] == "AUTHORIZE_GUEST_ACCESS"
        assert captured["timeLimitMinutes"] == 60
        assert captured["dataUsageLimitMBytes"] == 1024
