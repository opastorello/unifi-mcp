"""Write-gate (mode-gate): garante que device em mode=read BLOQUEIA toda write tool
ANTES de tocar o upstream. IDs validos (alfanumericos) p/ chegar ao gate, que vem
depois da validacao de id nas tools UniFi. Sem mock: se vazar, o erro seria de
conexao, nao 'somente-leitura'.
"""
import pytest

from app import config as _cfg
from app import devices as _dev
from app.services import unifi


@pytest.fixture
def read_device(monkeypatch):
    monkeypatch.setattr(_cfg, "DEVICES_RAW", {
        "ro": {"name": "RO", "host": "ro.test", "port": 443, "api_token": "t",
               "verify_ssl": False, "timeout": 5, "mode": "read", "tags": []},
    })
    _dev.load()
    yield "ro"
    monkeypatch.setattr(_cfg, "DEVICES_RAW", {})
    _dev.load()


def _assert_blocked(out):
    assert out["erro"] is True
    assert "somente-leitura" in out["mensagem"]


class TestWriteGateBloqueiaRead:
    async def test_restart_device(self, read_device):
        _assert_blocked(await unifi.restart_device(read_device, "host1", "site1", "dev1"))

    async def test_power_cycle_port(self, read_device):
        _assert_blocked(await unifi.power_cycle_port(read_device, "host1", "site1", "dev1", 1))

    async def test_client_action(self, read_device):
        out = await unifi.client_action(
            read_device, "host1", "site1", "cli1", "AUTHORIZE_GUEST_ACCESS"
        )
        _assert_blocked(out)

    async def test_power_cycle_ap(self, read_device):
        _assert_blocked(await unifi.power_cycle_ap(read_device, "host1", "ap-mac-ou-nome"))
