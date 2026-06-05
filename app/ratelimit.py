from slowapi import Limiter
from starlette.requests import Request

from app import config as _cfg


def _get_client_ip(request: Request) -> str:
    """Extract real client IP for rate limiting.

    When TRUSTED_PROXY_COUNT > 0 (behind N proxies), uses X-Forwarded-For
    rightmost entry at position -TRUSTED_PROXY_COUNT (the one the trusted
    proxy injected). Otherwise uses the raw socket peer address.

    NEVER blindly trusts X-Forwarded-For without explicit proxy config.
    """
    trusted = _cfg.TRUSTED_PROXY_COUNT
    if trusted > 0:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            # The entry at position -trusted is what our outermost trusted proxy saw
            if len(parts) >= trusted:
                return parts[-trusted]
    # Fallback: direct connection (no proxy or untrusted)
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_client_ip)
