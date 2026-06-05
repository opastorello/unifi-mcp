"""Testes unitários do módulo app/devices.py — registry multi-target.

Cobre:
  - load() com config vazio (nenhum device)
  - load() com múltiplos devices
  - get() para device existente e DeviceNotFoundError
  - list_safe() não expõe api_token
  - list_all(), list_ids(), count()
  - Device.base_url e Device.safe_dict()
  - Campos extras em device config ficam em .extra
"""
import pytest

from app import config as _cfg
from app import devices as _dev
from app.devices import Device, DeviceNotFoundError


class TestDeviceLoad:
    """Carregamento do registry a partir do config."""

    def test_load_empty_config(self, monkeypatch):
        monkeypatch.setattr(_cfg, "DEVICES_RAW", {})
        _dev.load()
        assert _dev.count() == 0
        assert _dev.list_ids() == []
        assert _dev.list_all() == []
        assert _dev.list_safe() == []

    def test_load_single_device(self, monkeypatch):
        monkeypatch.setattr(_cfg, "DEVICES_RAW", {
            "fw-01": {
                "name": "Firewall Principal",
                "host": "10.0.0.1",
                "port": 8443,
                "api_token": "secret123",
                "verify_ssl": False,
                "timeout": 10,
                "tags": ["site:matriz"],
            }
        })
        _dev.load()
        assert _dev.count() == 1
        assert _dev.list_ids() == ["fw-01"]

    def test_load_multiple_devices(self, monkeypatch):
        monkeypatch.setattr(_cfg, "DEVICES_RAW", {
            "fw-01": {"name": "FW1", "host": "10.0.0.1"},
            "fw-02": {"name": "FW2", "host": "10.0.0.2"},
            "sw-01": {"name": "Switch", "host": "10.0.0.3"},
        })
        _dev.load()
        assert _dev.count() == 3
        assert set(_dev.list_ids()) == {"fw-01", "fw-02", "sw-01"}

    def test_load_defaults_port_443_and_verify_ssl(self, monkeypatch):
        monkeypatch.setattr(_cfg, "DEVICES_RAW", {
            "minimal": {"host": "10.0.0.1"}
        })
        _dev.load()
        dev = _dev.get("minimal")
        assert dev.port == 443
        assert dev.verify_ssl is True
        assert dev.api_token == ""
        assert dev.name == "minimal"  # defaults to device_id

    def test_load_extra_keys_go_to_extra(self, monkeypatch):
        monkeypatch.setattr(_cfg, "DEVICES_RAW", {
            "with-extras": {
                "host": "10.0.0.1",
                "name": "ExtraDevice",
                "custom_field": "value1",
                "another_field": 42,
            }
        })
        _dev.load()
        dev = _dev.get("with-extras")
        assert dev.extra == {"custom_field": "value1", "another_field": 42}


class TestDeviceGet:
    """Busca por ID e DeviceNotFoundError."""

    def test_get_existing_device(self):
        # conftest already loads "test-device"
        dev = _dev.get("test-device")
        assert dev.id == "test-device"
        assert dev.host == "up.test"

    def test_get_nonexistent_raises(self):
        with pytest.raises(DeviceNotFoundError) as exc_info:
            _dev.get("nao-existe")
        assert "nao-existe" in str(exc_info.value)
        assert "test-device" in str(exc_info.value)  # shows available

    def test_get_empty_registry_raises(self, monkeypatch):
        monkeypatch.setattr(_cfg, "DEVICES_RAW", {})
        _dev.load()
        with pytest.raises(DeviceNotFoundError):
            _dev.get("qualquer")


class TestDeviceSafety:
    """list_safe e safe_dict nao expoe credenciais."""

    def test_list_safe_excludes_api_token(self):
        safe = _dev.list_safe()
        assert len(safe) >= 1
        for d in safe:
            assert "api_token" not in d
            assert "device_id" in d
            assert "host" in d

    def test_safe_dict_fields(self):
        dev = _dev.get("test-device")
        sd = dev.safe_dict()
        assert sd["device_id"] == "test-device"
        assert sd["name"] == "Test Device"
        assert sd["host"] == "up.test"
        assert sd["port"] == 443
        assert "api_token" not in sd


class TestDeviceBaseUrl:
    """Device.base_url computa corretamente."""

    def test_base_url_default_443(self):
        dev = Device(id="x", name="x", host="fw.local", port=443)
        assert dev.base_url == "https://fw.local:443"

    def test_base_url_custom_port(self):
        dev = Device(id="x", name="x", host="fw.local", port=8443)
        assert dev.base_url == "https://fw.local:8443"


class TestListAll:
    """list_all retorna Device objects."""

    def test_list_all_returns_device_objects(self):
        all_devs = _dev.list_all()
        assert len(all_devs) >= 1
        assert all(isinstance(d, Device) for d in all_devs)
