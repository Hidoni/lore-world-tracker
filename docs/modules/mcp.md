# Module: `mcp` — AI assistants (MCP)

> Serves a vault to AI assistants (Claude Desktop, Claude Code, any Model Context Protocol
> client) from the Lore server itself: search, entities and their state at a moment, events
> between dates, date conversion, and entities as resources. Off by default; the readers' view
> unless the author grants more. Design: `docs/architecture/mcp.md`, ADR 0017 (#150).

## Summary

| | |
|---|---|
| Module id | `mcp` |
| Depends on | – |
| Default enabled | **no** (enabling it in a vault is the opt-in, `security.md` §4) |
| Milestone | M13 (#395: the module, endpoint, token and read tools; #396: writes, settings page, bridge) |

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

One endpoint, `/api/v1/vaults/{v}/m/mcp` (not in the OpenAPI document): MCP's **Streamable
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

**Errors:** problems become tool errors (`isError`) whose text is `{code, title, detail, errors?,
context?}`; arguments that don't match the input schema are `validation_error` with the paths;
an unknown tool is `unknown_tool`.

### Resources

Every entity the policy shows is a resource `lore://{vault}/entities/{id}` (`text/markdown`: its
note, as in `get_entity`). `resources/list` pages them by name (100 a page);
`resources/templates/list` gives the template. Reading a hidden, trashed or unknown entity, or a
URI of another vault, is an `INVALID_PARAMS` error.

## UI

None yet: Settings → AI access (token, client configurations) comes with #396. Until then the
module is enabled in Settings → Modules, and its settings set through the API.

## Search, graph, visibility, backup, publish

- Visibility: every tool and resource reads through the services with the policy of `access`
  (the leak suite runs them all against the canary vault: `tests/visibility/test_mcp_leaks.py`).
- The token is a server secret: never in a vault, a backup or a published snapshot.
- Published snapshots keep the module's state and settings: a read-only server serves the
  endpoint for snapshots whose module is on, with the readers' policy.

## Disabling / removal notes

Disabling turns the endpoint into `404 module_disabled`; the settings are kept.

## Future ideas

Write tools, `undo_last`, the settings page and `lore mcp-bridge` (#396); text date input once
#157 parses typed dates.
