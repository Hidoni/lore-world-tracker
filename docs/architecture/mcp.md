# MCP: AI assistants and the vault (#150)

> Status: #395 implemented (module, endpoint, token, read tools and resources: `docs/modules/mcp.md`); #396 (writes, settings page, bridge) next (§9).

An opt-in module, `mcp`, exposes a vault through the [Model Context Protocol](https://modelcontextprotocol.io)
so an assistant (Claude Desktop, Claude Code, any MCP client) can search the world, read
entities and their state at a moment, list what happens between two dates in a calendar, and,
only when the author turns it on, write through the same services the app uses. Everything it
sees goes through the request's `VisibilityPolicy`, the readers' one unless the author grants
more; everything it writes is a changeset with `origin = "mcp"`, undoable like any other.

## 1. Goals and non-goals

- **Goals:** read tools good enough to answer questions about the world ("who ruled Varn when
  the Sundering began?"), calendar-aware date input and output, safe opt-in writes, the same
  semantics and visibility as the API, audit and undo of every write.
- **Non-goals:** a chat UI in the app; calling any AI service from the server (the server never
  makes outbound requests, `security.md` §4); exposing the whole REST API one-to-one; vector
  search or embeddings.

## 2. Transport: in the server process

The MCP endpoint is served by the Lore server itself, over MCP's **Streamable HTTP** transport at
`/api/v1/vaults/{vault}/m/mcp` (one endpoint per vault, the module's router), with the official
`mcp` Python SDK mounted as an ASGI app.

Why not a separate `lore mcp` process over stdio: per-vault engines and caches are in-process
(compiled calendars, windows, series, keyed by the vault's in-process write counter), so a
second process writing would leave the server's caches stale, and two processes reading would
each warm their own. One server, one worker, as `deployment.md` requires.

For clients that only speak stdio, `lore mcp-bridge --vault <id>` forwards stdio to the endpoint
(reading the token as below). It holds no vault state.

## 3. Opt-in and access levels

The module is **off by default** in every vault (`default_enabled = False`): enabling it in
Settings → Modules is the per-vault opt-in `security.md` §4 asks for. Its settings
(`settings_model`, stored in the vault):

| Setting | Values | Default |
|---|---|---|
| `access` | `readers` (the readers' policy: no private entities, fields, blocks, notes, history), `author` (everything) | `readers` |
| `writes` | `off`, `on` (needs `access = author`) | `off` |

A read-only server (`LORE_READ_ONLY`) serves the endpoint for published snapshots whose module is
on, always with the readers' policy and no writes.

## 4. Authentication

The endpoint needs `Authorization: Bearer <token>`:

- The token is a random 256-bit secret per server, stored outside vaults (they get shared and
  backed up, `security.md` §5): `<data dir>/secrets/mcp-token` (created on first use, mode
  `0600`), or `LORE_MCP_TOKEN`. Settings → AI access shows it with a copy button, regenerates it,
  and shows ready-made client configurations.
- **CSRF and DNS rebinding:** the Host allowlist applies as everywhere. The mutation guard
  accepts a valid bearer token on this route instead of `X-Lore-Client`: `Authorization` is not a
  simple header, so a cross-origin page can't send it without a preflight, which is never
  approved. `Origin`, when sent, must be allowed (the MCP specification asks servers to check
  it).
- Wrong or missing token: `401`. Module off: `404 module_disabled`, like every module route.

## 5. Tools

Results are compact JSON (the API's schemas where they exist), capped (`limit`, default 20, at
most 100) and paged with cursors. Moments are decimal strings, as in the API.

**Reading**

| Tool | What it does |
|---|---|
| `list_dimensions` | Dimensions with their calendars, timelines (prime first) and present. |
| `search` | The search expression (`api.md`, search) over the vault, with kind and dimension filters; hits with snippets. |
| `get_entity` | An entity by id, or by exact name or alias: summary, fields, body as Markdown (the Markdown export's renderer), tags, links and backlinks, and, with `at` (and `timeline`), its state then (existence, fields, links valid then). |
| `list_entities` | The entity list with its filters (kind, tag, dimension, parent, existing at a moment). |
| `events_between` | The events of a timeline overlapping a date range, ordered by start, with sub-events folded and series occurrences expanded (never stored, rule 4). |
| `convert_date` | A date in one calendar as a moment, and a moment as a date in each calendar (both chronology engines' semantics: `lore.chronology`). |

**Dates.** Every date argument is a moment, or a calendar date: `{calendar, fields}` (the
anchors' format: field values as strings, named units by slot id or name), or the typed text a
calendar accepts once text date parsing exists (#157). Every moment in a result comes with its
date in the dimension's default calendar.

**Writing** (only with `writes = on`)

| Tool | What it does |
|---|---|
| `create_entity` | Kind, name, dimension, parent, fields, tags, body (Markdown in, rich text stored). |
| `update_entity` | The same fields, with the entity's `revision` (optimistic concurrency, `409 conflict` on a stale one). |
| `add_link` / `remove_link` | A link of a registered type, with optional validity and role. |
| `set_fact` | A temporal value of a field (`core.exists` included) over a validity. |
| `create_event` | An event with anchors (absolute, calendar or relative to another event). |
| `undo_last` | Undoes the last changeset the MCP endpoint made, if nothing has changed it since. |

Each write is one request, one transaction, one changeset (rule 6): `origin = "mcp"`, the label
naming the tool and the client (`clientInfo.name` from the MCP handshake). The consistency
engine runs first; a refusal comes back as a tool error with the findings, so the assistant can
correct itself. No tool deletes entities (trash and purge stay in the app).

**Resources.** Each entity is also a resource, `lore://{vault}/entities/{id}`, as Markdown (the
readers' or the author's export, by `access`), so clients can attach entities as context.

## 6. Prompt injection

Vault content is data written by the author (or imported). It reaches an assistant that may
act on it, so:

- Writes are off unless the author turns them on, and every write is visible in History with its
  origin, and undoable.
- No tool reaches outside the vault (no URLs fetched, no files read, no other vaults: the
  endpoint is per vault).
- Destructive operations are not tools.

## 7. Errors, limits, logging

Problems (`api.md`) become MCP tool errors with their `code`, `title` and `detail`. Requests are
logged with the request id like any other (`lore.access`), and a write's changeset links to it.
Rate limits are unnecessary on a single-user local server; result caps keep answers small.

## 8. Tests

- Each tool against the leak canary vault with `access = readers`: no canary in any result,
  snippet or resource (the leak suite's byte scan, `visibility-and-sharing.md` §5).
- `author` access shows private data; `writes = off` refuses every write tool.
- Auth: missing, wrong and right tokens; an `Origin` the server doesn't allow; the module off.
- Writes: one changeset each, `origin = "mcp"`, undoable; consistency refusals as tool errors.
- Dates: calendar input and output through `convert_date` and `events_between` match the API's
  for the conformance calendars.
- An end-to-end test with the SDK's client over Streamable HTTP.

## 9. Implementation issues

1. #395: the module, endpoint, token auth, settings and the read tools and resources (with the leak
   tests and the client test).
2. #396: write tools, `undo_last`, origin `mcp` in History and its filter, the AI access settings page
   (token, client snippets), the stdio bridge and the user guide.
