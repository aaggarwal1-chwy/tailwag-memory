FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TAILWAG_API_PORT=8000

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[api]" \
    && addgroup --system tailwag \
    && adduser --system --ingroup tailwag --home /app tailwag \
    && chown -R tailwag:tailwag /app

USER tailwag

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('TAILWAG_API_PORT', '8000'), timeout=3).read()" || exit 1

CMD ["sh", "-c", "python -m uvicorn tailwag_memory.api.app:create_app --factory --host 0.0.0.0 --port ${TAILWAG_API_PORT:-8000}"]
