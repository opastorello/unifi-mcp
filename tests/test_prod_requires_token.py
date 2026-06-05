"""Fail-fast: em produção sem API_TOKEN o app NÃO pode subir.

Roda em subprocesso isolado (o guard de auth.py dispara no import, então
não dá pra testar via reload sem poluir a sessão do pytest).
"""
import os
import subprocess
import sys

_SERVER_ROOT = os.path.dirname(os.path.dirname(__file__))


def test_producao_sem_token_recusa_subir():
    env = {**os.environ, "ENV": "production", "API_TOKEN": "", "CONFIG_PATH": "config/none.json"}
    r = subprocess.run(
        [sys.executable, "-c", "import app.auth"],
        cwd=_SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0, "auth.py deveria ter levantado RuntimeError"
    assert "API_TOKEN obrigatório" in r.stderr


def test_producao_com_token_sobe():
    env = {**os.environ, "ENV": "production", "API_TOKEN": "x" * 16}
    r = subprocess.run(
        [sys.executable, "-c", "import app.auth"],
        cwd=_SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
