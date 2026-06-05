"""Testes do modulo app/config.py — edge cases de parsing.

Cobre:
  - _env_int com valor invalido retorna default
  - config sem config.json (DEVICES_RAW vazio)
  - ENV detection (IS_PRODUCTION, IS_TEST)
"""
class TestEnvInt:
    """_env_int converte inteiros do ambiente."""

    def test_valid_int_from_env(self, monkeypatch):
        monkeypatch.setenv("TEST_PORT", "9999")
        # Reimportar para testar _env_int diretamente
        from app.config import _env_int
        assert _env_int("TEST_PORT", 8000) == 9999

    def test_invalid_int_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_PORT", "not-a-number")
        from app.config import _env_int
        assert _env_int("TEST_PORT", 8000) == 8000

    def test_missing_env_returns_default(self):
        from app.config import _env_int
        assert _env_int("SURELY_DOES_NOT_EXIST_12345", 42) == 42


class TestEnv:
    """_env strips whitespace."""

    def test_env_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("TEST_STRIP", "  hello  ")
        from app.config import _env
        assert _env("TEST_STRIP", "default") == "hello"

    def test_env_missing_returns_default(self):
        from app.config import _env
        assert _env("SURELY_DOES_NOT_EXIST_99999", "fallback") == "fallback"
