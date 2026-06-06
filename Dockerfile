FROM python:3.12-slim

ENV DIVAPPLY_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER appuser
VOLUME ["/data"]

ENTRYPOINT ["divapply"]
CMD ["--help"]
