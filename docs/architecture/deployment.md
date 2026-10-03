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

The repository's `Dockerfile` (copied verbatim here; keep the two in sync). `.dockerignore` keeps
host `node_modules`, `.venv`, `data`, `published`, `.git`, `docs` and caches out of the build
context. `make docker` builds it as `lore-world-tracker:local`.

```dockerfile
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
```

- The uv image is pinned to a version tag (Dependabot's `docker` ecosystem bumps it, along with
  the `node`/`python` base images).
- The image runs as the unprivileged user `lore` (uid 10001). `docker-compose.yml` overrides the
  uid/gid with the host user's (§3), so files under the bind-mounted `./data` stay owned by them.
  The runtime never calls `uv`, so an arbitrary uid without a home directory works.
- `spec/` is copied to `/app/spec` (`LORE_SPEC_DIR`) for the chronology presets and schemas.
- CI's `docker` job runs `make docker` then `make docker-smoke` (`testing.md` §5).

## 3. docker compose

The repository's `docker-compose.yml` (copied verbatim here; keep the two in sync):

```yaml
# Suggested deployment (docs/architecture/deployment.md §3; keep that section in sync).
#   mkdir -p data published && docker compose up -d   → http://127.0.0.1:8080
# Create ./data and ./published yourself first: directories Docker creates are owned by root and
# not writable by the container user. The containers run as LORE_UID:LORE_GID (default 1000:1000;
# set them to `id -u` / `id -g` if yours differ) so files in ./data stay owned by you.
services:
  lore: # author instance: bound to localhost only (security.md §1)
    build: .
    image: lore-world-tracker:local
    # A fixed hostname lets a recreated container take over vault locks left by a crash
    # (a lock is only taken over on the host that wrote it; persistence-and-migrations.md §1).
    hostname: lore
    user: '${LORE_UID:-1000}:${LORE_GID:-1000}'
    ports: ['127.0.0.1:8080:8080']
    volumes: ['./data:/data', './published:/published']
    environment:
      LORE_PUBLISH_DIR: /published # where "Publish snapshot" writes (a data-dir layout)
    restart: unless-stopped

  # Read-only instance for sharing a published snapshot: `docker compose --profile reader up -d`.
  # NOT FUNCTIONAL YET: reader mode (LORE_READ_ONLY, snapshot publishing) arrives in M12. Until
  # then this service is a placeholder that documents the intended setup.
  reader:
    profiles: ['reader']
    image: lore-world-tracker:local
    user: '${LORE_UID:-1000}:${LORE_GID:-1000}'
    ports: ['8081:8080']
    volumes: ['./published:/data:ro']
    environment:
      LORE_READ_ONLY: 'true'
      LORE_ALLOWED_HOSTS: '*' # or your public hostname
    restart: unless-stopped
```

First run: `mkdir -p data published && docker compose up -d`, then open http://127.0.0.1:8080.
Create both directories yourself: if Docker creates a missing bind-mount source, it is owned by
root and not writable by the container user. `LORE_UID`/`LORE_GID` default to `1000`; set them
(e.g. in a `.env` file next to the compose file) when `id -u`/`id -g` differ.

The `reader` service only becomes functional in M12 (reader mode and snapshot publishing, #142).

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
| `make help` | list the targets (default goal) |
| `make setup` | `uv sync` (backend) + `npm ci` (workspaces) + Playwright's Chromium |
| `make dev` | backend `uv run lore serve --reload` on :8000 **and** Vite on :5173 (proxy `/api` → :8000), data in `./data` (`LORE_DATA_DIR`); Ctrl-C, or either server exiting, stops both |
| `make check` | everything CI runs except e2e/docker: lint, format check, types, import contracts, tests, build, conformance, drift checks (= `make check-backend` + `make check-frontend` + `make check-contract` + `make check-chronology`) |
| `make test` / `make test-backend` / `make test-frontend` / `make test-chronology` | tests (`test-chronology`: both engines' chronology tests and conformance runners) |
| `make e2e` | build the SPA, start the backend serving it on a temp data dir, run Playwright (`scripts/e2e.sh`; `E2E_PORT`, `SKIP_BUILD=1`) |
| `make gen` | regenerate OpenAPI TS types and chronology JSON Schema/TS types |
| `make check-contract` | regenerate the OpenAPI TS types in memory and fail if the committed file differs ("run make gen") |
| `make check-chronology` | `lore chronology export-schemas --check` + `gen:schema --check`: fail if `spec/chronology/schema/*.json` or `schema.gen.ts` drifted from the Pydantic models |
| `make fmt` | ruff format + prettier |
| `make docker` | build the image (`lore-world-tracker:local`) |
| `make docker-smoke` | start the built image through `docker-compose.yml` in a temp project dir (host port 8080) and smoke-test it (`scripts/docker-smoke.sh`) |
| `make sample-vault SIZE=small` | generate the demo world into `./data` |

## 5. Versioning and releases

- One app version (SemVer) shared by `backend/pyproject.toml` and the npm workspaces, bumped
  together.
- Each completed milestone that has a release in `roadmap.md` (M2 → v0.1.0 through M12 →
  v1.0.0) ends with a release PR: version bump, `CHANGELOG.md` (Keep a Changelog) update, a **new
  golden fixture vault** (`persistence-and-migrations.md` §3.5), and tag `vX.Y.0`. M0 and M1 have
  no release: vaults don't exist before M2, so v0.1.0 is the first release that writes them.
  Their changes accumulate under `Unreleased` (`workflow.md` §11).
- Pre-1.0 versions may change the API freely (same-repo client). Vault data must stay
  upgradable across **every** version from the first release that wrote vaults.
