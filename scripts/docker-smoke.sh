#!/usr/bin/env bash
# Container smoke test (testing.md §5): start the already-built image through docker-compose.yml in
# a throwaway project directory, wait for the healthcheck, then check that the API and the SPA
# answer, that the process is not root, and that /data writes land in the host's ./data. Then the
# sharing workflow (docs/guides/sharing.md): publish a vault, start the `reader` profile, and
# check that it serves the snapshot read-only without the private entity.
# `make docker-smoke` and the CI `docker` job run this after `make docker`.
# Uses host ports 8080 and 8081 (as docker-compose.yml does).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base_url="http://127.0.0.1:8080"
reader_url="http://127.0.0.1:8081"
client=(-H 'X-Lore-Client: web' -H 'Content-Type: application/json')
project_dir="$(mktemp -d "${TMPDIR:-/tmp}/lore-docker-smoke.XXXXXX")"
mkdir -p "$project_dir/data" "$project_dir/published"
export LORE_UID LORE_GID
LORE_UID="$(id -u)"
LORE_GID="$(id -g)"

compose() {
  docker compose -f "$root/docker-compose.yml" --project-directory "$project_dir" \
    -p lore-smoke "$@"
}

cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    echo "docker-smoke: container log:" >&2
    compose --profile reader logs >&2 || true
  fi
  compose --profile reader down --volumes --timeout 5 >/dev/null 2>&1 || true
  rm -rf "$project_dir"
  exit $status
}
trap cleanup EXIT

fail() {
  echo "docker-smoke: $*" >&2
  exit 1
}

echo "docker-smoke: starting the lore service"
compose up -d --no-build --wait --wait-timeout 60 lore

echo "docker-smoke: GET /api/v1/health"
curl -fsS "$base_url/api/v1/health" >/dev/null || fail "/api/v1/health did not return 2xx"

echo "docker-smoke: GET /api/v1/meta"
meta="$(curl -fsS "$base_url/api/v1/meta")" || fail "/api/v1/meta did not return 2xx"
grep -Eq '"app_version": *"[0-9]+\.[0-9]+\.[0-9]+' <<<"$meta" || fail "no app_version in /api/v1/meta: $meta"

echo "docker-smoke: GET / (SPA shell)"
index="$(curl -fsS "$base_url/")" || fail "/ did not return 2xx"
grep -q '<div id="root">' <<<"$index" || fail "/ is not the SPA shell"
spa_route="$(curl -fsS "$base_url/some/client/route")" || fail "SPA fallback did not return 2xx"
[[ "$spa_route" == "$index" ]] || fail "SPA fallback did not serve index.html"

echo "docker-smoke: container user is not root"
uid="$(compose exec -T lore id -u)"
[[ "$uid" != "0" ]] || fail "the container runs as root"

echo "docker-smoke: /data persists in the host directory"
compose exec -T lore sh -c 'echo ok > /data/.smoke'
[[ "$(cat "$project_dir/data/.smoke")" == "ok" ]] || fail "/data is not the host's ./data"

echo "docker-smoke: publish a vault with a public and a private entity"
json_field() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }
vault="$(curl -fsS "${client[@]}" -d '{"name": "Smoke"}' "$base_url/api/v1/vaults" | json_field '["id"]')"
dimension='{"kind": "dimension", "name": "Aetheria", "ext": {"base_unit": {"singular": "second",
  "plural": "seconds", "abbr": "s"}, "duration": "1000000000000"}}'
curl -fsS "${client[@]}" -d "$dimension" "$base_url/api/v1/vaults/$vault/entities" >/dev/null ||
  fail "could not create the dimension"
secret='{"kind": "misc", "name": "Smoke secret", "visibility": "private"}'
curl -fsS "${client[@]}" -d "$secret" "$base_url/api/v1/vaults/$vault/entities" >/dev/null ||
  fail "could not create the private entity"
curl -fsS "${client[@]}" -X POST "$base_url/api/v1/vaults/$vault/publish" >/dev/null ||
  fail "publishing failed"
ls "$project_dir/published/vaults/"*/vault.json >/dev/null || fail "no snapshot in ./published"

echo "docker-smoke: starting the reader profile"
compose --profile reader up -d --no-build --wait --wait-timeout 60 reader

echo "docker-smoke: the reader is read-only and serves the snapshot"
reader_meta="$(curl -fsS "$reader_url/api/v1/meta")" || fail "reader /api/v1/meta failed"
grep -Eq '"read_only": *true' <<<"$reader_meta" || fail "the reader is not read-only: $reader_meta"
names="$(curl -fsS "$reader_url/api/v1/vaults/$vault/entities" |
  json_field '["items"]' | tr -d "'")" || fail "reader GET entities failed"
grep -q 'Aetheria' <<<"$names" || fail "the reader doesn't serve the dimension: $names"
! grep -q 'Smoke secret' <<<"$names" || fail "the reader serves the private entity"
status="$(curl -sS -o /dev/null -w '%{http_code}' "${client[@]}" -d '{"name": "X"}' \
  "$reader_url/api/v1/vaults")"
[[ "$status" == "403" ]] || fail "a POST to the reader answered $status, not 403"
index="$(curl -fsS "$reader_url/")" || fail "reader / did not return 2xx"
grep -q '<div id="root">' <<<"$index" || fail "the reader's / is not the SPA shell"

echo "docker-smoke: ok"
