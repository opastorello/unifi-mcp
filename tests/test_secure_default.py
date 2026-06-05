"""Secure-by-default: sem ENV explícito o app assume production e recusa subir sem token.

Roda em subprocesso isolado — conftest.py NÃO é carregado nesses processos,
portanto o default real de config.py é aplicado (ENV="production").
"""
import os
import subprocess
import sys

_SERVER_ROOT = os.path.dirname(os.path.dirname(__file__))


def _run(env_overrides: dict) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ENV", "API_TOKEN")}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app.auth"],
        cwd=_SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_sem_env_sem_token_recusa_subir():
    """Bare run (nenhum ENV nem API_TOKEN) → fail-fast imediato (default=production)."""
    r = _run({"CONFIG_PATH": "config/none.json"})
    assert r.returncode != 0, "app.auth deveria ter levantado RuntimeError sem token"
    assert "API_TOKEN" in r.stderr


def test_dev_sem_token_sobe():
    """ENV=development sem token → escape hatch dev funciona normalmente."""
    r = _run({"ENV": "development"})
    assert r.returncode == 0, r.stderr
