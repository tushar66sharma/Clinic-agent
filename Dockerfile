# One image that serves both the API and the built dashboard.
# Used by the Render deployment (render.yaml) and for local production testing.

# ---- Stage 1: build the React dashboard ------------------------------------------------
FROM node:22-alpine AS dashboard
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python API ---------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EDVAK_HOME=/app \
    PORT=10000
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY data ./data
COPY reports ./reports
COPY --from=dashboard /build/frontend/dist ./frontend/dist

# Run as an unprivileged user. runs/ holds the AI response cache (ephemeral on free hosts).
RUN useradd --create-home app && mkdir -p /app/runs && chown -R app /app
USER app

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"10000\")}/api/health', timeout=4)"
CMD ["python", "-m", "edvak_forge.api"]
