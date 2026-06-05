# unifi-mcp

[![CI](https://github.com/opastorello/unifi-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/opastorello/unifi-mcp/actions/workflows/ci.yml)
[![Docker](https://github.com/opastorello/unifi-mcp/actions/workflows/docker.yml/badge.svg)](https://github.com/opastorello/unifi-mcp/actions/workflows/docker.yml)
![license](https://img.shields.io/badge/license-MIT-blue)

Servidor **MCP de UniFi** — multi-target, completo, com acesso **Local** (console direto na LAN)
e **Remoto** (Cloud Connector, sem estar na rede). FastAPI + FastMCP 3.0.

Arquitetura em camadas: `services/` pura (zero dependência de framework); `routers/` (REST) e
`mcp_server.py` (MCP) são duas interfaces sobre a mesma lógica.

> 📚 **Specs & documentação da API:** este MCP é construído sobre o
> [**opastorello/unifi-api-docs**](https://github.com/opastorello/unifi-api-docs) — espelho
> versionado e auto-atualizável do OpenAPI oficial da UniFi (Network, Protect, Site Manager, Mobility).
>
> Referência interativa: <https://opastorello.github.io/unifi-api-docs/>

## Conceito

Cada **device** no `config.json` é uma de duas naturezas (campo `kind`):

| `kind` | O que é | Como fala com o UniFi | `host` |
|---|---|---|---|
| `cloud` (default) | Conta UniFi Site Manager | `api.ui.com` → frota inteira + qualquer console **remotamente** via Cloud Connector | `api.ui.com` |
| `local` | Um console específico | `https://<console>/proxy/...` **direto na LAN** | IP/host do console |

Ambos autenticam com header **`X-API-KEY`** (`auth_scheme: "x-api-key"`):
- **cloud** → chave gerada em **unifi.ui.com → Settings → API Keys**.
- **local** → chave gerada no **console → Integrations**.

> A mesma Network Integration v1 serve aos dois — muda só o prefixo da URL, resolvido
> automaticamente conforme o `kind`. Tudo que dá pra fazer localmente dá pra fazer remotamente.

## Capacidades (tools)

29 tools MCP, cada uma espelhada em REST sob `/api/unifi`. `device_id` é sempre o 1º parâmetro.

**Discovery / info:** `list_devices`, `service_info`, `check_upstream`.

**Site Manager (frota, device cloud):** `list_hosts`, `get_host_detail`, `list_sites`,
`list_all_devices`, `fleet_health_summary`, `list_offline_devices`, `get_isp_metrics`,
`list_sdwan_configs`, `get_sdwan_config`.

**Network Integration v1 (cloud ou local):** `get_console_sites`, `get_console_devices`,
`get_device_detail`, `get_console_clients`, `get_console_networks`, `get_console_info`.

**Passthrough genérico (cobre toda a Integration v1 + versões futuras):**
- `integration_get(device_id, subpath, host_id="", paged=True)` — GET em qualquer endpoint.
- `integration_write(device_id, subpath, method, body, host_id="")` — POST/PUT/PATCH/DELETE (gated por `mode`).

Ex.: criar SSID → `integration_write(d, "sites/{siteId}/wifi/broadcasts", "POST", {...})`.
Consulte o subpath/schema exatos no [catálogo de docs](https://opastorello.github.io/unifi-api-docs/).

**Ações (write, gated por `mode`):** `restart_device`, `power_cycle_port`, `client_action`, `power_cycle_ap`.

**Diagnóstico físico L1 / health (via Network API legada proxiada):** `get_device_diagnostics`,
`resolve_uplink`, `get_port_health`, `get_site_health`.

## Configuração

Modelo híbrido: devices/server/logging em `config/config.json`; secrets via `.env`.

```bash
cp config/config.json.example config/config.json   # edite com seus devices
cp .env.example .env                                # ENV, API_TOKEN
```

- **`mode`** por device é o write-gate: `read` (default) bloqueia escrita; `write`/`admin` liberam.
- **`kind`**: `cloud` (default) ou `local`.
- **`API_TOKEN`** (env) protege REST + MCP (Bearer). Obrigatório em produção.

## Rate limiting

A API UniFi (Site Manager) impõe limite por versão da API: **100 req/min** (Early Access) e
**10.000 req/min** (v1 estável). Ao exceder, responde `429 Too Many Requests` com header
`Retry-After` (segundos). O cliente HTTP **honra o `Retry-After`** automaticamente — aguarda o
tempo indicado entre as tentativas (capado em 30s) e cai no backoff padrão quando o header
não vem.

## Rodar

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- MCP: `http://localhost:8000/mcp` (streamable-http) · REST: `/api/unifi/...`
- Health: `/health` (`?deep=true&device_id=X` pinga o upstream) · Métricas: `/metrics`
- `/docs` apenas em `ENV=development`.

## Testes / lint

```bash
ruff check app/ tests/
pytest -q
```

## Docker

Imagem pública no GHCR — `docker pull` sem login:

```bash
docker pull ghcr.io/opastorello/unifi-mcp:latest
```

Ou construir/rodar local com o compose (lê `config/config.json` + `.env`):

```bash
docker compose up --build -d
```

## CI/CD

GitHub Actions (`.github/workflows/`):

- **`ci.yml`** — `ruff` + `pytest` em cada push/PR na `main`.
- **`docker.yml`** — build e push da imagem para o GHCR (`latest`, `sha`, tags `v*`).
- **`release.yml`** — quando o `SERVICE_VERSION` (em `app/services/unifi.py`) muda, cria a tag
  `vX.Y.Z`, publica a imagem versionada no GHCR e gera o GitHub Release.
