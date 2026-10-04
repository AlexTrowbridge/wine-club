# syntax=docker/dockerfile:1
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN SECRET_KEY=collectstatic-only /opt/venv/bin/python manage.py collectstatic --noinput -v0


FROM python:3.13-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_CONCURRENCY=3
RUN useradd --system --uid 10001 --no-create-home --home-dir /app app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
USER 10001
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers ${WEB_CONCURRENCY} --worker-class gthread --threads 4 --worker-tmp-dir /tmp --no-control-socket --access-logfile - --forwarded-allow-ips '*'"]
