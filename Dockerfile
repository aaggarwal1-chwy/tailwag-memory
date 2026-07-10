FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[api]"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "tailwag_memory.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
