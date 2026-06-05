import hmac
import logging

from starlette.responses import JSONResponse

from app import config as _cfg

logger = logging.getLogger("uvicorn.error")

# Único caminho aberto sem token: /health (healthcheck do Docker/Coolify).
# / (índice JSON) e /metrics passam a exigir token.
_OPEN_PATHS_ALWAYS = {"/health"}
# Em desenvolvimento, a doc interativa fica acessível sem token (conveniência).
_OPEN_PATHS_DEV = {"/docs", "/redoc", "/openapi.json"}

# Fail-fast: production é o DEFAULT — um run sem API_TOKEN recusa subir imediatamente.
# Para abrir sem auth, defina explicitamente ENV=development ou ENV=test.
if _cfg.IS_PRODUCTION and not _cfg.API_TOKEN:
    raise RuntimeError(
        "API_TOKEN obrigatório quando ENV=production (default). "
        "REST e o endpoint MCP (/mcp) exigem Bearer token — defina API_TOKEN. "
        "Para modo dev sem auth, defina explicitamente ENV=development."
    )
if _cfg.IS_PRODUCTION and len(_cfg.API_TOKEN) < 16:
    raise RuntimeError(
        "API_TOKEN muito curto (mínimo 16 caracteres). "
        "Gere um com: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )
if not _cfg.API_TOKEN:
    logger.warning("API_TOKEN vazio — servidor SEM autenticação (aceitável só em dev/teste).")


def _open_paths() -> set[str]:
    extra = _OPEN_PATHS_DEV if _cfg.ENV == "development" else set()
    return _OPEN_PATHS_ALWAYS | extra


class TokenMiddleware:
    """Protege REST e /mcp via ASGI puro — sem bufferizar o streaming SSE do FastMCP."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Lifespan e WebSocket passam direto — auth só faz sentido em HTTP.
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Lido a cada request: tests fazem monkeypatch em _cfg.API_TOKEN.
        token = _cfg.API_TOKEN
        if not token:
            return await self.app(scope, receive, send)

        path = scope["path"]
        if path in _open_paths():
            return await self.app(scope, receive, send)

        auth = ""
        for name, value in scope["headers"]:
            if name == b"authorization":
                auth = value.decode("latin-1")
                break

        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], token):
            # JSONResponse é um app ASGI — só o caminho de rejeição usa isso,
            # então não há buffering no caminho de sucesso (pass-through direto).
            return await JSONResponse({"detail": "Unauthorized"}, status_code=401)(
                scope, receive, send
            )

        return await self.app(scope, receive, send)
