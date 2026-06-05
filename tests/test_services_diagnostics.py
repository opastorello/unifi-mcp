"""Testes de app/services/unifi.py — capability de diagnóstico L1 / health.

Cobre as funções que falam com a Network API legada proxiada pelo Connector:
get_device_diagnostics, resolve_uplink, get_port_health, get_site_health,
power_cycle_ap. Upstream mockado via httpx.MockTransport (roteado por path).
"""
import httpx

from app import devices as _dev
from app.services import _http, unifi

# ── Fixtures de payload (forma real observada em api.ui.com) ────────────────

_AP_OFFLINE = {
    "name": "LDA-AP-02", "mac": "f4:92:bf:c9:0b:ef", "model": "U7LR",
    "type": "uap", "state": 0, "last_seen": 1777522242, "uptime": None,
    "satisfaction": None, "ip": "10.2.64.199", "version": "6.6.77",
    "uplink": {"uplink_mac": "74:83:c2:06:19:bc",
               "uplink_device_name": "LDA-SW01", "uplink_remote_port": 4,
               "type": "wire"},
}
_AP_DEGRADED = {
    "name": "LDA-AP-03", "mac": "78:45:58:40:01:80", "model": "U7LR",
    "type": "uap", "state": 1, "last_seen": 1778995140, "uptime": 1102,
    "satisfaction": -1, "ip": "10.2.64.235", "version": "6.6.77",
    "uplink": {"uplink_mac": "74:83:c2:06:19:bc",
               "uplink_device_name": "LDA-SW01", "uplink_remote_port": 5,
               "type": "wire"},
}
_SWITCH = {
    "name": "LDA-SW01", "mac": "74:83:c2:06:19:bc", "model": "US16P150",
    "type": "usw", "state": 1,
    "port_table": [
        {"port_idx": 4, "up": False, "speed": 0, "poe_enable": False,
         "poe_mode": "auto", "poe_good": False, "poe_power": "0.00",
         "poe_voltage": "0.00", "lldp_table": []},
        {"port_idx": 5, "up": True, "speed": 100, "poe_enable": True,
         "poe_mode": "auto", "poe_good": True, "poe_power": "2.95",
         "poe_voltage": "53.65", "lldp_table": []},
    ],
}
_STAT_DEVICE = {"meta": {"rc": "ok"}, "data": [_AP_OFFLINE, _AP_DEGRADED, _SWITCH]}


def _mount(monkeypatch, handler):
    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler),
                          base_url=device.base_url),
    )


def _router(extra=None):
    """Handler que roteia por path: stat/device, integration v1 sites/devices,
    health endpoints e POST de power-cycle."""
    extra = extra or {}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path in extra:
            return extra[path]
        if path.endswith("/stat/device"):
            return httpx.Response(200, json=_STAT_DEVICE)
        if path.endswith("/integration/v1/sites"):
            return httpx.Response(200, json={"data": [{"id": "site-uuid-1"}]})
        if "/integration/v1/sites/" in path and path.endswith("/devices"):
            return httpx.Response(200, json={"data": [
                {"id": "sw-uid-1", "macAddress": "74:83:c2:06:19:bc"}]})
        if path.endswith("/interfaces/ports/4/actions"):
            return httpx.Response(200, json={"message": "Accepted"})
        if path.endswith("/stat/health"):
            return httpx.Response(200, json={"data": [
                {"subsystem": "wlan", "status": "warning",
                 "num_disconnected": 1, "num_adopted": 4, "num_pending": 0},
                {"subsystem": "wan", "status": "ok", "num_disconnected": 0,
                 "num_adopted": 1, "num_pending": 0},
                {"subsystem": "vpn", "status": "unknown"},
            ]})
        if path.endswith("/stat/widget/health"):
            return httpx.Response(200, json={"data": [
                {"devices_status": {"uap": {"disconnected": 1}},
                 "wifi_score": {"client_score_avg": 99},
                 "average_wifi_utilization": {"total": 11.3}}]})
        if path.endswith("/aggregated-dashboard"):
            return httpx.Response(200, json={"wifi_doctor": {"actions": [
                {"id": "UPDATE_DEVICE_FIRMWARE", "optimization_status": "PENDING",
                 "upgradable_devices": [{"mac": "a"}, {"mac": "b"}]}]}})
        return httpx.Response(404, json={"meta": {"rc": "error"}})

    return handler


