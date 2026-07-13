FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

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
    && uv pip install --python .venv --no-deps "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9" \
    && .venv/bin/python -m divapply.jobspy_runtime

USER appuser
VOLUME ["/data"]
STOPSIGNAL SIGINT

HEALTHCHECK --interval=5m --timeout=30s --start-period=30s --retries=3 \
    CMD python -m divapply selfcheck >/tmp/divapply-health.log 2>&1 || exit 1

ENTRYPOINT ["python", "-m", "divapply"]
CMD ["--help"]
