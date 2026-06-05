"""Servidor MCP — PADRÃO DE AUTORIA DE TOOLS (vale p/ todos os MCPs do monorepo).

Toda tool DEVE seguir este checklist (enforçado por tests/test_mcp_tools.py):

  1. Nome `verbo_substantivo` em snake_case  (ex.: list_users, disable_device).
  2. Docstring de 1 linha, imperativa e específica = a **descrição** exposta ao
     LLM via MCP. Nunca deixar tool sem docstring.
  3. Todo parâmetro tipado e anotado com
     `Annotated[T, Field(description="...", examples=[...])]`.
  4. Anotação de tipo de retorno (`dict`/Pydantic) → structured output.
  5. `@mcp.tool(annotations=..., tags=...)`:
       - `readOnlyHint=True`     → consulta, não muta nada
       - `destructiveHint=True`  → remoção/ação irreversível
       - `idempotentHint=True`   → repetir a chamada não muda o efeito
       - `openWorldHint=True`    → fala com a API externa de IT Ops
       - `tags={"read"|"write"|"admin"}` p/ filtragem/visibilidade
  6. Métrica obrigatória via `_instrument(tool, result, client)` — NÃO fazer
     manual; usar o helper abaixo que conta calls, duração e in_progress.
  7. Lógica real mora em `services/` (puro). A tool só adapta entrada/saída.

Multi-target: toda tool que fala com upstream recebe `device_id` como primeiro
param. O agent obtém a lista de devices via `list_devices`.

Contrato de erro: falha esperada (validação, não encontrado) →
retornar `{"erro": True, "mensagem": "..."}` (result=invalid).
Falha inesperada → `raise ToolError("...")` (result=error) p/ não vazar stack.
"""
import time
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from app import devices as _dev
from app import metrics as _m
from app.services import unifi

mcp = FastMCP("unifi")

_DEFAULT_CLIENT = "unknown"

_DEVICE_ID_FIELD = Field(
    description="ID do device (conta cloud UniFi) — ver list_devices",
    examples=["unifi-cloud"],
)
_HOST_ID_FIELD = Field(
    description="ID do console UniFi (host_id retornado por list_hosts)",
    examples=["abc123def456"],
)
_HOST_ID_OPT_FIELD = Field(
    description="host_id do console — obrigatório p/ device cloud; deixe vazio p/ device local",
    examples=["abc123def456", ""],
)
_SITE_ID_FIELD = Field(
    description="ID do site no console (siteId retornado por get_console_sites)",
    examples=["site-abc123"],
)
_DEVICE_UID_FIELD = Field(
    description="ID do dispositivo no console (id retornado por get_console_devices)",
    examples=["device-abc123"],
)


class _ToolTimer:
    """Context manager que instrumenta uma tool call (counter + histogram + gauge)."""

    __slots__ = ("_tool", "_client", "_start")

    def __init__(self, tool: str, client: str = _DEFAULT_CLIENT):
        self._tool = tool
        self._client = client
        self._start: float = 0

    def __enter__(self):
        self._start = time.perf_counter()
        _m.mcp_calls_in_progress.labels(tool=self._tool).inc()
        return self

    def __exit__(self, *_):
        _m.mcp_calls_in_progress.labels(tool=self._tool).dec()
        _m.mcp_call_duration_seconds.labels(tool=self._tool).observe(
            time.perf_counter() - self._start
        )

    def record(self, result: str) -> None:
        _m.mcp_calls_total.labels(tool=self._tool, result=result, client=self._client).inc()


def _instrument(tool: str, client: str = _DEFAULT_CLIENT) -> _ToolTimer:
    return _ToolTimer(tool, client)


# ───────────────────────── DISCOVERY ───────────────────────────────────────────

@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": False},
    tags={"read"},
)
async def list_devices() -> dict:
    """Lista os devices (contas cloud UniFi) disponíveis neste MCP sem expor credenciais."""
    with _instrument("list_devices") as t:
        result = {"devices": _dev.list_safe(), "total": _dev.count()}
        t.record("success")
    return result


# ───────────────────────── SERVICE INFO ────────────────────────────────────────

@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": False},
    tags={"read"},
)
async def service_info() -> dict:
    """Retorna versão, ambiente e devices configurados do servidor UniFi MCP."""
    with _instrument("service_info") as t:
        result = unifi.service_info()
        t.record("success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def check_upstream(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
) -> dict:
    """Verifica conectividade e autenticação com a API UniFi Site Manager."""
    with _instrument("check_upstream") as t:
        result = await unifi.check_upstream(device_id)
        t.record("invalid" if result.get("erro") else "success")
    return result


