FROM python:3.12-slim

LABEL org.opencontainers.image.title="DivApply" \
      org.opencontainers.image.description="Local-first job application assistant CLI" \
      org.opencontainers.image.source="https://github.com/InnitDivine/DivApply" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV DIVAPPLY_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[full]" \
    && python -m pip install --no-deps python-jobspy

USER appuser
VOLUME ["/data"]
STOPSIGNAL SIGINT

HEALTHCHECK --interval=5m --timeout=30s --start-period=30s --retries=3 \
    CMD divapply selfcheck >/tmp/divapply-health.log 2>&1 || exit 1

ENTRYPOINT ["divapply"]
CMD ["--help"]
