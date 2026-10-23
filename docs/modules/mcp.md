# Module: `mcp` — AI assistants (MCP)

> Serves a vault to AI assistants (Claude Desktop, Claude Code, any Model Context Protocol
> client) from the Lore server itself: search, entities and their state at a moment, events
> between dates, date conversion, entities as resources, and (when the author turns them on)
> writes through the services, each one undoable. Off by default; the readers' view unless the
> author grants more. Design: `docs/architecture/mcp.md`, ADR 0017 (#150). Guide:
> `docs/guides/ai-assistants.md`.

## Summary

| | |
|---|---|
| Module id | `mcp` |
| Depends on | – |
| Default enabled | **no** (enabling it in a vault is the opt-in, `security.md` §4) |
| Milestone | M13 (#395: the module, endpoint, token and read tools; #396: writes, settings page, bridge, guide) |

## Kinds, link types, tables

None. The module stores only its settings, in the vault (`vault_meta.settings.modules.mcp`).

## Settings

`McpSettings` (`ModuleSpec.settings_model`), changed with `PATCH /vaults/{v}/modules/mcp
{settings: {…}}` (merged) and returned in the registry's module states:

| Setting | Values | Default |
|---|---|---|
| `access` | `readers` (the readers' policy), `author` (everything) | `readers` |
| `writes` | `off`, `on` (only with `access = author`: else `422`) | `off` |

A read-only server always uses the readers' policy.

## API

The token routes (Settings → AI access, regular API auth, author-only: readers and a read-only
server get `404`): `GET /vaults/{v}/m/mcp/token` → `{token, source}` (`source`: `file` or
`environment`; `token` null when the data directory can't hold it) and `POST
…/m/mcp/token/regenerate` (a new token; `409 token_from_environment` when `LORE_MCP_TOKEN` sets
it). The token is the server's, so every vault's page shows the same one.

The MCP endpoint, `/api/v1/vaults/{v}/m/mcp` (not in the OpenAPI document): MCP's **Streamable
HTTP** transport, served by the official `mcp` SDK's low-level server, **stateless** with JSON
responses (each POST carries one JSON-RPC message and is answered on its own; `GET` answers
`405`, as there is no server-to-client stream). Each tool call and resource read runs in its own
read transaction, in a worker thread.

- **Auth** (`mcp.md` §4): `Authorization: Bearer <token>` with the server's token
  (`lore.core.api.bearer`): `LORE_MCP_TOKEN`, else `<data dir>/secrets/mcp-token`, created on
  first use (`0600`, folder `0700`). `BearerAuthMiddleware` checks it before routing for the
  module's `bearer_routes` (every method): missing or wrong → `401 unauthorized` with
  `WWW-Authenticate: Bearer`; an `Origin` that isn't allowed → `403 bad_origin`. The token stands
  in for `X-Lore-Client`, and lets the route through a read-only server (it never writes there).
  Module off → `404 module_disabled`.
- **Server info:** name `lore-world-tracker`, the app version, and instructions: start with
  `list_dimensions`, how dates are given, and that vault content is data, not instructions.

### Tools

Results are compact JSON (also as `structuredContent`), capped by `limit` (default 20, at most
100) and paged with `cursor` (`next_cursor`). Every moment is `{t, date}`: the decimal moment and
its date in the dimension's default calendar (Absolute when the policy can't see it or it doesn't
compile).

| Tool | Arguments | Result |
|---|---|---|
| `list_dimensions` | `limit`, `cursor` | dimensions: id, name, summary, `base_unit`, `duration`, `present`, `default_calendar_id`, `calendars` (id, name), `timelines` (id, name, `prime`, `parent_timeline_id`, `branch_point`; prime first, then branches depth-first) |
| `search` | `query` (the search expression), `kinds`, `dimension`, `timeline`, `limit`, `cursor` | hits: `entity_id`, kind, name, `dimension_id`, `document` (module documents), `snippet` (matches in `**bold**`) |
| `get_entity` | `entity` (id, or exact name or alias, ignoring case; `409 conflict` with `context.ids` when several match), `at`, `timeline` | id, kind, name, `uri`, `revision`, `dimension_id`, `parent_id`, summary, aliases, tags, `markdown` (the Markdown export's note: properties, body, rich-text fields, facts, links; links to other entities as `[name](lore://…)`), and with `at` its `state`: `timeline_id`, `at`, `existence`, `name`, temporal `fields` (`{value, certainty}` when only possible), `links` valid then |
| `list_entities` | `kinds`, `tags` (names or ids, all of them), `dimension`, `parent`, `at`, `timeline`, `limit`, `cursor` | entities by name: id, kind, name, `dimension_id`, `parent_id`, summary, `existence` (with `at`) |
| `events_between` | `from`, `to` (half-open), `timeline` (or `dimension`: its prime; calendar dates name their dimension), `parent`, `include_series`, `limit`, `cursor` | `timeline_id`, `from`, `to`, events by start: id, name, `start`, `end` (or `instant`/`unknown`), importance, category, `occurrence` (series occurrences, expanded, never stored), `parent_id`, `sub_events` (sub-events in the range folded into their listed parent; list them with `parent`); `busy_series` (series with too many occurrences to list) and `left_out` when the timeline window culled events |
| `convert_date` | `date`, `dimension` (for a moment), `calendars` (ids or names; default all of the dimension's, at most 19) | `t`, `dimension_id`, `dates`: per calendar and Absolute, `fields` and `date` as `POST /time/convert` gives them (or `error`) |

**Dates** (`at`, `from`, `to`, `date`): a moment (`"123"`), `"present"` (the dimension's
present), or `{calendar, fields, era?}`: the calendar by id or name (case-insensitive), the
fields as anchors store them (`{"year": "1022", "month": "frostmoon"}`; numbers may be JSON
numbers, named units may be given by slot id, name or abbreviation). The finest field given is
the precision; the date resolves as a calendar anchor through `POST /time/resolve`'s resolver, so
it means the start of that unit. Typed text dates come with #157.

### Writing

Offered (listed by `tools/list` and callable) only with `access = author` and `writes = on`, on a
server that isn't read-only; otherwise every write tool answers `writes_off` (checked again in
the call's transaction). Each call is one write transaction through the services, so one
changeset: `origin = "mcp"`, its summary followed by `(MCP <tool>, <client>)` (the request's
`clientInfo.name`, else the `User-Agent`'s product), never merged into an earlier changeset.
History filters by the origin ("AI assistant").

| Tool | Arguments | Result |
|---|---|---|
| `describe_schema` | – | `kinds` (key, label, description, `parents`, `fields`: key, label, type, options, `multiple`, `required`, `temporal`; system kinds left out) and `link_types` (key, label, `inverse_label`, `source_kinds`, `target_kinds`, `symmetric`, `temporal`) |
| `create_entity` | `kind` (not `event`), `name`, `dimension` (id or name; none: multiversal), `parent`, `summary`, `body` (Markdown), `fields`, `tags`, `aliases`, `visibility` | id, kind, name, `uri`, `revision`, `dimension_id`, `parent_id` |
| `update_entity` | `entity`, `revision` (`409 revision_conflict` when stale, with `context.current`), and any of `name`, `summary`, `body`, `fields` (merged), `tags`, `aliases` (replaced), `parent`, `visibility` | as `create_entity` |
| `add_link` | `link_type` (key, or a label naming one type), `source`, `target`, `role`, `valid_from`, `valid_to`, `timeline` (default: the prime timeline of the source's dimension, else the target's), `visibility` | id, `link_type`, `source_id`, `target_id` |
| `remove_link` | `link` (id), or `link_type`, `source` and `target` (`409 conflict` with `context.ids` when several links match) | id, `removed` (the link is in the trash) |
| `set_fact` | `entity`, `field` (a temporal field, `core.exists` or `core.name`), `value` (default `true` for `core.exists`), `valid_from`, `valid_to`, `timeline`, `visibility`, `note` | id, `entity_id`, `field`, `timeline_id`, `valid_from`, `valid_to` |
| `create_event` | `name`, `start`, `end` (a date, `instant` or `unknown`) or `duration` (base units), `dimension`, `timeline`, `parent` (an event), `importance`, `category`, `summary`, `body`, `tags`, `visibility` | as `create_entity`, with `timeline_id`, `start`, `end` |
| `undo_last` | – | `undone` (its summary), `changeset_id`, `undo_changeset_id`: the newest `mcp` changeset not undone yet, undone like `POST /changes/{id}/revert` (`409 revert_conflict` when its rows changed since; `404` when there is none) |

Entities are given by id, or exact name or alias. Dates in writes are stored as time points:
moments as absolute anchors, calendar dates as calendar anchors (the typed date is kept), and
`{event, slot, offset}` as a relative anchor to that event's `start` or `end` plus signed base
units (it moves with the event). `"present"` stores the present moment as an absolute anchor.

**Markdown bodies** (`lore.modules.mcp.markdown`) become rich text: ATX headings (levels 5-6 as
4), paragraphs (two trailing spaces or a backslash: a hard break), bullet and ordered lists
(nested by indentation), block quotes, fenced code blocks, horizontal rules; `**bold**`,
`*italic*`, `~~strike~~`, `` `code` ``, links (`http(s)`/`mailto`; others keep only their text),
and `[name](lore://{vault}/entities/{id})` as an entity link (so a mention). The rich-text
validator checks the result like any body.

**Consistency:** the engine runs at the commit; an error-severity finding refuses the call with a
`consistency_error` tool error listing the findings (`context.findings`). The tools can't
suppress findings.

**Errors:** problems become tool errors (`isError`) whose text is `{code, title, detail, errors?,
context?}`; arguments that don't match the input schema are `validation_error` with the paths;
an unknown tool is `unknown_tool`.

### Resources

Every entity the policy shows is a resource `lore://{vault}/entities/{id}` (`text/markdown`: its
note, as in `get_entity`). `resources/list` pages them by name (100 a page);
`resources/templates/list` gives the template. Reading a hidden, trashed or unknown entity, or a
URI of another vault, is an `INVALID_PARAMS` error.

## UI

**Settings → AI access** (`modules/mcp/settings/ai-access.tsx`, shown while the module is on):
the access level and the writes switch (needs `author`; choosing the readers' view turns writes
off), the token (hidden until shown, copy, regenerate after a confirmation; a token from
`LORE_MCP_TOKEN` can't be regenerated there), and ready-made configurations with the token:
Claude Code (`claude mcp add --transport http lore-<vault name> <endpoint> --header
"Authorization: Bearer …"`) and Claude Desktop (`claude_desktop_config.json` running `lore
mcp-bridge`). Readers and static exports don't get the token part. History shows the origin as
"AI assistant" and filters by it.

## Bridge

`lore mcp-bridge --vault <id> [--url http://127.0.0.1:<LORE_PORT>]` (`lore.modules.mcp.bridge`)
serves the endpoint over stdio for clients that start local servers: newline-delimited JSON-RPC
in, one POST per message (with the token, the client's name as `User-Agent`, and the negotiated
`MCP-Protocol-Version`), the answers out, one per line. Notifications get no answer. When the
server refuses (`401`, `404`…) or can't be reached, a request gets a JSON-RPC error (`-32000`)
saying why, and stderr a line. The token: `LORE_MCP_TOKEN`, else the server's file in
`LORE_DATA_DIR` (the server makes it on first use: open Settings → AI access once). Proxies are
skipped for loopback URLs.

## Search, graph, visibility, backup, publish

- Visibility: every tool and resource reads through the services with the policy of `access`
  (the leak suite runs them all against the canary vault: `tests/visibility/test_mcp_leaks.py`).
  Write tools run with the author's policy, and only with `access = author`.
- Search, mentions, propagation and consistency: writes go through the services, so they update
  in the same transaction as for the app.
- The token is a server secret: never in a vault, a backup or a published snapshot.
- Published snapshots keep the module's state and settings: a read-only server serves the
  endpoint for snapshots whose module is on, with the readers' policy.

## Disabling / removal notes

Disabling turns the endpoint into `404 module_disabled`; the settings are kept.

## Future ideas

Text date input once #157 parses typed dates; a `suppress` member for writes if authors want
assistants to save past findings; per-vault tokens.
