"""Registry de devices (targets upstream) para MCPs multi-target.

Carrega de config.json (via DEVICES_RAW em config.py).
Nunca expõe api_token para fora — use `list_safe()` para retornar ao agent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app import config as _cfg

_log = logging.getLogger("unifi")

_registry: dict[str, Device] = {}


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    name: str
    host: str
    port: int = 443
    api_token: str = ""
    use_tls: bool = True
    verify_ssl: bool = True
    timeout: float = 30.0
    tags: list[str] = field(default_factory=list)
    mode: str = "read"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_tls else "http"
        return f"{scheme}://{self.host}:{self.port}"

    def safe_dict(self) -> dict[str, Any]:
        """Representação sem credenciais — seguro para expor via tool."""
        return {
            "device_id": self.id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "verify_ssl": self.verify_ssl,
            "tags": self.tags,
            "mode": self.mode,
            "extra": _redact_secrets(self.extra),
        }


_SECRET_KEY_HINTS = (
    "secret", "password", "passwd", "pwd", "token",
    "credential", "private", "apikey", "api_key", "access_key",
)


def _redact_secrets(extra: dict[str, Any]) -> dict[str, Any]:
    """Redige valores de chaves sensiveis em `extra` (oauth_secret, app_token, ...).
    safe_dict() expoe `extra` ao agente/REST -> sem isto, segredos fora do api_token vazam."""
    return {
        k: ("***" if any(h in k.lower() for h in _SECRET_KEY_HINTS) else v)
        for k, v in extra.items()
    }


class DeviceNotFoundError(Exception):
    pass


def load() -> None:
    """Carrega o registry a partir do config. Chamado uma vez no lifespan."""
    global _registry
    _registry = {}

    if _cfg.DEVICES_RAW:
        for dev_id, dev_cfg in _cfg.DEVICES_RAW.items():
            known_keys = {
                "name", "host", "port", "api_token",
                "use_tls", "verify_ssl", "timeout", "tags", "mode",
            }
            extra = {k: v for k, v in dev_cfg.items() if k not in known_keys}
            raw_mode = dev_cfg.get("mode", "read")
            if raw_mode not in {"read", "write", "admin"}:
                _log.warning(
                    "device '%s': mode='%s' invalido — usando 'read' (validos: read|write|admin)",
                    dev_id, raw_mode,
                )
                raw_mode = "read"
            _registry[dev_id] = Device(
                id=dev_id,
                name=dev_cfg.get("name", dev_id),
                host=dev_cfg["host"],
                port=dev_cfg.get("port", 443),
                api_token=dev_cfg.get("api_token", ""),
                use_tls=dev_cfg.get("use_tls", dev_cfg.get("port", 443) != 80),
                verify_ssl=dev_cfg.get("verify_ssl", True),
                timeout=dev_cfg.get("timeout", _cfg.HTTP_TIMEOUT),
                tags=dev_cfg.get("tags", []),
                mode=raw_mode,
                extra=extra,
            )

    _log.info("devices: %d device(s) carregado(s): %s", len(_registry), list(_registry.keys()))


def get(device_id: str) -> Device:
    """Retorna device por ID. Levanta DeviceNotFoundError se não existir."""
    dev = _registry.get(device_id)
    if dev is None:
        available = list(_registry.keys())
        raise DeviceNotFoundError(
            f"device '{device_id}' não encontrado. Disponíveis: {available}"
        )
    return dev


def list_all() -> list[Device]:
    return list(_registry.values())


def list_safe() -> list[dict[str, Any]]:
    """Retorna devices sem credenciais — seguro para expor ao agent."""
    return [d.safe_dict() for d in _registry.values()]


def list_ids() -> list[str]:
    return list(_registry.keys())


def count() -> int:
    return len(_registry)
