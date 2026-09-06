FROM ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 AS uv

FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN uv sync --project backend --frozen --no-dev --no-install-project

COPY backend ./backend
COPY contracts ./contracts
COPY evaluators ./evaluators
COPY fixtures ./fixtures

RUN groupadd --gid 10001 orchestrator \
    && useradd --uid 10001 --gid orchestrator --no-create-home orchestrator \
    && mkdir -p /app/agents /app/playbook /app/reports /app/runs \
    && chown -R orchestrator:orchestrator /app/agents /app/playbook /app/reports /app/runs

USER orchestrator

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

# One process is deliberate: SQLite plus in-process background jobs do not
# support multiple independent application workers.
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
