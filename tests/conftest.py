"""Fixtures compartilhadas para testes do template."""
import pytest

from app import config as _cfg
from app import devices as _dev


@pytest.fixture(autouse=True)
def _setup_test_device(monkeypatch):
    """Garante ao menos um device 'test-device' no registry para todos os testes."""
    monkeypatch.setattr(_cfg, "DEVICES_RAW", {
        "test-device": {
            "name": "Test Device",
            "host": "up.test",
            "port": 443,
            "api_token": "test-token",
            "verify_ssl": False,
            "timeout": 5,
            "mode": "admin",  # write/admin tools liberados nos testes
            "tags": ["env:test"],
        }
    })
    _dev.load()
    yield
    monkeypatch.setattr(_cfg, "DEVICES_RAW", {})
    _dev.load()