class TestGetDeviceDiagnostics:
    async def test_ref_obrigatorio(self):
        out = await unifi.get_device_diagnostics("test-device", "h1", "")
        assert out["erro"] is True

    async def test_match_por_nome_enriquece_porta(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.get_device_diagnostics("test-device", "h1", "LDA-AP-02")
        assert out["online"] is False
        assert out["uplink"]["port_idx"] == 4
        assert out["uplink"]["link_speed_mbps"] == 0
        assert out["uplink"]["poe_good"] is False

    async def test_match_por_mac_link_degradado(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.get_device_diagnostics(
            "test-device", "h1", "78:45:58:40:01:80")
        assert out["online"] is True
        assert out["uplink"]["link_speed_mbps"] == 100
        assert out["uplink"]["link_degraded"] is True

    async def test_nao_encontrado(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.get_device_diagnostics("test-device", "h1", "FANTASMA")
        assert out["erro"] is True


class TestResolveUplink:
    async def test_bridge_mac_para_uuid(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.resolve_uplink("test-device", "h1", "LDA-AP-02")
        assert out["port_idx"] == 4
        assert out["switch_uid"] == "sw-uid-1"
        assert out["site_id"] == "site-uuid-1"
        assert out["ap_online"] is False

    async def test_sem_uplink_com_fio(self, monkeypatch):
        wireless = {"name": "AP-W", "mac": "00:11:22:33:44:55", "type": "uap",
                    "state": 1, "uplink": {}}

        def h(req):
            if req.url.path.endswith("/stat/device"):
                return httpx.Response(200, json={"data": [wireless]})
            return httpx.Response(404, json={})

        _mount(monkeypatch, h)
        out = await unifi.resolve_uplink("test-device", "h1", "AP-W")
        assert out["erro"] is True
        assert "uplink" in out["mensagem"]


class TestGetPortHealth:
    async def test_curadoria_e_degraded(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.get_port_health("test-device", "h1", "LDA-SW01")
        assert out["online"] is True
        assert out["degraded_ports"] == [5]
        p5 = next(p for p in out["ports"] if p["port_idx"] == 5)
        assert p5["low_speed"] is True
        assert p5["poe_power_w"] == "2.95"

    async def test_switch_nao_encontrado(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.get_port_health("test-device", "h1", "XX")
        assert out["erro"] is True


class TestGetSiteHealth:
    async def test_agrega_e_filtra_warnings(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.get_site_health("test-device", "h1")
        assert out["warnings"] == ["wlan"]  # vpn=unknown não conta
        assert out["disconnected_total"] == 1
        assert out["wifi_score"]["client_score_avg"] == 99
        assert out["wifi_doctor"][0]["upgradable_devices"] == 2

    async def test_health_erro_propaga(self, monkeypatch):
        def h(req):
            return httpx.Response(500, text="down")

        monkeypatch.setattr("app.config.MAX_RETRIES", 0, raising=False)
        _mount(monkeypatch, h)
        out = await unifi.get_site_health("test-device", "h1")
        assert out["erro"] is True


class TestPowerCycleAp:
    async def test_compoe_resolve_e_cycle(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.power_cycle_ap("test-device", "h1", "LDA-AP-02")
        assert out["resolved"]["port_idx"] == 4
        assert not out["power_cycle"].get("erro")

    async def test_resolve_erro_propaga(self, monkeypatch):
        _mount(monkeypatch, _router())
        out = await unifi.power_cycle_ap("test-device", "h1", "FANTASMA")
        assert out["erro"] is True
