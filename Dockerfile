# One image for the web process and the task worker (the command decides which).
FROM node:22-bookworm-slim AS assets
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY src/msd/web/templates /build/src/msd/web/templates
COPY src/msd/web/*.py /build/src/msd/web/
RUN npm run build

FROM python:3.13-slim AS app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MSD_ENV=prod MSD_ROOT=/app MSD_STATIC_ROOT=/app/staticfiles
RUN useradd --create-home --uid 10001 desk
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=assets /build/src/msd/web/static/web ./src/msd/web/static/web
RUN pip install --no-cache-dir .
COPY config ./config
COPY scenarios ./scenarios
COPY manage.py ./
RUN MSD_SECRET_KEY=build-only-not-a-secret-0123456789abcdefghijklmnopqrstuvwxyz python manage.py collectstatic --noinput
USER desk
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# web: gunicorn with uvicorn workers (ASGI); worker: python manage.py db_worker
CMD ["gunicorn", "msd.asgi:application", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "-w", "2", "--timeout", "60"]
