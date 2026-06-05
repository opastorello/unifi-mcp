# Base pinada por digest (2026-05-16) — bump deliberado.
FROM python:3.11.15-slim@sha256:9a7765b36773a37061455b332f18e265e7f58f6fea9c419a550d2a8b0e9db834

WORKDIR /app

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# config/ é montado via volume no docker-compose (config/config.json).
# Para rodar sem compose: docker run -v ./config:/app/config:ro ...
RUN mkdir -p config

RUN useradd -m mcpuser
USER mcpuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
