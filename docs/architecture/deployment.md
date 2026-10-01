# Deployment and development environment

## 1. Configuration (environment variables)

| Variable | Default | Meaning |
|----------|---------|---------|
| `LORE_DATA_DIR` | `./data` (dev), `/data` (Docker) | root of `vaults/`, `trash/` |
| `LORE_HOST` | `127.0.0.1` (dev), `0.0.0.0` inside Docker | bind address |
| `LORE_PORT` | `8000` (dev), `8080` (Docker) | port |
| `LORE_READ_ONLY` | `false` | reader mode (`visibility-and-sharing.md` §7) |
| `LORE_EXPOSED_VAULTS` | empty (= all) | comma-separated vault ids/folders to serve |
| `LORE_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Host header allowlist, ports ignored; `LORE_HOST` is added unless it is a wildcard address (`*` allowed only with `LORE_READ_ONLY=true`) |
| `LORE_CORS_ORIGINS` | empty | development only |
| `LORE_AUTO_MIGRATE` | `true` | migrate vaults on open (with backup) |
| `LORE_STATIC_DIR` | empty (API only) | built SPA directory to serve at `/` (with SPA fallback) |
| `LORE_SPEC_DIR` | auto-detected `<repo>/spec` | location of `spec/chronology` (presets, schemas) |
| `LORE_MAX_UPLOAD_MB` | `50` | upload size limit |
| `LORE_PUBLISH_DIR` | empty (publishing from the UI disabled) | data-dir root where published snapshots are written |
| `LORE_LOG_LEVEL` / `LORE_LOG_FORMAT` | `info` / `text` | logging (`json` = one JSON object per line, for containers); every record carries the request id |
| `LORE_DEBUG` | `false` | include tracebacks in `internal_error` responses (development only, never in shared deployments) |

Settings are read once at startup with `pydantic-settings` (`lore.config.Settings`). Vault-level
preferences (backup schedule, display options, module toggles) live in the vault, not in env vars.

## 2. Docker image (multi-stage)

```dockerfile
# --- web build -------------------------------------------------------------
FROM node:26-slim AS web
WORKDIR /src
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/
COPY packages/chronology/package.json packages/chronology/
RUN npm ci
COPY spec ./spec
COPY packages ./packages
COPY frontend ./frontend
RUN npm run build --workspace frontend

# --- runtime ---------------------------------------------------------------
FROM python:3.14-slim AS app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
COPY spec ./spec
RUN cd backend && uv sync --frozen --no-dev --no-editable
COPY --from=web /src/frontend/dist /app/static
RUN useradd --system --uid 10001 lore && mkdir -p /data && chown lore /data
USER lore
ENV PATH="/app/backend/.venv/bin:$PATH" \
    LORE_DATA_DIR=/data LORE_STATIC_DIR=/app/static LORE_SPEC_DIR=/app/spec \
    LORE_HOST=0.0.0.0 LORE_PORT=8080 LORE_LOG_FORMAT=json
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health')"
CMD ["lore", "serve"]
```

(The real Dockerfile is created in M0 and may differ in details, e.g. pinning the uv image tag.
Keep this section in sync with it.)

## 3. docker compose

```yaml
services:
  lore:                                   # author instance: localhost only
    build: .
    image: lore-world-tracker:local
    ports: ["127.0.0.1:8080:8080"]
    volumes: ["./data:/data", "./published:/published"]
    environment:
      LORE_PUBLISH_DIR: /published        # where "Publish snapshot" writes (a data-dir layout)
    restart: unless-stopped

  reader:                                 # read-only instance for sharing a published snapshot
    profiles: ["reader"]
    image: lore-world-tracker:local
    ports: ["8081:8080"]
    volumes: ["./published:/data:ro"]
    environment:
      LORE_READ_ONLY: "true"
      LORE_ALLOWED_HOSTS: "*"             # or your public hostname
    restart: unless-stopped
```

Sharing workflow: `docker compose exec lore lore vault publish <vault> --out /published` (or the
settings button, which writes into `LORE_PUBLISH_DIR`). `--out` is a **data-dir root**: the
snapshot lands in `/published/vaults/<folder>/`, replacing an earlier snapshot of the same vault.
Then `docker compose --profile reader up -d reader`. Put a reverse proxy (Caddy/nginx) with TLS in
front of `reader` if it is exposed to the internet. Basic auth at the proxy is optional.

Upgrading: `git pull && docker compose build && docker compose up -d`. Vaults auto-migrate on
first open, with a pre-migration backup.

## 4. Development environment

Prerequisites: `uv`, Node.js (≥ 24; the repo's `.nvmrc` pins the major version), `make`, and
Docker (optional, for image builds/e2e parity).

| Command | Does |
|---------|------|
| `make setup` | `uv sync` (backend) + `npm ci` (workspaces) + Playwright browsers |
| `make dev` | backend `uv run lore serve --reload` on :8000 **and** Vite on :5173 (proxy `/api` → :8000), data in `./data` |
| `make check` | everything CI runs except e2e/docker: lint, format check, types, import contracts, tests, conformance, drift checks |
| `make test` / `make test-backend` / `make test-frontend` / `make test-chronology` | tests |
| `make e2e` | build the SPA, start the backend serving it on a temp data dir, run Playwright |
| `make gen` | regenerate OpenAPI TS types and chronology JSON Schema/TS types |
| `make fmt` | ruff format + prettier |
| `make docker` | build the image |
| `make sample-vault SIZE=small` | generate the demo world into `./data` |

## 5. Versioning and releases

- One app version (SemVer) shared by `backend/pyproject.toml` and the npm workspaces, bumped
  together.
- Each completed milestone ends with a release PR: version bump, `CHANGELOG.md`
  (Keep a Changelog) update, a **new golden fixture vault** (`persistence-and-migrations.md`
  §3.5), and tag `vX.Y.0`.
- Pre-1.0 versions may change the API freely (same-repo client). Vault data must stay
  upgradable across **every** version from the first release that wrote vaults.
