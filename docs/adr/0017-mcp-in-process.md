# ADR-0017: An opt-in MCP module served by the Lore server

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

Authors want AI assistants to answer questions about their world and, sometimes, to write into
it (#150). The Model Context Protocol is how assistants (Claude Desktop, Claude Code and others)
reach tools and data. Constraints:

- The vault's semantics (calendars, recurrence, timelines, visibility) live in the server's
  services. An assistant must see them, not a reimplementation.
- `security.md` §4: integrations are opt-in per vault, and the server makes no outbound calls.
  `security.md` §5: no secrets in vault data.
- Per-vault engines and caches are in-process, keyed by an in-process write counter
  (`deployment.md`: one worker).
- Vault content can carry instructions an assistant might follow (prompt injection).

## Decision

- **A module, `mcp`, off by default**: turning it on in a vault is the opt-in. Its settings choose
  the access level (`readers` by default, or `author`) and whether writes are on (off by default;
  only with `author`).
- **Served by the Lore server**, over MCP's Streamable HTTP transport, one endpoint per vault
  (`/api/v1/vaults/{vault}/m/mcp`), with the official `mcp` Python SDK. A `lore mcp-bridge`
  command forwards stdio for clients that need it, and holds no state.
- **Bearer token auth**: a per-server secret outside vaults (`<data dir>/secrets/mcp-token` or
  `LORE_MCP_TOKEN`). The CSRF guard accepts it in place of `X-Lore-Client` on this route.
- **Tools over services**: a small set of read tools (search, entities, state at a moment, events
  between dates, date conversion) and opt-in write tools (create and update entities, links,
  facts, events; undo the last MCP changeset). Every read goes through the `VisibilityPolicy`
  of the access level. Every write is one changeset with `origin = "mcp"`, checked by the
  consistency engine and undoable. No delete tools.
- Design: `docs/architecture/mcp.md`.

## Consequences

- Assistants get the same answers as the app, with calendar-aware dates, and the same visibility
  guarantees (leak tests cover the tools).
- A new runtime dependency (`mcp`), and a second protocol surface to keep in step with the API
  when services change.
- Writes by an assistant are as auditable and reversible as the author's own; destructive
  actions stay manual.
- Clients must be configured with the token; Settings shows ready-made configurations.

## Alternatives considered

- **A separate `lore mcp` stdio process** opening the vault itself: simplest for clients, but its
  writes would leave the server's caches stale and its own caches cold. It could only be safe if
  the server were stopped.
- **Exposing the REST API through a generic OpenAPI-to-MCP adapter**: hundreds of endpoints,
  shapes made for the UI, and no single place to enforce access levels and write opt-in.
- **Reader access only, no writes**: safer, but issue #150 asks for opt-in writes. With writes
  off by default, as changesets that can be undone, and with no deletes, the risk is
  contained.
