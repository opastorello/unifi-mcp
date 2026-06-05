"""Testa o tratamento de 429 + Retry-After no cliente HTTP (_http).

Comportamento documentado (UniFi Site Manager → Rate Limiting): ao exceder o
limite, o upstream responde 429 com header Retry-After indicando os segundos a
aguardar. O cliente honra esse valor (capado em _RETRY_AFTER_MAX) entre retries.
"""
import httpx

from app import config as _cfg
from app.services import _http


def _mock_429(monkeypatch, retry_after: str | None):
    """Injeta um device cujo upstream sempre responde 429 (com/sem Retry-After)."""
    def handler(_req: httpx.Request) -> httpx.Response:
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        return httpx.Response(429, json={"message": "rate limit exceeded"}, headers=headers)

    device = _http.get_device("test-device")
    monkeypatch.setitem(
        _http._clients, "test-device",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=device.base_url),
    )


def _capture_sleeps(monkeypatch):
    """Substitui asyncio.sleep no _http por um fake que registra (não dorme)."""
    waited: list[float] = []

    async def fake_sleep(secs):
        waited.append(secs)

    monkeypatch.setattr(_http.asyncio, "sleep", fake_sleep)
    return waited


# ── parser ───────────────────────────────────────────────────────────────────

class TestParseRetryAfter:
    def test_delta_seconds_int(self):
        assert _http._parse_retry_after("7") == 7.0

    def test_delta_seconds_float(self):
        assert _http._parse_retry_after("5.37") == 5.37

    def test_none_e_vazio(self):
        assert _http._parse_retry_after(None) is None
        assert _http._parse_retry_after("") is None

    def test_http_date_futura(self):
        # data ~2 min no futuro → ~120s (tolerância ampla)
        from datetime import datetime, timedelta, timezone
        from email.utils import format_datetime
        dt = datetime.now(timezone.utc) + timedelta(seconds=120)
        secs = _http._parse_retry_after(format_datetime(dt))
        assert secs is not None and 90 <= secs <= 130

    def test_invalido(self):
        assert _http._parse_retry_after("abc") is None


# ── comportamento no loop de retry ────────────────────────────────────────────

class TestRetryAfterBehavior:
    async def test_honra_retry_after(self, monkeypatch):
        monkeypatch.setattr(_cfg, "MAX_RETRIES", 2)
        waited = _capture_sleeps(monkeypatch)
        _mock_429(monkeypatch, "7")
        out = await _http.request_json("test-device", "GET", "/v1/sites")
        assert out["erro"] is True
        assert "429" in out["mensagem"]
        # 3 tentativas → 2 esperas, ambas respeitando o header (7s)
        assert waited == [7.0, 7.0]

    async def test_cap_retry_after(self, monkeypatch):
        monkeypatch.setattr(_cfg, "MAX_RETRIES", 1)
        waited = _capture_sleeps(monkeypatch)
        _mock_429(monkeypatch, "999")  # acima do teto
        out = await _http.request_json("test-device", "GET", "/v1/sites")
        assert out["erro"] is True
        assert waited == [_http._RETRY_AFTER_MAX]  # capado

    async def test_sem_header_usa_backoff_padrao(self, monkeypatch):
        monkeypatch.setattr(_cfg, "MAX_RETRIES", 1)
        waited = _capture_sleeps(monkeypatch)
        _mock_429(monkeypatch, None)  # 429 sem Retry-After
        out = await _http.request_json("test-device", "GET", "/v1/sites")
        assert out["erro"] is True
        assert waited == [0.5]  # backoff padrão 0.5*(attempt+1) p/ attempt=0
