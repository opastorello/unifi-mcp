"""F-04 — X-Request-ID sanitization: CRLF stripped, length bounded to 64 chars."""
import re

from fastapi.testclient import TestClient

from app.main import app

_RID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Payload: starts with 'a', then CRLF + 'INJECTED 5' + CRLF, then 5000 'x' chars.
# The sanitizer must strip non-[A-Za-z0-9._-] chars (removing CR/LF/space) and cap at 64.
_MALICIOUS_RID = "a\r\nINJECTED 5\r\n" + "x" * 5000


def test_request_id_sanitized_in_response():
    """Response x-request-id must match [A-Za-z0-9._-]{1,64} — no CR/LF, no overlong value."""
    with TestClient(app) as client:
        r = client.get("/health", headers={"X-Request-ID": _MALICIOUS_RID})
    assert r.status_code == 200
    rid = r.headers.get("x-request-id", "")
    assert rid, "x-request-id header missing from response"
    assert _RID_RE.match(rid), (
        f"x-request-id not sanitized correctly: {rid!r} "
        f"(expected to match {_RID_RE.pattern!r})"
    )
