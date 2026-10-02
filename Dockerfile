# Single multi-stage image: the SPA is built with Node, then served by `lore serve` on Python
# (docs/architecture/deployment.md §2; keep that section in sync with this file).

# --- web build -------------------------------------------------------------
FROM node:26-slim AS web
WORKDIR /src
COPY package.json package-lock.json tsconfig.base.json ./
COPY frontend/package.json frontend/
COPY packages/chronology/package.json packages/chronology/
RUN npm ci
COPY spec ./spec
COPY packages ./packages
COPY frontend ./frontend
RUN npm run build --workspace frontend

# --- runtime ---------------------------------------------------------------
FROM python:3.14-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
COPY spec ./spec
RUN cd backend && uv sync --frozen --no-dev --no-editable
COPY --from=web /src/frontend/dist /app/static
# The image runs as an unprivileged user. docker-compose.yml overrides the uid/gid with the host
# user's so the bind-mounted ./data stays writable and owned by them.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin lore \
    && mkdir -p /data /published && chown lore: /data /published
USER lore
ENV PATH="/app/backend/.venv/bin:$PATH" \
    LORE_DATA_DIR=/data LORE_STATIC_DIR=/app/static LORE_SPEC_DIR=/app/spec \
    LORE_HOST=0.0.0.0 LORE_PORT=8080 LORE_LOG_FORMAT=json
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=2)"]
CMD ["lore", "serve"]
