# Playwright's image already has Chromium and its system libraries installed.
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    TZ=America/Chicago \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY gradebook ./gradebook
RUN mkdir -p /app/data && chown -R pwuser:pwuser /app
USER pwuser

CMD ["python", "-m", "gradebook", "schedule"]
