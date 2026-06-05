"""Rotas REST — espelham as tools MCP do UniFi Site Manager Cloud.

Mesma lógica, dois protocolos: REST aqui, MCP em mcp_server.py.
Não duplicar lógica — toda chamada delega para app/services/unifi.py.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import config as _cfg
from app import devices as _dev
from app import metrics as _m
from app.ratelimit import limiter
from app.services import unifi

router = APIRouter(prefix="/api/unifi", tags=["unifi"])

_HOST_EXAMPLE = "abc123def456"
_SITE_EXAMPLE = "site-abc123"
_DEVICE_EXAMPLE = "device-abc123"
_CLIENT_EXAMPLE = "client-abc123"


# ─── Request body models ────────────────────────────────────────────────────


class RestartDeviceRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "host_id": _HOST_EXAMPLE,
                "site_id": _SITE_EXAMPLE,
                "device_uid": _DEVICE_EXAMPLE,
            }
        }
    }
    host_id: str = Field(..., description="ID do console UniFi", examples=[_HOST_EXAMPLE])
    site_id: str = Field(..., description="ID do site", examples=[_SITE_EXAMPLE])
    device_uid: str = Field(..., description="ID do dispositivo", examples=[_DEVICE_EXAMPLE])


class PowerCyclePortRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "host_id": _HOST_EXAMPLE,
                "site_id": _SITE_EXAMPLE,
                "device_uid": _DEVICE_EXAMPLE,
                "port_idx": 3,
            }
        }
    }
    host_id: str = Field(..., description="ID do console UniFi", examples=[_HOST_EXAMPLE])
    site_id: str = Field(..., description="ID do site", examples=[_SITE_EXAMPLE])
    device_uid: str = Field(..., description="ID do dispositivo", examples=[_DEVICE_EXAMPLE])
    port_idx: int = Field(..., description="Índice da porta PoE (1-based)", examples=[3])


class ClientActionRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "host_id": _HOST_EXAMPLE,
                "site_id": _SITE_EXAMPLE,
                "client_id": _CLIENT_EXAMPLE,
                "action": "AUTHORIZE_GUEST_ACCESS",
            }
        }
    }
    host_id: str = Field(..., description="ID do console UniFi", examples=[_HOST_EXAMPLE])
    site_id: str = Field(..., description="ID do site", examples=[_SITE_EXAMPLE])
    client_id: str = Field(..., description="ID do cliente", examples=[_CLIENT_EXAMPLE])
    action: str = Field(
        ...,
        description="AUTHORIZE_GUEST_ACCESS ou UNAUTHORIZE_GUEST_ACCESS",
        examples=["AUTHORIZE_GUEST_ACCESS"],
    )
    time_limit_minutes: int | None = Field(default=None, description="Opcional: minutos")
    data_usage_limit_mb: int | None = Field(default=None, description="Opcional: dados MB")
    rx_rate_limit_kbps: int | None = Field(default=None, description="Opcional: download kbps")
    tx_rate_limit_kbps: int | None = Field(default=None, description="Opcional: upload kbps")


# ─── Registry / info ────────────────────────────────────────────────────────


@router.get("/devices-list", summary="Lista devices disponíveis")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def devices_list(request: Request):
    _m.rest_calls_total.labels(endpoint="/api/unifi/devices-list", result="success").inc()
    return {"devices": _dev.list_safe(), "total": _dev.count()}


@router.get("/info", summary="Metadados do servidor")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def info(request: Request):
    _m.rest_calls_total.labels(endpoint="/api/unifi/info", result="success").inc()
    return unifi.service_info()


@router.get("/{device_id}/check", summary="Verifica conectividade com Site Manager")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def check_device(request: Request, device_id: str):
    result = await unifi.check_upstream(device_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/check",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


# ─── Site Manager — read ─────────────────────────────────────────────────────


@router.get("/{device_id}/hosts", summary="Lista consoles (hosts) da conta")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def get_hosts(request: Request, device_id: str):
    result = await unifi.list_hosts(device_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/hosts",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get("/{device_id}/hosts/{host_id}", summary="Detalhe de um console")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def get_host_detail(request: Request, device_id: str, host_id: str):
    result = await unifi.get_host_detail(device_id, host_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/hosts/detail",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get("/{device_id}/sites", summary="Lista sites da frota")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def get_sites(request: Request, device_id: str):
    result = await unifi.list_sites(device_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/sites",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get("/{device_id}/all-devices", summary="Lista todos os dispositivos da frota")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def get_all_devices(request: Request, device_id: str):
    result = await unifi.list_all_devices(device_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/all-devices",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get("/{device_id}/fleet-health", summary="Rollup de saúde da frota")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def fleet_health(request: Request, device_id: str, worst_n: int = 10):
    result = await unifi.fleet_health_summary(device_id, worst_n)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/fleet-health",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get("/{device_id}/offline-devices", summary="Devices offline da frota")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def offline_devices(request: Request, device_id: str):
    result = await unifi.list_offline_devices(device_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/offline-devices",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get("/{device_id}/isp-metrics", summary="Métricas ISP (latência, banda, perda)")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def get_isp_metrics(request: Request, device_id: str, interval: str = "5m"):
    result = await unifi.get_isp_metrics(device_id, interval)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/isp-metrics",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get("/{device_id}/sdwan-configs", summary="Lista configurações SD-WAN")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def get_sdwan_configs(request: Request, device_id: str):
    result = await unifi.list_sdwan_configs(device_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/sdwan-configs",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get("/{device_id}/sdwan-configs/{config_id}", summary="Detalhe de configuração SD-WAN")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def get_sdwan_config(request: Request, device_id: str, config_id: str):
    result = await unifi.get_sdwan_config(device_id, config_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/sdwan-configs/detail",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


# ─── Cloud Connector — read ──────────────────────────────────────────────────


@router.get(
    "/{device_id}/consoles/{host_id}/sites",
    summary="Sites de um console (Connector)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def console_sites(request: Request, device_id: str, host_id: str):
    result = await unifi.get_console_sites(device_id, host_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/consoles/sites",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get(
    "/{device_id}/consoles/{host_id}/sites/{site_id}/devices",
    summary="Dispositivos de um site (Connector)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def console_devices(request: Request, device_id: str, host_id: str, site_id: str):
    result = await unifi.get_console_devices(device_id, host_id, site_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/consoles/devices",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get(
    "/{device_id}/consoles/{host_id}/sites/{site_id}/devices/{device_uid}",
    summary="Detalhe de dispositivo (Connector)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def console_device_detail(
    request: Request, device_id: str, host_id: str, site_id: str, device_uid: str
):
    result = await unifi.get_device_detail(device_id, host_id, site_id, device_uid)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/consoles/device-detail",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get(
    "/{device_id}/consoles/{host_id}/sites/{site_id}/clients",
    summary="Clientes de um site (Connector)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def console_clients(request: Request, device_id: str, host_id: str, site_id: str):
    result = await unifi.get_console_clients(device_id, host_id, site_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/consoles/clients",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get(
    "/{device_id}/consoles/{host_id}/sites/{site_id}/networks",
    summary="Redes de um site (Connector)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def console_networks(request: Request, device_id: str, host_id: str, site_id: str):
    result = await unifi.get_console_networks(device_id, host_id, site_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/consoles/networks",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get(
    "/{device_id}/consoles/{host_id}/info",
    summary="Informações de um console (Connector)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def console_info(request: Request, device_id: str, host_id: str):
    result = await unifi.get_console_info(device_id, host_id)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/consoles/info",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


# ─── Cloud Connector — write ─────────────────────────────────────────────────


@router.post("/{device_id}/restart-device", summary="Reinicia dispositivo via Connector")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def restart_device(request: Request, device_id: str, body: RestartDeviceRequest):
    result = await unifi.restart_device(
        device_id, body.host_id, body.site_id, body.device_uid
    )
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/restart-device",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.post("/{device_id}/power-cycle-port", summary="Power-cycle PoE via Connector")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def power_cycle_port(request: Request, device_id: str, body: PowerCyclePortRequest):
    result = await unifi.power_cycle_port(
        device_id, body.host_id, body.site_id, body.device_uid, body.port_idx
    )
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/power-cycle-port",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.post("/{device_id}/client-action", summary="Ação em cliente via Connector")
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def do_client_action(request: Request, device_id: str, body: ClientActionRequest):
    result = await unifi.client_action(
        device_id, body.host_id, body.site_id, body.client_id, body.action,
        body.time_limit_minutes, body.data_usage_limit_mb,
        body.rx_rate_limit_kbps, body.tx_rate_limit_kbps,
    )
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/client-action",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


# ─── Diagnóstico L1 / health (Network API legada via Connector) ──────────────


class PowerCycleApRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {"host_id": _HOST_EXAMPLE, "ap_ref": "LDA-AP-02",
                        "site": "default"}
        }
    }
    host_id: str = Field(..., description="ID do console UniFi", examples=[_HOST_EXAMPLE])
    ap_ref: str = Field(..., description="MAC ou nome do AP", examples=["LDA-AP-02"])
    site: str = Field(default="default", description="Nome interno do site",
                       examples=["default"])


@router.get(
    "/{device_id}/consoles/{host_id}/device-diagnostics",
    summary="Diagnóstico de device (estado, uplink, link speed, PoE)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def device_diagnostics(
    request: Request, device_id: str, host_id: str, ref: str, site: str = "default"
):
    result = await unifi.get_device_diagnostics(device_id, host_id, ref, site)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/device-diagnostics",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get(
    "/{device_id}/consoles/{host_id}/resolve-uplink",
    summary="Resolve uplink de um AP → switch + porta",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def resolve_uplink(
    request: Request, device_id: str, host_id: str, ap: str, site: str = "default"
):
    result = await unifi.resolve_uplink(device_id, host_id, ap, site)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/resolve-uplink",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get(
    "/{device_id}/consoles/{host_id}/port-health",
    summary="Saúde das portas de um switch",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def port_health(
    request: Request, device_id: str, host_id: str, switch: str, site: str = "default"
):
    result = await unifi.get_port_health(device_id, host_id, switch, site)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/port-health",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.get(
    "/{device_id}/consoles/{host_id}/site-health",
    summary="Saúde do site (subsistemas, devices, wifi score, wifi-doctor)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def site_health(
    request: Request, device_id: str, host_id: str, site: str = "default"
):
    result = await unifi.get_site_health(device_id, host_id, site)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/site-health",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.post(
    "/{device_id}/power-cycle-ap",
    summary="Power-cycle PoE do uplink de um AP (resolve switch+porta)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def do_power_cycle_ap(
    request: Request, device_id: str, body: PowerCycleApRequest
):
    result = await unifi.power_cycle_ap(
        device_id, body.host_id, body.ap_ref, body.site
    )
    pc = result.get("power_cycle")
    failed = result.get("erro") or (isinstance(pc, dict) and pc.get("erro"))
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/power-cycle-ap",
        result="invalid" if failed else "success",
    ).inc()
    return result


# ─── Integration v1 — passthrough genérico (cloud ou local) ──────────────────


class IntegrationWriteRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "subpath": "sites/site-abc123/wifi/broadcasts",
                "method": "POST",
                "body": {"name": "IoT", "enabled": True},
                "host_id": _HOST_EXAMPLE,
            }
        }
    }
    subpath: str = Field(..., description="Endpoint relativo a .../integration/v1",
                         examples=["sites/site-abc123/clients"])
    method: str = Field("POST", description="POST | PUT | PATCH | DELETE", examples=["POST"])
    body: dict | None = Field(None, description="Corpo JSON da requisição")
    host_id: str = Field("", description="host_id (cloud); vazio p/ device local",
                         examples=[_HOST_EXAMPLE])


@router.get(
    "/{device_id}/integration",
    summary="GET genérico na Network Integration v1 (cloud ou local)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def integration_get(
    request: Request, device_id: str, subpath: str, host_id: str = "", paged: bool = True
):
    result = await unifi.integration_get(device_id, subpath, host_id, paged)
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/integration",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result


@router.post(
    "/{device_id}/integration",
    summary="POST/PUT/PATCH/DELETE genérico na Integration v1 (gated por mode)",
)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def integration_write(
    request: Request, device_id: str, body: IntegrationWriteRequest
):
    result = await unifi.integration_write(
        device_id, body.subpath, body.method, body.body, body.host_id
    )
    _m.rest_calls_total.labels(
        endpoint="/api/unifi/integration",
        result="invalid" if result.get("erro") else "success",
    ).inc()
    return result
