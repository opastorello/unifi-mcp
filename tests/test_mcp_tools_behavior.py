"""Testes de COMPORTAMENTO das tools MCP UniFi Site Manager Cloud.

test_mcp_tools.py valida ESTRUTURA (naming, description, schema).
Este módulo valida que cada tool produz output correto, incluindo:
  - list_devices retorna devices sem credenciais
  - service_info retorna metadados
  - check_upstream com device inválido retorna erro
  - list_hosts com mock upstream retorna dados
  - get_host_detail com host_id inválido retorna erro
  - get_console_sites com host_id inválido retorna erro
  - get_console_devices com IDs inválidos retorna erro
  - get_device_detail com IDs inválidos retorna erro
  - restart_device com IDs inválidos retorna erro
  - power_cycle_port com port_idx inválido retorna erro
  - client_action com action inválida retorna erro
  - _ToolTimer atualiza métricas corretamente
"""
import httpx
import pytest
from fastmcp import Client

from app import devices as _dev
from app import metrics as _m
from app.mcp_server import mcp
from app.services import _http


@pytest.fixture
def mcp_client():
    """Client MCP in-memory conectado ao servidor."""
    return Client(mcp)


async def test_list_devices_tool(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool("list_devices", {})
    data = result.data
    assert "devices" in data
    assert "total" in data
    assert data["total"] >= 1
    for dev in data["devices"]:
        assert "api_token" not in dev
        assert "device_id" in dev


async def test_service_info_tool(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool("service_info", {})
    data = result.data
    assert "version" in data
    assert "env" in data
    assert "devices_configured" in data
    assert data["devices_configured"] >= 1


async def test_check_upstream_invalid_device(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool("check_upstream", {"device_id": "nao-existe"})
    data = result.data
    assert data["erro"] is True
    assert "nao-existe" in data["mensagem"]


async def test_check_upstream_valid_device(mcp_client, monkeypatch):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "host1", "type": "UCG-Ultra"}]})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    async with mcp_client as client:
        result = await client.call_tool("check_upstream", {"device_id": "test-device"})
    data = result.data
    assert data["device_id"] == "test-device"
    assert data["upstream"] == "ok"


async def test_list_hosts_invalid_device(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool("list_hosts", {"device_id": "nao-existe"})
    data = result.data
    assert data["erro"] is True


async def test_list_hosts_valid_device(mcp_client, monkeypatch):
    def handler(_req: httpx.Request) -> httpx.Response:
        payload = {"data": [{"id": "h1", "type": "UCG-Ultra", "owner": True}]}
        return httpx.Response(200, json=payload)

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    async with mcp_client as client:
        result = await client.call_tool("list_hosts", {"device_id": "test-device"})
    data = result.data
    assert "data" in data


async def test_get_host_detail_invalid_host_id(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "get_host_detail",
            {"device_id": "test-device", "host_id": "../bad"},
        )
    data = result.data
    assert data["erro"] is True
    assert "host_id inválido" in data["mensagem"]


async def test_get_console_sites_invalid_host_id(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "get_console_sites",
            {"device_id": "test-device", "host_id": "../traversal"},
        )
    data = result.data
    assert data["erro"] is True
    assert "host_id inválido" in data["mensagem"]


async def test_get_console_devices_invalid_host_id(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "get_console_devices",
            {"device_id": "test-device", "host_id": "../bad", "site_id": "s1"},
        )
    data = result.data
    assert data["erro"] is True


async def test_get_console_devices_invalid_site_id(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "get_console_devices",
            {"device_id": "test-device", "host_id": "h1", "site_id": "../bad"},
        )
    data = result.data
    assert data["erro"] is True
    assert "site_id inválido" in data["mensagem"]


async def test_get_device_detail_invalid_ids(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "get_device_detail",
            {
                "device_id": "test-device",
                "host_id": "h1",
                "site_id": "s1",
                "device_uid": "../bad",
            },
        )
    data = result.data
    assert data["erro"] is True
    assert "device_uid inválido" in data["mensagem"]


async def test_restart_device_invalid_host_id(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "restart_device",
            {
                "device_id": "test-device",
                "host_id": "../bad",
                "site_id": "s1",
                "device_uid": "d1",
            },
        )
    data = result.data
    assert data["erro"] is True


async def test_power_cycle_port_invalid_port(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "power_cycle_port",
            {
                "device_id": "test-device",
                "host_id": "h1",
                "site_id": "s1",
                "device_uid": "d1",
                "port_idx": 0,
            },
        )
    data = result.data
    assert data["erro"] is True
    assert "port_idx" in data["mensagem"]


async def test_client_action_invalid_action(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "client_action",
            {
                "device_id": "test-device",
                "host_id": "h1",
                "site_id": "s1",
                "client_id": "c1",
                "action": "DELETE",
            },
        )
    data = result.data
    assert data["erro"] is True
    assert "action inválida" in data["mensagem"]


async def test_client_action_invalid_client_id(mcp_client):
    async with mcp_client as client:
        result = await client.call_tool(
            "client_action",
            {
                "device_id": "test-device",
                "host_id": "h1",
                "site_id": "s1",
                "client_id": "../bad",
                "action": "AUTHORIZE_GUEST_ACCESS",
            },
        )
    data = result.data
    assert data["erro"] is True
    assert "client_id inválido" in data["mensagem"]


async def test_client_action_valid(mcp_client, monkeypatch):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "Accepted"})

    device = _dev.get("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )
    async with mcp_client as client:
        result = await client.call_tool(
            "client_action",
            {
                "device_id": "test-device",
                "host_id": "h1",
                "site_id": "s1",
                "client_id": "c1",
                "action": "AUTHORIZE_GUEST_ACCESS",
            },
        )
    data = result.data
    assert not data.get("erro")


class TestToolTimer:
    """_ToolTimer instrumenta métricas corretamente."""

    def test_timer_increments_and_decrements_gauge(self):
        from app.mcp_server import _ToolTimer

        gauge_before = _m.mcp_calls_in_progress.labels(tool="test_timer")._value.get()
        with _ToolTimer("test_timer") as t:
            gauge_during = _m.mcp_calls_in_progress.labels(tool="test_timer")._value.get()
            assert gauge_during == gauge_before + 1
            t.record("success")
        gauge_after = _m.mcp_calls_in_progress.labels(tool="test_timer")._value.get()
        assert gauge_after == gauge_before

    def test_timer_records_counter(self):
        from app.mcp_server import _ToolTimer

        before = _m.mcp_calls_total.labels(
            tool="test_counter", result="success", client="unknown"
        )._value.get()
        with _ToolTimer("test_counter") as t:
            t.record("success")
        after = _m.mcp_calls_total.labels(
            tool="test_counter", result="success", client="unknown"
        )._value.get()
        assert after == before + 1

    def test_timer_records_duration_histogram(self):
        from app.mcp_server import _ToolTimer

        hist = _m.mcp_call_duration_seconds.labels(tool="test_hist")
        count_before = hist._sum.get()
        with _ToolTimer("test_hist") as t:
            t.record("success")
        count_after = hist._sum.get()
        assert count_after > count_before

    def test_timer_custom_client(self):
        from app.mcp_server import _ToolTimer

        before = _m.mcp_calls_total.labels(
            tool="test_client", result="error", client="my-agent"
        )._value.get()
        with _ToolTimer("test_client", client="my-agent") as t:
            t.record("error")
        after = _m.mcp_calls_total.labels(
            tool="test_client", result="error", client="my-agent"
        )._value.get()
        assert after == before + 1
