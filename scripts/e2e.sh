#!/usr/bin/env bash
# e2e harness (testing.md §5): build the SPA, serve it from the backend on a temp data dir, wait for
# /api/v1/health, then run Playwright against it. `make e2e` and the CI `e2e` job both run this.
# Extra arguments go to Playwright (e.g. `scripts/e2e.sh --headed smoke`).
# E2E_PORT picks the port (default 8765); SKIP_BUILD=1 reuses an existing frontend/dist.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${E2E_PORT:-8765}"
base_url="http://127.0.0.1:${port}"

if [[ "${SKIP_BUILD:-}" != "1" ]]; then
  npm run build --prefix "$root" --workspaces
fi

data_dir="$(mktemp -d "${TMPDIR:-/tmp}/lore-e2e.XXXXXX")"
log_file="$data_dir/server.log"
server_pid=""

cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$data_dir"
}
trap cleanup EXIT INT TERM

LORE_DATA_DIR="$data_dir/data" LORE_STATIC_DIR="$root/frontend/dist" \
  uv --directory "$root/backend" run lore serve --host 127.0.0.1 --port "$port" >"$log_file" 2>&1 &
server_pid=$!

echo "e2e: waiting for $base_url/api/v1/health"
for _ in $(seq 1 60); do
  if curl -fsS "$base_url/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "e2e: the server exited before becoming healthy:" >&2
    cat "$log_file" >&2
    exit 1
  fi
  sleep 0.5
done
if ! curl -fsS "$base_url/api/v1/health" >/dev/null 2>&1; then
  echo "e2e: the server did not become healthy within 30 s:" >&2
  cat "$log_file" >&2
  exit 1
fi

status=0
(cd "$root/frontend" && E2E_BASE_URL="$base_url" npx playwright test -c e2e/playwright.config.ts "$@") ||
  status=$?
if [[ $status -ne 0 ]]; then
  echo "e2e: server log:" >&2
  cat "$log_file" >&2
fi
exit $status
