"""Camada de serviço UniFi — lógica pura, ZERO imports de FastAPI ou FastMCP.

Multi-target: cada device no config é uma de duas naturezas (campo extra.kind):
  • "cloud" (default) — conta Site Manager em api.ui.com; alcança qualquer console
    da conta REMOTAMENTE via Cloud Connector. Auth: header X-API-KEY.
  • "local" — um console UniFi específico, acesso DIRETO na LAN. Auth: header X-API-KEY.

Auth upstream via X-API-KEY é configurada em _http._build_client quando
`device.extra["auth_scheme"] == "x-api-key"`.

Camadas de API cobertas:
  A) Site Manager v1 (frota, só p/ device cloud) — prefixo /v1/
  B) Network Integration v1 (por console), resolvida conforme o device:
       - cloud: /v1/connector/consoles/{host_id}/network/integration/v1/{subpath}
       - local: /proxy/network/integration/v1/{subpath}
     Tools dedicadas (sites/devices/clients/...) + passthrough genérico
     (integration_get/integration_write) cobrem toda a spec e versões futuras.
  C) Network API legada (por console, via Connector) — diagnóstico físico L1/health
     que a Integration v1 não expõe (link speed, PoE real, last_seen, mapa MAC↔porta).

Referência de endpoints/schemas: https://opastorello.github.io/unifi-api-docs/
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app import config as _cfg
from app import devices as _dev
from app import metrics as _m
from app.services import _http

# Validação de IDs — permite alfanumérico, hifens, underscores, pontos.
# Bloqueamos qualquer coisa que possa causar path traversal ou injeção.
# ':' permitido — host IDs UniFi têm forma '<hex>:<num>' (ex.: ...669C8047:1524255700).
# Sem '/', então '..' isolado é inócuo; _http ainda bloqueia traversal e garante mesmo-host.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,160}$")
_SAFE_INTERVAL = frozenset({"5m", "1h"})
# A UniFi Integration API v1 só expõe autorização de guest no endpoint de
# ação de cliente — NÃO há block/unblock/reconnect/forget (legado, fora da v1).
_SAFE_CLIENT_ACTIONS = frozenset({"AUTHORIZE_GUEST_ACCESS", "UNAUTHORIZE_GUEST_ACCESS"})

SERVICE_VERSION = "2.0.0"


# ── Write gate ─────────────────────────────────────────────────────────────────

def _require_write(device_id: str, level: str = "write") -> dict | None:
    """Retorna dict de erro se o device não permite o nível de escrita; None se permitido.
    level='write' exige mode in {write, admin}; level='admin' exige mode == admin."""
    try:
        dev = _dev.get(device_id)
    except _dev.DeviceNotFoundError:
        # device inexistente — deixa a camada upstream retornar o erro correto
        return None
    mode = getattr(dev, "mode", "read")
    if level == "admin":
        ok = mode == "admin"
    else:
        ok = mode in ("write", "admin")
    if not ok:
        return {
            "erro": True,
            "mensagem": (
                f"device '{device_id}' em modo somente-leitura (mode={mode}); "
                f"operação de {level} bloqueada"
            ),
        }
    return None


def _validate_id(value: str) -> str | None:
    """Retorna o valor sanitizado ou None se inválido."""
    v = (value or "").strip()
    if not v or not _SAFE_ID.match(v):
        return None
    return v


def _connector_prefix(host_id: str) -> str:
    """Monta o prefixo do Cloud Connector para um console."""
    return f"/v1/connector/consoles/{host_id}/network/integration/v1"


def _device_kind(device_id: str) -> str:
    """Tipo do device: 'local' (console direto) ou 'cloud' (Site Manager/Connector). Default cloud."""
    try:
        dev = _dev.get(device_id)
    except _dev.DeviceNotFoundError:
        return "cloud"
    return ((getattr(dev, "extra", None) or {}).get("kind") or "cloud").lower()


# Prefixo da Network Integration v1 quando o device fala DIRETO com o console.
_LOCAL_INTEGRATION_PREFIX = "/proxy/network/integration/v1"


def _resolve_prefix_or_err(device_id: str, host_id: str) -> tuple[str | None, dict | None]:
    """Resolve o prefixo da Network Integration v1, ciente do tipo de device → (prefix, err).

    - device LOCAL (extra.kind=='local'): fala direto com o console; host_id é ignorado.
    - device CLOUD (default): via Cloud Connector; host_id é obrigatório e validado.
    """
    if _device_kind(device_id) == "local":
        return _LOCAL_INTEGRATION_PREFIX, None
    raw = (host_id or "").strip()
    if not raw:
        return None, {"erro": True, "mensagem": "host_id obrigatório para device cloud (use list_hosts)"}
    hid = _validate_id(raw)
    if hid is None:
        return None, {"erro": True, "mensagem": f"host_id inválido: {host_id!r}"}
    return _connector_prefix(hid), None


# Teto de itens p/ auto-paginação — evita varrer infinito num site gigante.
_MAX_PAGED_ITEMS = 5000
_PAGE_SIZE = 200


async def _get_paged(device_id: str, path: str) -> dict:
    """GET com auto-paginação. A UniFi API devolve {offset,limit,count,totalCount,data}.
    Busca todas as páginas (até _MAX_PAGED_ITEMS) e mescla 'data'. Se a resposta não
    for paginada (sem totalCount), repassa como veio — seguro p/ Site Manager.
    """
    first = await _http.get_json(device_id, path, params={"offset": 0, "limit": _PAGE_SIZE})
    if first.get("erro"):
        return first
    total = first.get("totalCount")
    data = first.get("data")
    if not isinstance(data, list) or not isinstance(total, int):
        return first  # não paginado — passa direto
    items = list(data)
    while len(items) < total and len(items) < _MAX_PAGED_ITEMS:
        page = await _http.get_json(
            device_id, path, params={"offset": len(items), "limit": _PAGE_SIZE}
        )
        if page.get("erro"):
            break
        chunk = page.get("data")
        if not isinstance(chunk, list) or not chunk:
            break
        items.extend(chunk)
    return {"data": items, "totalCount": total, "fetched": len(items)}


def service_info() -> dict:
    """Metadados do servidor — não toca a API upstream."""
    return {
        "service": _cfg.SERVER_NAME,
        "version": SERVICE_VERSION,
        "env": _cfg.ENV,
        "devices_configured": _dev.count(),
        "devices": _dev.list_ids(),
        "now": datetime.now(UTC).isoformat(),
    }


async def check_upstream(device_id: str) -> dict:
    """Testa conectividade e autenticação. Cloud → GET /v1/hosts; local → GET /proxy/network/integration/v1/info."""
    path = "/proxy/network/integration/v1/info" if _device_kind(device_id) == "local" else "/v1/hosts"
    data = await _http.get_json(device_id, path)
    if data.get("erro"):
        return data
    return {"device_id": device_id, "kind": _device_kind(device_id), "upstream": "ok"}


# ─── PASSTHROUGH GENÉRICO — Network Integration v1 (cloud OU local) ──────────
#
# Coração do "completo + auto-update": encaminha QUALQUER endpoint da Integration
# v1 (todas as ~73 ops da spec atual e as versões futuras), sem precisar de uma
# tool dedicada por endpoint. Resolve o prefixo conforme o device:
#   - LOCAL  → https://<console>/proxy/network/integration/v1/<subpath>
#   - CLOUD  → https://api.ui.com/v1/connector/consoles/{host_id}/network/integration/v1/<subpath>
# subpath é relativo a .../integration/v1 (ex.: 'sites', 'sites/{siteId}/clients').

# Métodos de escrita aceitos no passthrough de escrita.
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# subpath: segmentos alfanum/_/-/. separados por '/', com query opcional. Sem '..', sem host.
_SAFE_SUBPATH = re.compile(r"^[A-Za-z0-9_.\-/]+(\?[A-Za-z0-9_.\-/=&%,:]*)?$")


def _resolve_integration_path(device_id: str, subpath: str, host_id: str) -> tuple[str | None, dict | None]:
    """Resolve (full_path, err). err é um dict {erro:True} pronto p/ retornar."""
    sp = (subpath or "").strip().lstrip("/")
    if not sp or ".." in sp or not _SAFE_SUBPATH.match(sp):
        return None, {"erro": True, "mensagem": f"subpath inválido: {subpath!r}"}
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return None, err
    return f"{prefix}/{sp}", None


async def integration_get(
    device_id: str, subpath: str, host_id: str = "", paged: bool = True
) -> dict:
    """READ genérico na Network Integration v1 (qualquer endpoint), cloud ou local.

    subpath relativo a .../integration/v1 — ex.: 'sites', 'sites/{siteId}/wifi/broadcasts'.
    paged=True auto-pagina respostas no formato {offset,limit,totalCount,data}.
    """
    full, err = _resolve_integration_path(device_id, subpath, host_id)
    if err:
        return err
    return await (_get_paged(device_id, full) if paged else _http.get_json(device_id, full))


async def integration_write(
    device_id: str,
    subpath: str,
    method: str = "POST",
    body: dict | None = None,
    host_id: str = "",
) -> dict:
    """WRITE genérico na Network Integration v1 (POST/PUT/PATCH/DELETE), cloud ou local.

    Gated por mode (write/admin). subpath relativo a .../integration/v1.
    Ex.: criar SSID → method='POST', subpath='sites/{siteId}/wifi/broadcasts', body={...}.
    """
    m = (method or "POST").strip().upper()
    if m not in _WRITE_METHODS:
        return {"erro": True, "mensagem": f"método inválido: {method!r}. Use {sorted(_WRITE_METHODS)}"}
    gate = _require_write(device_id, "write")
    if gate:
        return gate
    full, err = _resolve_integration_path(device_id, subpath, host_id)
    if err:
        return err
    kw: dict[str, Any] = {}
    if body is not None:
        if not isinstance(body, dict):
            return {"erro": True, "mensagem": "body deve ser objeto JSON (dict)"}
        kw["json"] = body
    return await _http.request_json(device_id, m, full, **kw)


# ─── SITE MANAGER — READ ─────────────────────────────────────────────────────


async def list_hosts(device_id: str) -> dict:
    """Lista todos os consoles (hosts) da conta via Site Manager."""
    return await _http.get_json(device_id, "/v1/hosts")


async def get_host_detail(device_id: str, host_id: str) -> dict:
    """Retorna detalhe de um console específico via Site Manager."""
    hid = _validate_id(host_id)
    if hid is None:
        return {"erro": True, "mensagem": f"host_id inválido: {host_id!r}"}
    return await _http.get_json(device_id, f"/v1/hosts/{hid}")


async def list_sites(device_id: str) -> dict:
    """Lista todos os sites da frota via Site Manager."""
    return await _http.get_json(device_id, "/v1/sites")


async def list_all_devices(device_id: str) -> dict:
    """Lista dispositivos agrupados por console via Site Manager."""
    return await _http.get_json(device_id, "/v1/devices")


def _iter_devices(raw: dict):
    """Itera (host_id, host_name, device) de /v1/devices — tolera agrupado-por-console ou flat."""
    data = raw.get("data") if isinstance(raw, dict) else raw
    if not isinstance(data, list):
        return
    for entry in data:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("devices")
        if isinstance(inner, list):
            host_id = entry.get("hostId") or entry.get("id")
            host_name = entry.get("hostName") or entry.get("name")
            for d in inner:
                if isinstance(d, dict):
                    yield host_id, host_name, d
        else:
            yield entry.get("hostId"), entry.get("hostName"), entry


async def fleet_health_summary(device_id: str, worst_n: int = 10) -> dict:
    """Rollup enxuto da frota: consoles, devices online/offline, clientes e piores sites.

    Agrega server-side a partir de /v1/sites (+ nomes de /v1/hosts, best-effort),
    evitando baixar os MBs de list_sites/list_all_devices/get_isp_metrics no n8n.
    """
    sites_raw = await list_sites(device_id)
    if isinstance(sites_raw, dict) and sites_raw.get("erro"):
        return sites_raw
    sites = sites_raw.get("data") if isinstance(sites_raw, dict) else []
    sites = sites if isinstance(sites, list) else []
    # Nome amigável do site vem do host (reportedState.name) — best-effort.
    host_names: dict[str, Any] = {}
    hosts_raw = await list_hosts(device_id)
    if isinstance(hosts_raw, dict) and not hosts_raw.get("erro"):
        for h in hosts_raw.get("data") or []:
            if not isinstance(h, dict):
                continue
            rs = h.get("reportedState") or {}
            name = rs.get("name") or rs.get("hostname") or h.get("name")
            if h.get("id"):
                host_names[h["id"]] = name
    total_dev = offline_dev = wifi = wired = 0
    host_ids: set = set()
    rows: list[dict] = []
    for s in sites:
        counts = (s.get("statistics") or {}).get("counts") or {}
        td = int(counts.get("totalDevice") or 0)
        od = int(counts.get("offlineDevice") or 0)
        wc = int(counts.get("wifiClient") or 0)
        wd = int(counts.get("wiredClient") or 0)
        total_dev += td
        offline_dev += od
        wifi += wc
        wired += wd
        hid = s.get("hostId")
        if hid:
            host_ids.add(hid)
        name = host_names.get(hid) or (s.get("meta") or {}).get("desc") or s.get("siteId")
        rows.append({
            "site": name, "site_id": s.get("siteId"), "host_id": hid,
            "devices": td, "offline_devices": od,
            "wifi_clients": wc, "wired_clients": wd,
        })
    # ── Camada 3: gauges de dominio (best-effort, nunca quebra a tool) ──
    # rollup global da frota -> .clear() reflete o snapshot atual (series que
    # sumiram desaparecem em vez de congelar no ultimo valor).
    try:
        _m.unifi_clients_connected.clear()
        _m.unifi_sites_offline.clear()
        offline_sites_by_host: dict[str, int] = {}
        for r in rows:
            sid = r["site_id"] or "unknown"
            _m.unifi_clients_connected.labels(type="wifi", site=sid).set(r["wifi_clients"])
            _m.unifi_clients_connected.labels(type="wired", site=sid).set(r["wired_clients"])
            if r["host_id"] and r["offline_devices"] > 0:
                offline_sites_by_host[r["host_id"]] = offline_sites_by_host.get(r["host_id"], 0) + 1
        for hid_k, n in offline_sites_by_host.items():
            _m.unifi_sites_offline.labels(host_id=hid_k).set(n)
    except Exception:
        pass
    worst = sorted(
        (r for r in rows if r["offline_devices"] > 0),
        key=lambda r: r["offline_devices"], reverse=True,
    )[: max(1, worst_n)]
    return {
        "sites_total": len(sites),
        "consoles_total": len(host_ids),
        "devices": {
            "total": total_dev,
            "offline": offline_dev,
            "online": total_dev - offline_dev,
        },
        "clients": {"wifi": wifi, "wired": wired, "total": wifi + wired},
        "sites_with_offline_devices": sum(1 for r in rows if r["offline_devices"] > 0),
        "worst_sites": worst,
    }


async def list_offline_devices(device_id: str) -> dict:
    """Lista, da frota inteira num shot, os devices que NÃO estão online (console+modelo+ip)."""
    raw = await list_all_devices(device_id)
    if isinstance(raw, dict) and raw.get("erro"):
        return raw
    offline: list[dict] = []
    for host_id, host_name, d in _iter_devices(raw):
        status = str(d.get("status") or d.get("state") or "").strip()
        if status and status.lower() != "online":
            offline.append({
                "name": d.get("name"),
                "model": d.get("model"),
                "mac": d.get("mac"),
                "ip": d.get("ip") or d.get("ipAddress"),
                "status": status,
                "host_id": host_id,
                "console": host_name,
            })
    return {"total": len(offline), "offline_devices": offline}


async def get_isp_metrics(device_id: str, interval: str = "5m") -> dict:
    """Retorna métricas ISP (latência, banda, perda, uptime) via Site Manager."""
    ivl = interval if interval in _SAFE_INTERVAL else "5m"
    return await _http.get_json(device_id, f"/v1/isp-metrics/{ivl}")


async def list_sdwan_configs(device_id: str) -> dict:
    """Lista configurações SD-WAN da conta via Site Manager."""
    return await _http.get_json(device_id, "/v1/sd-wan-configs")


async def get_sdwan_config(device_id: str, config_id: str) -> dict:
    """Retorna detalhe de uma configuração SD-WAN via Site Manager."""
    cid = _validate_id(config_id)
    if cid is None:
        return {"erro": True, "mensagem": f"config_id inválido: {config_id!r}"}
    return await _http.get_json(device_id, f"/v1/sd-wan-configs/{cid}")


# ─── CLOUD CONNECTOR — READ ───────────────────────────────────────────────────


async def get_console_sites(device_id: str, host_id: str = "") -> dict:
    """Lista sites de um console (cloud via Connector ou local direto; host_id ignorado p/ local)."""
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _get_paged(device_id, f"{prefix}/sites")


async def get_console_devices(device_id: str, host_id: str, site_id: str) -> dict:
    """Lista dispositivos de um site (cloud via Connector ou local direto; host_id ignorado p/ local)."""
    sid = _validate_id(site_id)
    if sid is None:
        return {"erro": True, "mensagem": f"site_id inválido: {site_id!r}"}
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _get_paged(device_id, f"{prefix}/sites/{sid}/devices")


async def get_device_detail(device_id: str, host_id: str, site_id: str, device_uid: str) -> dict:
    """Retorna detalhe de um dispositivo (cloud via Connector ou local direto; host_id ignorado p/ local)."""
    sid = _validate_id(site_id)
    if sid is None:
        return {"erro": True, "mensagem": f"site_id inválido: {site_id!r}"}
    did = _validate_id(device_uid)
    if did is None:
        return {"erro": True, "mensagem": f"device_uid inválido: {device_uid!r}"}
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _http.get_json(device_id, f"{prefix}/sites/{sid}/devices/{did}")


async def get_console_clients(device_id: str, host_id: str, site_id: str) -> dict:
    """Lista clientes conectados a um site (cloud via Connector ou local direto; host_id ignorado p/ local)."""
    sid = _validate_id(site_id)
    if sid is None:
        return {"erro": True, "mensagem": f"site_id inválido: {site_id!r}"}
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _get_paged(device_id, f"{prefix}/sites/{sid}/clients")


async def get_console_networks(device_id: str, host_id: str, site_id: str) -> dict:
    """Lista redes configuradas num site (cloud via Connector ou local direto; host_id ignorado p/ local)."""
    sid = _validate_id(site_id)
    if sid is None:
        return {"erro": True, "mensagem": f"site_id inválido: {site_id!r}"}
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _get_paged(device_id, f"{prefix}/sites/{sid}/networks")


async def get_console_info(device_id: str, host_id: str = "") -> dict:
    """Retorna informações do console (cloud via Connector ou local direto; host_id ignorado p/ local)."""
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _http.get_json(device_id, f"{prefix}/info")


# ─── CLOUD CONNECTOR — WRITE ──────────────────────────────────────────────────


async def restart_device(device_id: str, host_id: str, site_id: str, device_uid: str) -> dict:
    """Reinicia um dispositivo (cloud via Connector ou local direto; host_id ignorado p/ local)."""
    sid = _validate_id(site_id)
    if sid is None:
        return {"erro": True, "mensagem": f"site_id inválido: {site_id!r}"}
    did = _validate_id(device_uid)
    if did is None:
        return {"erro": True, "mensagem": f"device_uid inválido: {device_uid!r}"}
    gate = _require_write(device_id, "write")
    if gate:
        return gate
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _http.request_json(
        device_id,
        "POST",
        f"{prefix}/sites/{sid}/devices/{did}/actions",
        json={"action": "RESTART"},
    )


async def power_cycle_port(
    device_id: str, host_id: str, site_id: str, device_uid: str, port_idx: int
) -> dict:
    """Power-cycle PoE em uma porta (cloud via Connector ou local direto; host_id ignorado p/ local)."""
    sid = _validate_id(site_id)
    if sid is None:
        return {"erro": True, "mensagem": f"site_id inválido: {site_id!r}"}
    did = _validate_id(device_uid)
    if did is None:
        return {"erro": True, "mensagem": f"device_uid inválido: {device_uid!r}"}
    if port_idx < 1:
        return {"erro": True, "mensagem": "port_idx deve ser >= 1"}
    gate = _require_write(device_id, "write")
    if gate:
        return gate
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _http.request_json(
        device_id,
        "POST",
        f"{prefix}/sites/{sid}/devices/{did}/interfaces/ports/{port_idx}/actions",
        json={"action": "POWER_CYCLE"},
    )


async def client_action(
    device_id: str,
    host_id: str,
    site_id: str,
    client_id: str,
    action: str,
    time_limit_minutes: int | None = None,
    data_usage_limit_mb: int | None = None,
    rx_rate_limit_kbps: int | None = None,
    tx_rate_limit_kbps: int | None = None,
) -> dict:
    """Autoriza ou revoga acesso de guest de um cliente (cloud via Connector ou local direto)."""
    sid = _validate_id(site_id)
    if sid is None:
        return {"erro": True, "mensagem": f"site_id inválido: {site_id!r}"}
    cid = _validate_id(client_id)
    if cid is None:
        return {"erro": True, "mensagem": f"client_id inválido: {client_id!r}"}
    act = (action or "").strip().upper()
    if act not in _SAFE_CLIENT_ACTIONS:
        return {
            "erro": True,
            "mensagem": f"action inválida: {action!r}. Use: {sorted(_SAFE_CLIENT_ACTIONS)}",
        }
    gate = _require_write(device_id, "write")
    if gate:
        return gate
    prefix, err = _resolve_prefix_or_err(device_id, host_id)
    if err:
        return err
    body: dict[str, Any] = {"action": act}
    if time_limit_minutes is not None:
        body["timeLimitMinutes"] = int(time_limit_minutes)
    if data_usage_limit_mb is not None:
        body["dataUsageLimitMBytes"] = int(data_usage_limit_mb)
    if rx_rate_limit_kbps is not None:
        body["rxRateLimitKbps"] = int(rx_rate_limit_kbps)
    if tx_rate_limit_kbps is not None:
        body["txRateLimitKbps"] = int(tx_rate_limit_kbps)
    return await _http.request_json(
        device_id,
        "POST",
        f"{prefix}/sites/{sid}/clients/{cid}/actions",
        json=body,
    )


# ─── DIAGNÓSTICO L1 / HEALTH (Network API legada) ─────────────────────────────
#
# A Integration API v1 (usada acima) é cega p/ topologia física: não expõe
# link speed, PoE real, last_seen nem mapa MAC↔porta. A API legada do Network
# controller (sem o sufixo /integration/v1) tem esses dados. Resolvida conforme
# o device: cloud via Cloud Connector, local direto. Site legado usa o NOME
# interno do site (ex.: "default"), não o UUID.

_LEGACY_SITE_DEFAULT = "default"
# Prefixo da API legada quando o device fala DIRETO com o console.
_LOCAL_LEGACY_PREFIX = "/proxy/network"


def _resolve_legacy_prefix_or_err(device_id: str, host_id: str) -> tuple[str | None, dict | None]:
    """Prefixo da API legada do Network → (prefix, err), ciente do tipo de device.

    - local: /proxy/network (host_id ignorado).
    - cloud: /v1/connector/consoles/{host_id}/network (host_id obrigatório/validado).
    """
    if _device_kind(device_id) == "local":
        return _LOCAL_LEGACY_PREFIX, None
    raw = (host_id or "").strip()
    if not raw:
        return None, {"erro": True, "mensagem": "host_id obrigatório para device cloud (use list_hosts)"}
    hid = _validate_id(raw)
    if hid is None:
        return None, {"erro": True, "mensagem": f"host_id inválido: {host_id!r}"}
    return f"/v1/connector/consoles/{hid}/network", None


def _norm_mac(value: str) -> str:
    """Normaliza MAC p/ 12 hex minúsculos sem separador. '' se não for MAC."""
    raw = re.sub(r"[^0-9A-Fa-f]", "", value or "")
    return raw.lower() if len(raw) == 12 else ""


def _match_device(devs: list[dict], ref: str) -> dict | None:
    """Acha um device na lista stat/device por MAC, nome, _id ou device_id."""
    ref = (ref or "").strip()
    mac = _norm_mac(ref)
    ref_low = ref.lower()
    for d in devs:
        if mac and _norm_mac(str(d.get("mac", ""))) == mac:
            return d
        if ref and (str(d.get("name", "")).lower() == ref_low
                    or str(d.get("_id", "")) == ref
                    or str(d.get("device_id", "")) == ref):
            return d
    return None


async def _legacy_stat(device_id: str, host_id: str, site: str, kind: str) -> dict:
    """GET genérico na API legada: /api/s/{site}/stat/{kind}. Repassa {erro}."""
    snm = _validate_id(site or _LEGACY_SITE_DEFAULT)
    if snm is None:
        return {"erro": True, "mensagem": f"site inválido: {site!r}"}
    prefix, err = _resolve_legacy_prefix_or_err(device_id, host_id)
    if err:
        return err
    return await _http.get_json(device_id, f"{prefix}/api/s/{snm}/stat/{kind}")


def _port_view(p: dict) -> dict:
    """Curadoria de uma entrada de port_table (legado)."""
    speed = p.get("speed") or 0
    up = bool(p.get("up"))
    lldp = [
        x.get("lldp_system_name") or x.get("lldp_chassis_id")
        for x in (p.get("lldp_table") or [])
    ]
    return {
        "port_idx": p.get("port_idx"),
        "up": up,
        "speed_mbps": speed,
        "low_speed": bool(up and 0 < speed < 1000),
        "poe_enable": bool(p.get("poe_enable")),
        "poe_mode": p.get("poe_mode"),
        "poe_good": bool(p.get("poe_good")),
        "poe_power_w": p.get("poe_power"),
        "poe_voltage_v": p.get("poe_voltage"),
        "lldp": [m for m in lldp if m],
    }


async def get_device_diagnostics(
    device_id: str, host_id: str, device_ref: str, site: str = _LEGACY_SITE_DEFAULT
) -> dict:
    """Diagnóstico real de um device (state, last_seen, uplink, link speed, PoE).

    device_ref = MAC ou nome do device (ex.: 'LDA-AP-02' ou 'f4:92:bf:c9:0b:ef').
    """
    if not (device_ref or "").strip():
        return {"erro": True, "mensagem": "device_ref obrigatório (MAC ou nome)"}
    raw = await _legacy_stat(device_id, host_id, site, "device")
    if raw.get("erro"):
        return raw
    devs = raw.get("data") or []
    dev = _match_device(devs, device_ref)
    if dev is None:
        return {"erro": True, "mensagem": f"device {device_ref!r} não encontrado no site"}
    up = dev.get("uplink") or {}
    out: dict[str, Any] = {
        "name": dev.get("name"),
        "mac": dev.get("mac"),
        "model": dev.get("model"),
        "type": dev.get("type"),
        "online": dev.get("state") == 1,
        "state": dev.get("state"),
        "last_seen": dev.get("last_seen"),
        "uptime": dev.get("uptime"),
        "satisfaction": dev.get("satisfaction"),
        "ip": dev.get("ip"),
        "version": dev.get("version"),
        "uplink": {
            "switch_name": up.get("uplink_device_name"),
            "switch_mac": up.get("uplink_mac"),
            "port_idx": up.get("uplink_remote_port"),
            "type": up.get("type"),
        },
    }
    # Enriquecer: speed/PoE reais da porta do switch onde este device sobe.
    sw_mac = _norm_mac(str(up.get("uplink_mac", "")))
    port_idx = up.get("uplink_remote_port")
    if sw_mac and port_idx is not None:
        sw = next((d for d in devs if _norm_mac(str(d.get("mac", ""))) == sw_mac), None)
        if sw:
            port = next(
                (p for p in (sw.get("port_table") or [])
                 if p.get("port_idx") == port_idx),
                None,
            )
            if port:
                pv = _port_view(port)
                out["uplink"]["link_speed_mbps"] = pv["speed_mbps"]
                out["uplink"]["link_degraded"] = pv["low_speed"]
                out["uplink"]["poe_good"] = pv["poe_good"]
                out["uplink"]["poe_power_w"] = pv["poe_power_w"]
    return out


async def resolve_uplink(
    device_id: str, host_id: str, ap_ref: str, site: str = _LEGACY_SITE_DEFAULT
) -> dict:
    """Resolve o uplink de um AP/device → switch + porta (p/ power-cycle dirigido).

    ap_ref = MAC ou nome. Faz a ponte MAC→device_uid (Integration v1) p/ que o
    resultado seja usável direto por power_cycle_port (precisa site_id e
    device_uid no esquema UUID da API v1).
    """
    if not (ap_ref or "").strip():
        return {"erro": True, "mensagem": "ap_ref obrigatório (MAC ou nome)"}
    raw = await _legacy_stat(device_id, host_id, site, "device")
    if raw.get("erro"):
        return raw
    devs = raw.get("data") or []
    ap = _match_device(devs, ap_ref)
    if ap is None:
        return {"erro": True, "mensagem": f"device {ap_ref!r} não encontrado no site"}
    up = ap.get("uplink") or {}
    sw_mac = up.get("uplink_mac")
    port_idx = up.get("uplink_remote_port")
    if not sw_mac or port_idx is None:
        return {
            "erro": True,
            "mensagem": f"{ap.get('name') or ap_ref} sem uplink com fio (wireless/sem dados)",
        }
    # Ponte p/ Integration v1: site UUID + device_uid do switch (por MAC).
    sites = await get_console_sites(device_id, host_id)
    if sites.get("erro"):
        return sites
    site_list = sites.get("data") or []
    if not site_list:
        return {"erro": True, "mensagem": "nenhum site no console (Integration v1)"}
    site_uuid = site_list[0].get("id")
    cd = await get_console_devices(device_id, host_id, site_uuid)
    if cd.get("erro"):
        return cd
    sw_mac_n = _norm_mac(sw_mac)
    switch = next(
        (d for d in (cd.get("data") or [])
         if _norm_mac(str(d.get("macAddress", ""))) == sw_mac_n),
        None,
    )
    return {
        "ap_name": ap.get("name"),
        "ap_mac": ap.get("mac"),
        "ap_online": ap.get("state") == 1,
        "switch_name": up.get("uplink_device_name"),
        "switch_mac": sw_mac,
        "switch_uid": switch.get("id") if switch else None,
        "site_id": site_uuid,
        "host_id": host_id,
        "port_idx": port_idx,
    }


async def get_port_health(
    device_id: str, host_id: str, switch_ref: str, site: str = _LEGACY_SITE_DEFAULT
) -> dict:
    """Saúde das portas de um switch (speed, PoE, LLDP, flags de degradação).

    switch_ref = MAC ou nome do switch.
    """
    if not (switch_ref or "").strip():
        return {"erro": True, "mensagem": "switch_ref obrigatório (MAC ou nome)"}
    raw = await _legacy_stat(device_id, host_id, site, "device")
    if raw.get("erro"):
        return raw
    devs = raw.get("data") or []
    sw = _match_device(devs, switch_ref)
    if sw is None:
        return {"erro": True, "mensagem": f"switch {switch_ref!r} não encontrado no site"}
    ports = [_port_view(p) for p in (sw.get("port_table") or [])]
    return {
        "switch_name": sw.get("name"),
        "switch_mac": sw.get("mac"),
        "online": sw.get("state") == 1,
        "ports": ports,
        "degraded_ports": [p["port_idx"] for p in ports if p["low_speed"]],
    }


async def get_site_health(
    device_id: str, host_id: str, site: str = _LEGACY_SITE_DEFAULT
) -> dict:
    """Saúde do site: subsistemas, contagem de devices, wifi score, wifi-doctor.

    Agrega os sinais que alimentam o painel 'Cables & Power / Anomaly' (esse
    painel branded não tem endpoint próprio na API proxiada).
    """
    health = await _legacy_stat(device_id, host_id, site, "health")
    if health.get("erro"):
        return health
    subs = health.get("data") or []
    subsystems = [
        {
            "subsystem": s.get("subsystem"),
            "status": s.get("status"),
            "num_disconnected": s.get("num_disconnected"),
            "num_adopted": s.get("num_adopted"),
            "num_pending": s.get("num_pending"),
        }
        for s in subs
    ]
    # Camada 3: 1=warning/error, 0=ok por subsistema deste console (best-effort).
    try:
        for s in subsystems:
            subsys = s.get("subsystem")
            if not subsys:
                continue
            _m.unifi_site_subsystem_warning.labels(host_id=host_id, subsystem=subsys).set(
                1 if s.get("status") in ("warning", "error") else 0
            )
    except Exception:
        pass
    out: dict[str, Any] = {
        "subsystems": subsystems,
        "warnings": [
            s["subsystem"] for s in subsystems
            if s.get("status") in ("warning", "error")
        ],
        "disconnected_total": sum(
            int(s.get("num_disconnected") or 0) for s in subsystems
        ),
    }
    # widget/health — wifi score + status de devices (best-effort).
    widget = await _legacy_stat(device_id, host_id, site, "widget/health")
    if not widget.get("erro"):
        wd = (widget.get("data") or [{}])[0]
        out["devices_status"] = wd.get("devices_status")
        out["wifi_score"] = wd.get("wifi_score")
        out["wifi_utilization"] = wd.get("average_wifi_utilization")
    # v2 aggregated-dashboard.wifi_doctor — motor de diagnóstico (best-effort).
    prefix, _err = _resolve_legacy_prefix_or_err(device_id, host_id)
    snm = _validate_id(site or _LEGACY_SITE_DEFAULT)
    if prefix and snm:
        agg = await _http.get_json(
            device_id,
            f"{prefix}/v2/api/site/{snm}/aggregated-dashboard",
        )
        if not agg.get("erro"):
            doctor = (agg.get("wifi_doctor") or {})
            out["wifi_doctor"] = [
                {
                    "id": a.get("id"),
                    "status": a.get("optimization_status"),
                    "upgradable_devices": len(a.get("upgradable_devices") or []),
                }
                for a in (doctor.get("actions") or [])
            ]
    return out


async def power_cycle_ap(
    device_id: str, host_id: str, ap_ref: str, site: str = _LEGACY_SITE_DEFAULT
) -> dict:
    """Power-cycle PoE do uplink de um AP — resolve switch+porta sozinho.

    Compõe resolve_uplink + power_cycle_port. ap_ref = MAC ou nome do AP.
    Pensada p/ uso autônomo por agente (não precisa saber a porta).
    """
    if not (ap_ref or "").strip():
        return {"erro": True, "mensagem": "ap_ref obrigatório (MAC ou nome)"}
    gate = _require_write(device_id, "write")
    if gate:
        return gate
    res = await resolve_uplink(device_id, host_id, ap_ref, site)
    if res.get("erro"):
        return res
    if not res.get("switch_uid") or res.get("site_id") is None:
        return {
            "erro": True,
            "mensagem": (
                f"uplink de {res.get('ap_name') or ap_ref} resolvido "
                f"(switch {res.get('switch_name')} porta {res.get('port_idx')}) "
                "mas switch não mapeado na Integration v1 — power-cycle indisponível"
            ),
        }
    result = await power_cycle_port(
        device_id, host_id, res["site_id"], res["switch_uid"], res["port_idx"]
    )
    return {"resolved": res, "power_cycle": result}
