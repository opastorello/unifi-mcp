"""Request ID + log de acesso (1 linha estruturada por request)."""
import logging
import re
import time
import uuid

logger = logging.getLogger("unifi.access")


def setup_logging() -> None:
    """Garante que os logs do app saiam mesmo sob uvicorn (idempotente)."""
    from app import config as _cfg

    root = logging.getLogger("unifi")
    root.setLevel(getattr(logging, _cfg.LOG_LEVEL.upper(), logging.INFO))
    if not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(h)
    root.propagate = False


class RequestContextMiddleware:
    """Injeta X-Request-ID e loga 1 linha por request via ASGI puro (sem bufferizar streaming)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Reaproveita o ID enviado pelo cliente ou gera um novo.
        rid = ""
        for name, value in scope["headers"]:
            if name == b"x-request-id":
                rid = re.sub(r"[^A-Za-z0-9._-]", "", value.decode("latin-1"))[:64]
                break
        if not rid:
            rid = uuid.uuid4().hex[:12]

        start = time.perf_counter()
        safe_path = re.sub(r"[\r\n\x00]", "", scope["path"])[:512]
        status_code: int = 0

        async def send_with_rid(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                dur_ms = (time.perf_counter() - start) * 1000
                # Injeta o header na resposta e loga antes de enviar.
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"cache-control", b"no-store"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                headers.append((b"permissions-policy", b"camera=(), microphone=(), geolocation=()"))
                message = {**message, "headers": headers}
                logger.info(
                    "rid=%s %s %s -> %s %.1fms",
                    rid,
                    scope["method"],
                    safe_path,
                    status_code,
                    dur_ms,
                )
            await send(message)

        await self.app(scope, receive, send_with_rid)
