import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import config as _cfg
from app import devices as _dev
from app import metrics as _m
from app.auth import TokenMiddleware
from app.mcp_server import mcp
from app.observability import RequestContextMiddleware, setup_logging
from app.ratelimit import limiter
from app.routers import unifi
from app.schema_compat import make_tools_gemini_safe
from app.services import _http
from app.services.unifi import SERVICE_VERSION

setup_logging()

# Colapsa anyOf nullable nos schemas das tools (compat Gemini function-calling).
make_tools_gemini_safe(mcp)

_mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _dev.load()
    _m.set_service_info(name=_cfg.SERVER_NAME, version=SERVICE_VERSION, env=_cfg.ENV)
    async with _mcp_app.lifespan(_app):
        yield
    await _http.aclose_all()


app = FastAPI(
    title=_cfg.SERVER_NAME,
    description=(
        "Servidor MCP de IT Ops — multi-target.\n\n"
        "**Autenticação:** `Authorization: Bearer <API_TOKEN>` (obrigatório em produção). "
        "Único aberto sem token: `/health`. Use o botão **Authorize** acima."
    ),
    version=SERVICE_VERSION,
    lifespan=_lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
    docs_url=None if _cfg.IS_PRODUCTION else "/docs",
    redoc_url=None if _cfg.IS_PRODUCTION else "/redoc",
    openapi_url=None if _cfg.IS_PRODUCTION else "/openapi.json",
)


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "Token"}
    }
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if isinstance(operation, dict):
                operation["security"] = [{"BearerAuth": []}, {}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi


def _rate_limit_handler(request, exc: RateLimitExceeded):
    _m.rate_limit_total.labels(endpoint=request.url.path).inc()
    return _rate_limit_exceeded_handler(request, exc)


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.add_middleware(TokenMiddleware)
app.add_middleware(RequestContextMiddleware)


_MAX_BODY_BYTES = 1_048_576  # 1 MB


@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and int(cl) > _MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request body too large"}, status_code=413)
    return await call_next(request)


@app.get("/", include_in_schema=False)
@limiter.limit(_cfg.RATE_LIMIT_DEFAULT)
async def root(request: Request):
    return {
        "service": app.title,
        "version": app.version,
        "devices": _dev.count(),
        "api": "/api",
        "docs": "/docs",
        "mcp": "/mcp",
        "health": "/health",
        "metrics": "/metrics",
    }


@app.get(
    "/health",
    tags=["health"],
    summary="Health check",
    description="Verifica se o servidor está no ar. `?deep=true` checa um device.",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def health(request: Request, deep: bool = False, device_id: str | None = None):
    if not deep:
        return {"status": "ok", "devices_loaded": _dev.count()}
    if _cfg.API_TOKEN:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], _cfg.API_TOKEN):
            return JSONResponse(
                {"erro": True, "mensagem": "deep health requer Bearer token"}, status_code=401
            )
    from app.services import unifi as svc
    target = device_id or (_dev.list_ids()[0] if _dev.list_ids() else None)
    if not target:
        return {"status": "ok", "upstream": "no_devices"}
    up = await svc.check_upstream(target)
    return {"status": "ok", "device": target, "upstream": "unreachable" if up.get("erro") else "ok"}


app.include_router(unifi.router)

Instrumentator().instrument(app).expose(app, include_in_schema=False)

app.mount("/mcp", _mcp_app)
