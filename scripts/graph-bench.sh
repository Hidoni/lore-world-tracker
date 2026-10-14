#!/usr/bin/env bash
# Graph benchmark (docs/modules/graph.md, testing.md §4): build the SPA, seed a temp data dir with
# a vault of 10k entities and 50k links (backend/scripts/make_graph_bench_vault.py), serve it, and
# measure the graph page in a headed Chromium (frontend/e2e/graph.bench.ts). `make bench-graph`
# runs this. Run it on a machine with a GPU: headless or GPU-less browsers draw WebGL in software.
# BENCH_PORT picks the port (default 8775); SKIP_BUILD=1 reuses frontend/dist; BENCH_HEADLESS=1
# runs headless; BENCH_NODES / BENCH_EDGES change the world's size. Extra arguments go to Playwright.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${BENCH_PORT:-8775}"
base_url="http://127.0.0.1:${port}"

if [[ "${SKIP_BUILD:-}" != "1" ]]; then
  npm run build --prefix "$root" --workspaces
fi

data_dir="$(mktemp -d "${TMPDIR:-/tmp}/lore-graph-bench.XXXXXX")"
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

echo "graph-bench: seeding ${BENCH_NODES:-10000} entities and ${BENCH_EDGES:-50000} links"
vault="$(uv --directory "$root/backend" run scripts/make_graph_bench_vault.py --out "$data_dir/data" \
  --nodes "${BENCH_NODES:-10000}" --edges "${BENCH_EDGES:-50000}" | tail -n 1)"

LORE_DATA_DIR="$data_dir/data" LORE_STATIC_DIR="$root/frontend/dist" \
  uv --directory "$root/backend" run lore serve --host 127.0.0.1 --port "$port" >"$log_file" 2>&1 &
server_pid=$!

for _ in $(seq 1 60); do
  if curl -fsS "$base_url/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "graph-bench: the server exited before becoming healthy:" >&2
    cat "$log_file" >&2
    exit 1
  fi
  sleep 0.5
done

(cd "$root/frontend" && E2E_BASE_URL="$base_url" BENCH_VAULT="$vault" \
  npx playwright test -c e2e/bench.config.ts "$@")
