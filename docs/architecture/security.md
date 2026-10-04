# Security

> Single-user, locally hosted, no authentication. The main risks are (1) other websites in the
> author's browser attacking the local server (CSRF, DNS rebinding), (2) leaking private lore
> through shared read-only deployments, and (3) malicious uploads or content. This document lists
> the mitigations implementations must keep.

## 1. Threat model

| Asset | Threat | Mitigation |
|-------|--------|------------|
| Author instance (writes) | CSRF from a malicious website (simple POST to `localhost`) | Mutations require the custom header `X-Lore-Client` (a cross-origin request with a custom header triggers a CORS preflight, which we never approve); no CORS allowed by default; `Origin` checked on mutations. |
| Author instance | DNS rebinding (attacker domain resolving to 127.0.0.1) | `Host` header allowlist (`LORE_ALLOWED_HOSTS`, default `localhost,127.0.0.1,[::1]` plus the configured host); others get `421`/`400`. |
| Author instance | Exposure to the LAN/internet | Binds to `127.0.0.1` by default. Docker compose publishes `127.0.0.1:8080:8080`. Exposing author mode publicly is unsupported and documented as such. |
| Private lore | Leaks through reader deployments | Published snapshots + visibility enforcement + leak test suite (`visibility-and-sharing.md`). |
| Browser (XSS) | Malicious rich text / names / SVG / links | Rich text is rendered from JSON by TipTap/React (no `dangerouslySetInnerHTML`). Allowed node types are validated server-side. Link marks are restricted to `http(s)`/`mailto`. CSP header. SVG uploads are not rendered inline (§3). |
| Server | Malicious uploads (zip bombs, path traversal, huge files) | Size limits, type allowlist, content sniffing, content-addressed paths, safe zip extraction for restores (§3). |
| Data | Accidental destruction | Trash, history/undo, pre-migration and scheduled backups, no in-place restore. |

## 2. HTTP hardening (backend middleware, M0)

Implemented as pure ASGI middlewares in `lore.core.api.middleware` (outermost first: security
headers → request context → host check → CORS (optional) → mutation guard → body size limit).

- **Host allowlist** (DNS rebinding): the `Host` header (port ignored, case-insensitive, IPv6 as
  `[::1]`) must be in `LORE_ALLOWED_HOSTS` or equal the configured `LORE_HOST` (unless it binds
  every interface, e.g. `0.0.0.0`). Otherwise `400 invalid_host`. `*` disables the check and is
  allowed **only** with `LORE_READ_ONLY=true` (startup error otherwise).
- **Mutation guard** (CSRF): methods other than GET/HEAD/OPTIONS require
  `X-Lore-Client: web|cli|test` (`test` for test clients), otherwise `403 missing_client_header`.
  If `Origin` is present it must be an `http(s)` origin whose host is allowed (as above) or one of
  `LORE_CORS_ORIGINS`, otherwise `403 bad_origin` (`Origin: null` is rejected).
- No CORS middleware unless `LORE_CORS_ORIGINS` is set (development only). It then allows those
  origins, all methods, and the `X-Lore-Client`, `X-Request-Id` and `Content-Type` headers.
- Headers on every response (including rejections and errors): `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`. Responses outside `/api` (the SPA) also
  get the CSP, defined once as `CONTENT_SECURITY_POLICY`:
  `default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'`
  (change it only there if a dependency needs it, and document why here). API responses don't
  carry it, so the developer docs at `/api/v1/docs` keep working.
- Request size limits: non-multipart bodies ≤ 10 MB (declared `Content-Length` or streamed bytes)
  → `413 payload_too_large`. `multipart/form-data` uploads are left to upload endpoints, which
  enforce `LORE_MAX_UPLOAD_MB` (default 50).
- **Request ids:** `X-Request-Id` is accepted if it matches `[A-Za-z0-9._:-]{1,128}`, otherwise a
  new UUIDv7 (hex) is generated. It is echoed on every response, stored in a contextvar, and
  included in every log record. One `lore.access` log line per request records the id, method,
  path, status and duration (uvicorn's access log is disabled).
- Errors never include stack traces unless `LORE_DEBUG=true`. Then `internal_error` problems add
  `context.exception` and `context.traceback`. Unexpected exceptions are always logged with their
  traceback.

## 3. Files

- Uploads: an allowlist of MIME types (images: png, jpeg, webp, gif, avif; documents: pdf, txt,
  md; fonts for the future scripts module). Type is verified by magic bytes, and images are
  decoded with Pillow (the dimension limit protects against decompression bombs). Files are stored
  by SHA-256 and never by user-provided names.
- SVG: accepted only as an attachment (`Content-Disposition: attachment`) and never rendered inline
  until a sanitizer is added (post-MVP).
- Serving: `Content-Type` from the stored record, `X-Content-Type-Options: nosniff`,
  `Content-Security-Policy: default-src 'none'; img-src 'self'; style-src 'unsafe-inline'` on
  media responses.
- Restore/import zips: reject absolute paths, `..`, backslashes, drive letters, symbolic links,
  duplicate entries and files the manifest doesn't list (or that aren't `lore.db`/`media/…`), cap
  the file count and the bytes actually extracted (not the declared sizes), and verify every
  checksum from the manifest. Extraction goes into a staging folder that is removed on any
  failure (`lore.core.vaults.backups`).
- Vault ids/folder names are validated (`^[a-z0-9-]+$`) before touching the filesystem.

## 4. Dependencies and supply chain

- Lockfiles are committed (`uv.lock`, `package-lock.json`). CI installs with frozen lockfiles
  (`uv sync --frozen`, `npm ci`).
- Dependabot (or Renovate) for both ecosystems, weekly and grouped (M0 issue).
- No runtime fetching of code. External calls are absent by default. Any future integration
  (AI/MCP) must be opt-in per vault.

## 5. Secrets

The app stores no secrets in the MVP. Future modules that need API keys read them from env vars or
a local secrets file outside vaults, never from vault data (vaults get shared and backed up).
