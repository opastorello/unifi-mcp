import os

# Bootstrap de teste: garante que a importação de app.auth não dispare o fail-fast
# de produção durante a coleta do pytest. IS_PRODUCTION=False → testes rodam livres.
os.environ.setdefault("ENV", "test")

# Presença deste arquivo faz o pytest inserir o diretório do servidor em sys.path,
# permitindo `from app.main import app` ao rodar `pytest` a partir de servers/<nome>/.
