"""Cliente HTTP multi-target para APIs upstream de IT Ops.

Suporta N devices (targets), cada um com host/port/credenciais próprias.
Pool de AsyncClients por device_id — lazy init, fechados no lifespan.

Contrato público:
  - `get_json(device_id, path)` / `request_json(device_id, path)` → dict
  - Falha esperada → `{"erro": True, "mensagem": "..."}`
  - `request(device_id, method, path)` → httpx.Response

Guard de segurança: bloqueia SSRF (path para host externo) e path traversal.

Auth upstream:
  - Padrão: `Authorization: Bearer <api_token>`
  - UniFi OS 4.x+: `X-API-KEY: <api_token>` — ative via `device.extra["auth_scheme"] = "x-api-key"`
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app import config as _cfg
from app import metrics as _m
from app.devices import Device, DeviceNotFoundError
from app.devices import get as get_device

_clients: dict[str, httpx.AsyncClient] = {}
_sems: dict[str, asyncio.Semaphore] = {}


def _get_sem(device_id: str) -> asyncio.Semaphore:
    if device_id not in _sems:
        _sems[device_id] = asyncio.Semaphore(_cfg.MAX_CONCURRENT)
    return _sems[device_id]

_RETRYABLE = (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)


class UpstreamError(Exception):
    """Falha ao falar com a API upstream após esgotar os retries."""


def _build_client(device: Device) -> httpx.AsyncClient:
    headers = {"Accept": "application/json"}
    auth_scheme = (device.extra or {}).get("auth_scheme", "bearer")
    if device.api_token:
        if auth_scheme == "x-api-key":
            headers["X-API-KEY"] = device.api_token
        else:
            headers["Authorization"] = f"Bearer {device.api_token}"
    return httpx.AsyncClient(
        base_url=device.base_url,
        timeout=device.timeout,
        headers=headers,
        verify=device.verify_ssl,
    )


def _get_client(device: Device) -> httpx.AsyncClient:
    if device.id not in _clients:
        _clients[device.id] = _build_client(device)
    return _clients[device.id]


async def aclose_all() -> None:
    """Fecha todos os clients — chamado no lifespan shutdown."""
    for c in _clients.values():
        await c.aclose()
    _clients.clear()
    _sems.clear()


_ALLOWED_REQUEST_KW = frozenset({"json", "data", "params", "content", "files"})


async def request(device_id: str, method: str, path: str, **kw: Any) -> httpx.Response:
    """Chamada com retry/backoff + métricas. Levanta `UpstreamError` no fim."""
    kw = {k: v for k, v in kw.items() if k in _ALLOWED_REQUEST_KW}
    try:
        device = get_device(device_id)
    except DeviceNotFoundError as exc:
        raise UpstreamError(str(exc)) from exc

    _base = httpx.URL(device.base_url)
    _target = _base.join(path)
    if (_target.scheme, _target.host, _target.port) != (_base.scheme, _base.host, _base.port):
        raise UpstreamError("path resolvido para host fora do upstream — bloqueado (SSRF)")

    # Defense-in-depth: block path traversal within same host
    if ".." in path:
        raise UpstreamError("path contém traversal (..) — bloqueado")

    cli = _get_client(device)
    last: Exception | None = None
    async with _get_sem(device_id):
        _m.concurrent_requests.inc()
        try:
            for attempt in range(_cfg.MAX_RETRIES + 1):
                if attempt > 0:
                    _m.upstream_retries_total.inc()
                try:
                    with _m.upstream_request_duration_seconds.time():
                        resp = await cli.request(method, path, **kw)
                    _m.upstream_requests_total.labels(
                        method=method.upper(),
                        status=str(resp.status_code),
                        device=device_id,
                    ).inc()
                    if resp.status_code >= 500:
                        _m.upstream_errors_total.labels(
                            type="http_status", device=device_id
                        ).inc()
                        last = UpstreamError(f"upstream HTTP {resp.status_code}")
                    else:
                        return resp
                except _RETRYABLE as exc:
                    kind = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection"
                    _m.upstream_errors_total.labels(type=kind, device=device_id).inc()
                    last = exc
                if attempt < _cfg.MAX_RETRIES:
                    await asyncio.sleep(0.5 * (attempt + 1))
        finally:
            _m.concurrent_requests.dec()

    msg = str(last) or f"{type(last).__name__} ao conectar em {device_id}"
    raise UpstreamError(msg if last else "falha desconhecida no upstream")


async def request_json(device_id: str, method: str, path: str, **kw: Any) -> dict:
    """Igual a `request`, mas devolve dict e converte falha em `{erro:True}`."""
    try:
        resp = await request(device_id, method, path, **kw)
        resp.raise_for_status()
        # Endpoints de ação (POST .../actions) respondem 200/204 com corpo
        # vazio. Corpo vazio + 2xx é SUCESSO, não erro de decode.
        if not (resp.content or b"").strip():
            return {"ok": True, "status": resp.status_code}
        data = resp.json()
        return data if isinstance(data, dict) else {"data": data}
    except UpstreamError as exc:
        return {"erro": True, "mensagem": str(exc)}
    except httpx.HTTPStatusError as exc:
        _m.upstream_errors_total.labels(type="http_status", device=device_id).inc()
        return {"erro": True, "mensagem": f"upstream HTTP {exc.response.status_code}"}
    except (json.JSONDecodeError, ValueError):
        _m.upstream_errors_total.labels(type="decode", device=device_id).inc()
        return {"erro": True, "mensagem": "resposta upstream não-JSON"}


async def get_json(device_id: str, path: str, **kw: Any) -> dict:
    return await request_json(device_id, "GET", path, **kw)
