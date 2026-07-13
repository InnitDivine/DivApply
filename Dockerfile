FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /uvx /bin/

LABEL org.opencontainers.image.title="DivApply" \
      org.opencontainers.image.description="Local-first job application assistant CLI" \
      org.opencontainers.image.source="https://github.com/InnitDivine/DivApply" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV DIVAPPLY_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data

COPY pyproject.toml uv.lock README.md LICENSE ./

RUN uv sync --locked --no-dev --extra full --no-install-project

COPY src ./src
COPY scripts ./scripts

RUN uv sync --locked --no-dev --extra full --no-editable \
    && uv pip install --python .venv --no-deps "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9"

USER appuser
VOLUME ["/data"]
STOPSIGNAL SIGINT

HEALTHCHECK --interval=5m --timeout=30s --start-period=30s --retries=3 \
    CMD python -m divapply selfcheck >/tmp/divapply-health.log 2>&1 || exit 1

ENTRYPOINT ["python", "-m", "divapply"]
CMD ["--help"]
