#!/usr/bin/env bash
# Page benchmarks (testing.md §4, frontend.md §12): build the SPA, generate the sample world into a
# temp data dir (backend/scripts/make_sample_vault.py), serve it, and measure the entity page and
# the timeline in Chromium (frontend/e2e/pages.bench.ts). `make bench-pages` runs this.
# BENCH_SIZE picks the world (default small: 1,000 bulk events); BENCH_DATA_DIR reuses a data dir
# that already holds one vault (e.g. a cached `large` world) instead; BENCH_PORT picks the port
# (default 8776); SKIP_BUILD=1 reuses frontend/dist; BENCH_HEADLESS=1 runs headless. Extra
# arguments go to Playwright.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${BENCH_PORT:-8776}"
base_url="http://127.0.0.1:${port}"

if [[ "${SKIP_BUILD:-}" != "1" ]]; then
  npm run build --prefix "$root" --workspaces
fi

temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/lore-pages-bench.XXXXXX")"
log_file="$temp_dir/server.log"
server_pid=""

cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$temp_dir"
}
trap cleanup EXIT INT TERM

if [[ -n "${BENCH_DATA_DIR:-}" ]]; then
  data_dir="$BENCH_DATA_DIR"
else
  data_dir="$temp_dir/data"
  echo "pages-bench: generating the ${BENCH_SIZE:-small} sample world"
  uv --directory "$root/backend" run scripts/make_sample_vault.py --size "${BENCH_SIZE:-small}" \
    --out "$data_dir" >/dev/null
fi

LORE_DATA_DIR="$data_dir" LORE_STATIC_DIR="$root/frontend/dist" \
  uv --directory "$root/backend" run lore serve --host 127.0.0.1 --port "$port" >"$log_file" 2>&1 &
server_pid=$!

for _ in $(seq 1 120); do
  if curl -fsS "$base_url/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "pages-bench: the server exited before becoming healthy:" >&2
    cat "$log_file" >&2
    exit 1
  fi
  sleep 0.5
done

vault="$(curl -fsS "$base_url/api/v1/vaults" | python3 -c 'import json, sys; print(json.load(sys.stdin)["items"][0]["id"])')"

(cd "$root/frontend" && E2E_BASE_URL="$base_url" BENCH_VAULT="$vault" \
  npx playwright test -c e2e/bench.config.ts pages.bench.ts "$@")