# ───────────────────────── SITE MANAGER — READ ─────────────────────────────────

@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def list_hosts(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
) -> dict:
    """Lista todos os consoles UniFi (hosts) da conta com tipo, IP, owner e estado."""
    with _instrument("list_hosts") as t:
        try:
            result = await unifi.list_hosts(device_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"list_hosts falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_host_detail(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    host_id: Annotated[str, _HOST_ID_FIELD],
) -> dict:
    """Retorna detalhe de um console UniFi (reportedState, userData, ipAddress, owner)."""
    with _instrument("get_host_detail") as t:
        try:
            result = await unifi.get_host_detail(device_id, host_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_host_detail falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def list_sites(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
) -> dict:
    """Lista todos os sites da frota com nome, timezone e contadores de dispositivos."""
    with _instrument("list_sites") as t:
        try:
            result = await unifi.list_sites(device_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"list_sites falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def list_all_devices(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
) -> dict:
    """Lista dispositivos de toda a frota agrupados por console (id, mac, name, model, ip)."""
    with _instrument("list_all_devices") as t:
        try:
            result = await unifi.list_all_devices(device_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"list_all_devices falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def fleet_health_summary(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    worst_n: Annotated[
        int,
        Field(
            default=10,
            description="Quantos piores sites (por devices offline) retornar",
            examples=[10],
        ),
    ] = 10,
) -> dict:
    """Rollup enxuto da frota: consoles, devices online/offline, clientes e piores sites."""
    with _instrument("fleet_health_summary") as t:
        try:
            result = await unifi.fleet_health_summary(device_id, worst_n)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"fleet_health_summary falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def list_offline_devices(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
) -> dict:
    """Lista os devices da frota que não estão online num único payload (console, modelo, ip)."""
    with _instrument("list_offline_devices") as t:
        try:
            result = await unifi.list_offline_devices(device_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"list_offline_devices falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_isp_metrics(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    interval: Annotated[
        str,
        Field(
            description="Intervalo de agregação: '5m' (5 minutos) ou '1h' (1 hora)",
            examples=["5m"],
        ),
    ] = "5m",
) -> dict:
    """Retorna métricas ISP (latência, banda, perda de pacotes, uptime) via Site Manager."""
    with _instrument("get_isp_metrics") as t:
        try:
            result = await unifi.get_isp_metrics(device_id, interval)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_isp_metrics falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def list_sdwan_configs(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
) -> dict:
    """Lista configurações SD-WAN da conta UniFi via Site Manager."""
    with _instrument("list_sdwan_configs") as t:
        try:
            result = await unifi.list_sdwan_configs(device_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"list_sdwan_configs falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_sdwan_config(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    config_id: Annotated[
        str,
        Field(
            description="ID da configuração SD-WAN (retornado por list_sdwan_configs)",
            examples=["sdwan-cfg-abc123"],
        ),
    ],
) -> dict:
    """Retorna detalhe de uma configuração SD-WAN específica via Site Manager."""
    with _instrument("get_sdwan_config") as t:
        try:
            result = await unifi.get_sdwan_config(device_id, config_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_sdwan_config falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


# ───────────────────────── CLOUD CONNECTOR — READ ──────────────────────────────

@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_console_sites(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Lista sites de um console UniFi (cloud via Connector ou local direto)."""
    with _instrument("get_console_sites") as t:
        try:
            result = await unifi.get_console_sites(device_id, host_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_console_sites falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_console_devices(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    site_id: Annotated[str, _SITE_ID_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Lista dispositivos de um site (cloud ou local): modelo, firmware, status, IP, MAC."""
    with _instrument("get_console_devices") as t:
        try:
            result = await unifi.get_console_devices(device_id, host_id, site_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_console_devices falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_device_detail(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    site_id: Annotated[str, _SITE_ID_FIELD],
    device_uid: Annotated[str, _DEVICE_UID_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Retorna detalhe de um dispositivo (cloud ou local): portas, PoE, radio, uptime."""
    with _instrument("get_device_detail") as t:
        try:
            result = await unifi.get_device_detail(device_id, host_id, site_id, device_uid)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_device_detail falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_console_clients(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    site_id: Annotated[str, _SITE_ID_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Lista clientes conectados a um site (cloud ou local): hostname, IP, MAC, sinal."""
    with _instrument("get_console_clients") as t:
        try:
            result = await unifi.get_console_clients(device_id, host_id, site_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_console_clients falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_console_networks(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    site_id: Annotated[str, _SITE_ID_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Lista redes e VLANs configuradas num site (cloud ou local)."""
    with _instrument("get_console_networks") as t:
        try:
            result = await unifi.get_console_networks(device_id, host_id, site_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_console_networks falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_console_info(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Retorna informações de um console UniFi (cloud ou local): versão, capacidades."""
    with _instrument("get_console_info") as t:
        try:
            result = await unifi.get_console_info(device_id, host_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_console_info falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


# ───────────────────────── CLOUD CONNECTOR — WRITE ─────────────────────────────

@mcp.tool(
    annotations={"idempotentHint": True, "openWorldHint": True},
    tags={"write"},
)
async def restart_device(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    site_id: Annotated[str, _SITE_ID_FIELD],
    device_uid: Annotated[str, _DEVICE_UID_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Reinicia um dispositivo UniFi (cloud via Connector ou local direto)."""
    with _instrument("restart_device") as t:
        try:
            result = await unifi.restart_device(device_id, host_id, site_id, device_uid)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"restart_device falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"idempotentHint": True, "openWorldHint": True},
    tags={"write"},
)
async def power_cycle_port(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    site_id: Annotated[str, _SITE_ID_FIELD],
    device_uid: Annotated[str, _DEVICE_UID_FIELD],
    port_idx: Annotated[
        int,
        Field(description="Índice da porta PoE (1-based)", examples=[3]),
    ],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Executa power-cycle PoE em porta de switch (cloud ou local) — reinicia o device PoE."""
    with _instrument("power_cycle_port") as t:
        try:
            result = await unifi.power_cycle_port(device_id, host_id, site_id, device_uid, port_idx)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"power_cycle_port falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"destructiveHint": True, "openWorldHint": True},
    tags={"write"},
)
async def client_action(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    site_id: Annotated[str, _SITE_ID_FIELD],
    client_id: Annotated[
        str,
        Field(
            description="ID do cliente (retornado por get_console_clients)",
            examples=["client-abc123"],
        ),
    ],
    action: Annotated[
        str,
        Field(
            description="AUTHORIZE_GUEST_ACCESS ou UNAUTHORIZE_GUEST_ACCESS",
            examples=["AUTHORIZE_GUEST_ACCESS"],
        ),
    ],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
    time_limit_minutes: Annotated[
        int | None,
        Field(default=None, description="Opcional: minutos de autorização do guest",
              examples=[60]),
    ] = None,
    data_usage_limit_mb: Annotated[
        int | None,
        Field(default=None, description="Opcional: limite de dados do guest (MB)",
              examples=[1024]),
    ] = None,
    rx_rate_limit_kbps: Annotated[
        int | None,
        Field(default=None, description="Opcional: limite de download do guest (kbps)",
              examples=[10000]),
    ] = None,
    tx_rate_limit_kbps: Annotated[
        int | None,
        Field(default=None, description="Opcional: limite de upload do guest (kbps)",
              examples=[5000]),
    ] = None,
) -> dict:
    """Autoriza ou revoga o acesso de guest de um cliente (cloud ou local, portal cativo)."""
    with _instrument("client_action") as t:
        try:
            result = await unifi.client_action(
                device_id, host_id, site_id, client_id, action,
                time_limit_minutes, data_usage_limit_mb,
                rx_rate_limit_kbps, tx_rate_limit_kbps,
            )
        except Exception as exc:
            t.record("error")
            raise ToolError(f"client_action falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


# ───────────────────────── DIAGNÓSTICO L1 / HEALTH ─────────────────────────────
# Via API legada do Network proxiada pelo Cloud Connector — expõe link speed,
# PoE real, last_seen, mapa MAC↔porta e health (a Integration v1 é cega nisso).

_AP_REF_FIELD = Field(
    description="MAC ou nome do device/AP (ex.: 'LDA-AP-02' ou 'f4:92:bf:c9:0b:ef')",
    examples=["LDA-AP-02"],
)
_SWITCH_REF_FIELD = Field(
    description="MAC ou nome do switch (ex.: 'LDA-SW01' ou '74:83:c2:06:19:bc')",
    examples=["LDA-SW01"],
)
_LEGACY_SITE_FIELD = Field(
    description="Nome interno do site no console (não o UUID). Default: default",
    examples=["default"],
)


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_device_diagnostics(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    device_ref: Annotated[str, _AP_REF_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
    site: Annotated[str, _LEGACY_SITE_FIELD] = "default",
) -> dict:
    """Diagnostica um device: estado real, last_seen, uplink, link speed e PoE."""
    with _instrument("get_device_diagnostics") as t:
        try:
            result = await unifi.get_device_diagnostics(
                device_id, host_id, device_ref, site
            )
        except Exception as exc:
            t.record("error")
            raise ToolError(
                f"get_device_diagnostics falhou: {type(exc).__name__}"
            ) from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def resolve_uplink(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    ap_ref: Annotated[str, _AP_REF_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
    site: Annotated[str, _LEGACY_SITE_FIELD] = "default",
) -> dict:
    """Resolve o uplink de um AP em switch + porta (mapa MAC↔porta via LLDP)."""
    with _instrument("resolve_uplink") as t:
        try:
            result = await unifi.resolve_uplink(device_id, host_id, ap_ref, site)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"resolve_uplink falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_port_health(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    switch_ref: Annotated[str, _SWITCH_REF_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
    site: Annotated[str, _LEGACY_SITE_FIELD] = "default",
) -> dict:
    """Lista a saúde das portas de um switch (speed, PoE, LLDP, degradação)."""
    with _instrument("get_port_health") as t:
        try:
            result = await unifi.get_port_health(device_id, host_id, switch_ref, site)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_port_health falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def get_site_health(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
    site: Annotated[str, _LEGACY_SITE_FIELD] = "default",
) -> dict:
    """Resume a saúde do site: subsistemas, devices, wifi score e wifi-doctor."""
    with _instrument("get_site_health") as t:
        try:
            result = await unifi.get_site_health(device_id, host_id, site)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"get_site_health falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"idempotentHint": True, "openWorldHint": True},
    tags={"write"},
)
async def power_cycle_ap(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    ap_ref: Annotated[str, _AP_REF_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
    site: Annotated[str, _LEGACY_SITE_FIELD] = "default",
) -> dict:
    """Reinicia um AP via power-cycle PoE do seu uplink (resolve switch+porta)."""
    with _instrument("power_cycle_ap") as t:
        try:
            result = await unifi.power_cycle_ap(device_id, host_id, ap_ref, site)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"power_cycle_ap falhou: {type(exc).__name__}") from exc
        pc = result.get("power_cycle")
        failed = result.get("erro") or (
            isinstance(pc, dict) and pc.get("erro")
        )
        t.record("invalid" if failed else "success")
    return result


# ───────────────────────── INTEGRATION v1 — PASSTHROUGH ────────────────────────
# Acesso genérico a QUALQUER endpoint da Network Integration v1 (cloud OU local),
# cobrindo as ~73 operações da spec e as versões futuras sem novas tools. Consulte
# o catálogo de endpoints/schemas em https://opastorello.github.io/unifi-api-docs/

_SUBPATH_FIELD = Field(
    description=(
        "Endpoint relativo a .../integration/v1 (ex.: 'sites', "
        "'sites/{siteId}/clients', 'sites/{siteId}/wifi/broadcasts')"
    ),
    examples=["sites", "sites/abc123/clients"],
)
@mcp.tool(
    annotations={"readOnlyHint": True, "openWorldHint": True},
    tags={"read"},
)
async def integration_get(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    subpath: Annotated[str, _SUBPATH_FIELD],
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
    paged: Annotated[
        bool,
        Field(description="Auto-paginar respostas {offset,limit,totalCount,data}", examples=[True]),
    ] = True,
) -> dict:
    """Faz GET em qualquer endpoint da Network Integration v1 (cloud ou local)."""
    with _instrument("integration_get") as t:
        try:
            result = await unifi.integration_get(device_id, subpath, host_id, paged)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"integration_get falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result


@mcp.tool(
    annotations={"destructiveHint": True, "openWorldHint": True},
    tags={"write"},
)
async def integration_write(
    device_id: Annotated[str, _DEVICE_ID_FIELD],
    subpath: Annotated[str, _SUBPATH_FIELD],
    method: Annotated[
        str,
        Field(description="Método HTTP de escrita", examples=["POST", "PUT", "PATCH", "DELETE"]),
    ] = "POST",
    body: Annotated[
        dict | None,
        Field(default=None, description="Corpo JSON da requisição", examples=[{"name": "IoT"}]),
    ] = None,
    host_id: Annotated[str, _HOST_ID_OPT_FIELD] = "",
) -> dict:
    """Faz POST/PUT/PATCH/DELETE em qualquer endpoint da Integration v1 (gated por mode)."""
    with _instrument("integration_write") as t:
        try:
            result = await unifi.integration_write(device_id, subpath, method, body, host_id)
        except Exception as exc:
            t.record("error")
            raise ToolError(f"integration_write falhou: {type(exc).__name__}") from exc
        t.record("invalid" if result.get("erro") else "success")
    return result
