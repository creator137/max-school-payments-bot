FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
WORKDIR /app

RUN pip install --no-cache-dir uv==0.8.15
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
RUN chmod +x scripts/entrypoint.sh && mkdir -p /data/receipts

EXPOSE 8000
ENTRYPOINT ["./scripts/entrypoint.sh"]

