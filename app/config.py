"""Configuração do MCP — carrega config.json + env vars (secrets).

Hierarquia:
  - config/config.json (ou CONFIG_PATH env) → devices, server, http, logging
  - Env vars → ENV, API_TOKEN (secrets não ficam em arquivo)
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _env(key: str, default: str) -> str:
    return os.getenv(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


# ── Env vars (secrets + runtime) ───────────────────────────────
ENV = _env("ENV", "production")
IS_PRODUCTION = ENV == "production"
IS_TEST = ENV in {"test", "testing"}
CONFIG_PATH = _env("CONFIG_PATH", "config/config.json")

# ── Carregar config.json ───────────────────────────────────────
_config: dict = {}
_config_path = Path(CONFIG_PATH)
if _config_path.is_file():
    with _config_path.open(encoding="utf-8") as f:
        _config = json.load(f)

# ── Server ─────────────────────────────────────────────────────
_server = _config.get("server", {})

# API_TOKEN: env var tem precedencia; em runtime real (nao-teste) cai para
# config.json (server.api_token) -- segredo vive no config.json, sem .env.
API_TOKEN = _env("API_TOKEN", "")
if not API_TOKEN and not IS_TEST:
    API_TOKEN = str(_server.get("api_token", "")).strip()
SERVER_NAME = _server.get("name", "unifi")
SERVER_HOST = _server.get("host", "0.0.0.0")
SERVER_PORT = _env_int("PORT", _server.get("port", 8000))

# ── HTTP (settings compartilhados entre devices) ──────────────
_http = _config.get("http", {})
HTTP_TIMEOUT = float(_http.get("timeout", 30))
MAX_RETRIES = int(_http.get("max_retries", 3))
MAX_CONCURRENT = int(_http.get("max_concurrent", 10))

# ── Logging ────────────────────────────────────────────────────
_logging = _config.get("logging", {})
LOG_LEVEL = _logging.get("level", "INFO")

# ── Devices (raw dict — processado por app/devices.py) ─────────
DEVICES_RAW: dict = _config.get("devices", {})

# ── Rate limit ─────────────────────────────────────────────────
RATE_LIMIT_DEFAULT = _env("RATE_LIMIT_DEFAULT", "60/minute")
TRUSTED_PROXY_COUNT = _env_int("TRUSTED_PROXY_COUNT", 0)
