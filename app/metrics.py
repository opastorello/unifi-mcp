"""Métricas Prometheus padronizadas para o servidor MCP UniFi.

Três camadas:
  1. USO — volume/latência de chamadas MCP tools e REST endpoints.
  2. UPSTREAM — saúde e performance da API encapsulada.
  3. DOMÍNIO — métricas específicas do negócio (template fornece exemplos).

Labels controlados (cardinalidade fixa):
  - tool: nome snake_case da tool (echo, list_users, …)
  - result: success | invalid | error
  - client: identificador do client MCP (clientInfo.name no initialize)
  - endpoint: path REST (/api/example/echo)
  - method: HTTP method upstream (GET, POST, …)
  - error_type: timeout | connection | http_status | decode
"""

from prometheus_client import Counter, Gauge, Histogram, Info

# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 1 — USO (tools MCP + REST)
# ═════════════════════════════════════════════════���═════════════════════════════

mcp_calls_total = Counter(
    "mcp_calls_total",
    "Chamadas MCP por tool, resultado e client que chamou",
    ["tool", "result", "client"],
)

mcp_call_duration_seconds = Histogram(
    "mcp_call_duration_seconds",
    "Duração de execução de cada tool MCP",
    ["tool"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

mcp_calls_in_progress = Gauge(
    "mcp_calls_in_progress",
    "Tools MCP em execução agora",
    ["tool"],
)

mcp_sessions_total = Counter(
    "mcp_sessions_total",
    "Sessões MCP iniciadas (initialize) por client",
    ["client"],
)

rest_calls_total = Counter(
    "rest_calls_total",
    "Chamadas REST por endpoint e resultado",
    ["endpoint", "result"],
)

rate_limit_total = Counter(
    "rate_limit_total",
    "Requisições bloqueadas por rate limit",
    ["endpoint"],
)

# ════════════��══════════════════════════════════════════════════════════════════
# CAMADA 2 — UPSTREAM (API de IT Ops encapsulada)
# ═���═════════════════════════════════════════════════════════════════════════════

upstream_requests_total = Counter(
    "upstream_requests_total",
    "Chamadas à API upstream por method, status e device",
    ["method", "status", "device"],
)

upstream_request_duration_seconds = Histogram(
    "upstream_request_duration_seconds",
    "Latência da API upstream",
    buckets=[0.1, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

upstream_errors_total = Counter(
    "upstream_errors_total",
    "Erros de comunicação com a API upstream por tipo e device",
    ["type", "device"],  # type: timeout | connection | http_status | decode
)

upstream_retries_total = Counter(
    "upstream_retries_total",
    "Retries executados contra a API upstream",
)

concurrent_requests = Gauge(
    "concurrent_requests",
    "Requisições upstream em execução agora",
)

# ════════════════════════════════════════════════��══════════════════════════════
# CAMADA 3 — DOMÍNIO (específico por MCP — exemplos abaixo)
# ══════��════════════════════════════════════════════════════════════════════════
# Ao criar um MCP concreto, adicione aqui as métricas de negócio.
# Use gauge p/ estado atual, counter p/ eventos, histogram p/ medições.
# NUNCA use labels de cardinalidade livre (user_id, IP, UUID).
#
# ┌─────────────────────────────────────────────────────────────────────────────
# │ EXEMPLOS POR MCP (descomente/adapte ao implementar):
# │
# │ ── Zabbix ──
# │ zabbix_hosts_total = Gauge("zabbix_hosts_total", "Hosts no Zabbix", ["status"])
# │ zabbix_triggers_active = Gauge("zabbix_triggers_active", "Triggers ativas", ["severity"])
# │ zabbix_problems_open = Gauge("zabbix_problems_open", "Problemas abertos", ["severity"])
# │
# │ ── Grafana ──
# │ grafana_alerts_firing = Gauge("grafana_alerts_firing", "Alertas disparando", ["state"])
# │ grafana_datasource_health = Gauge("grafana_datasource_health", "Saúde DS", ["name","status"])
# │
# │ ── Proxmox ──
# │ proxmox_vms_total = Gauge("proxmox_vms_total", "VMs por nó e estado", ["node","status"])
# │ proxmox_storage_usage_ratio = Gauge("proxmox_storage_usage_ratio", "Uso disco", ["storage"])
# │
# │ ── Network-tools ──
# │ nettools_ping_rtt_ms = Histogram("nettools_ping_rtt_ms", "RTT ping", ["target"])
# │ nettools_checks_total = Counter("nettools_checks_total", "Checks executados", ["type"])
# │
# │ ── Fortigate ──
# │ fortigate_vpn_tunnels_up = Gauge("fortigate_vpn_tunnels_up", "Túneis VPN up", ["type"])
# │ fortigate_threats_blocked = Counter("fortigate_threats_blocked", "Ameaças", ["type"])
# │
# │ ── UniFi ──
# │ unifi_clients_connected = Gauge("unifi_clients_connected", "Clientes", ["type","site"])
# │ unifi_devices_total = Gauge("unifi_devices_total", "Dispositivos", ["type","status"])
# │
# │ ── Tracelog ──
# │ tracelog_queries_total = Counter("tracelog_queries_total", "Buscas", ["source","result"])
# │ tracelog_lines_returned = Histogram("tracelog_lines_returned", "Linhas", ["source"])
# └────���─────────────────────────���──────────────────────────────────────────────

# ════════════════════════════════��══════════════════════════════════════════════
# INFO — metadados estáticos exportados como métrica (util em dashboards)
# ═══════════════════════════════════════════════════════════════════════════════

# ── UniFi — Camada 3 (domínio) ──────────────────────────────────────────────
# Métricas baseadas na UniFi Site Manager Cloud API (api.ui.com)

unifi_hosts_total = Gauge(
    "unifi_hosts_total",
    "Consoles UniFi (hosts) por tipo e owner",
    ["type", "owner"],
)

unifi_devices_total = Gauge(
    "unifi_devices_total",
    "Dispositivos UniFi por tipo e status",
    ["type", "status"],
)

unifi_sites_offline = Gauge(
    "unifi_sites_offline",
    "Sites com dispositivos offline por console",
    ["host_id"],
)

unifi_clients_connected = Gauge(
    "unifi_clients_connected",
    "Clientes conectados ao UniFi por tipo e site",
    ["type", "site"],
)

# ── Diagnóstico L1 / health (via Network API legada proxiada) ───────────────
# Cardinalidade limitada por console (host_id ≈ frota) + conjuntos fixos.

unifi_ap_link_degraded = Gauge(
    "unifi_ap_link_degraded",
    "APs com link de uplink abaixo de 1 Gbps por console",
    ["host_id"],
)

unifi_devices_disconnected = Gauge(
    "unifi_devices_disconnected",
    "Dispositivos desconectados por console e tipo (uap/usw/ugw)",
    ["host_id", "type"],
)

unifi_site_subsystem_warning = Gauge(
    "unifi_site_subsystem_warning",
    "Subsistemas do site em warning/error (1=alerta) por console",
    ["host_id", "subsystem"],
)

# ─────────────────────────────────────────────────────────────────────────────

service_info_metric = Info(
    "mcp_service",
    "Metadados do servidor MCP",
)


def set_service_info(name: str, version: str, env: str) -> None:
    """Chamado uma vez no startup (lifespan) para popular labels estáticos."""
    service_info_metric.info({"name": name, "version": version, "env": env})
