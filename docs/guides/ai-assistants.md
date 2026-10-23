# Connecting AI assistants

Lore can serve a vault to AI assistants that speak the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP): Claude Desktop, Claude Code and
other MCP clients. An assistant connected to a vault can search it, read entities as they are at
any moment, list the events between two dates, convert dates between calendars and, if you let
it, add and change things. Every change it makes shows in **Recent changes** and can be undone.

The server does this itself: there is nothing extra to install for Claude Code, and Claude
Desktop runs a small bridge that comes with Lore. Details: `docs/modules/mcp.md`.

## 1. Turn it on for a vault

AI access is off in every vault until you turn it on:

1. **Settings → Modules**: turn on **AI assistants (MCP)**.
2. **Settings → AI access** (it appears once the module is on): choose what assistants get.

| Access | Assistants see |
|--------|----------------|
| What readers see (the default) | what a reader of a published snapshot sees: no private entities, fields, blocks or links, no history |
| Everything | all of it, private content included |

**Let assistants make changes** (only with access to everything) adds the write tools: create
and edit entities, add and remove links, set facts (values over time, existence, names), create
events, and undo. Assistants never delete entities, and removed links go to the trash.

## 2. Connect a client

**Settings → AI access** shows the server's **token** and ready-made configurations that hold
it. The token opens every vault of this server to whoever has it (as each vault's AI access
allows), so treat it like a password. **Regenerate** makes a new one; clients with the old token
stop working until you give them the new configuration. If the server's `LORE_MCP_TOKEN` sets the
token (`docs/architecture/deployment.md`), change it there.

**Claude Code** talks to the server directly. Copy the **Claude Code** command and run it in a
terminal:

```sh
claude mcp add --transport http lore-atlas http://127.0.0.1:8080/api/v1/vaults/<vault id>/m/mcp \
  --header "Authorization: Bearer <token>"
```

**Claude Desktop** starts local servers over stdio, so it runs `lore mcp-bridge`, which passes
each message on to the server. Copy the **Claude Desktop** configuration into
`claude_desktop_config.json` (Claude Desktop: Settings → Developer → Edit config) and restart
Claude Desktop. It needs the `lore` command on the same computer (a source checkout: `uv run
lore` in `backend/`, with the full path to `uv` as `command` and `run`, `lore` first in `args`).

With the suggested **Docker** setup (`docker-compose.yml`), run the bridge inside the container
instead; it finds the token itself:

```json
{
  "mcpServers": {
    "lore-atlas": {
      "command": "docker",
      "args": [
        "compose", "-f", "/path/to/docker-compose.yml", "exec", "-T", "lore",
        "lore", "mcp-bridge", "--vault", "<vault id>"
      ]
    }
  }
}
```

The bridge reports problems to the assistant, and on its stderr (Claude Desktop's MCP log): a
wrong token (`401`: copy the configuration again), the module off (`404`), or the server not
running.

## 3. Using it

Ask about your world in plain words: "Who ruled Varn when the Sundering happened?", "What
happened in the north between the years 1020 and 1030 of the Common Reckoning?", "Add a character
named Mira, a healer, born in 1003". Assistants start by listing the dimensions, so they know the
calendars and timelines, and give dates either as moments or in any calendar. Every date they get
back comes with its date in the dimension's default calendar.

What assistants read is your writing: Lore tells them to treat it as data, not as instructions,
and nothing in a vault can make them reach outside it (no tool fetches URLs or reads files).

## 4. Reviewing what an assistant changed

Each tool call that changes something is one entry in **Recent changes**, from **AI assistant**,
named after the tool and the client (“Created character “Mira” (MCP create_entity,
claude-code)”). Filter the list by that origin to see only theirs, and undo any entry as usual.
Assistants can undo their own newest change too (`undo_last`), unless you have edited what it
changed since.

Consistency rules apply to assistants as to you: a change that breaks an error-severity rule is
refused, and the assistant is told why, so it can fix its request. Assistants can't save past a
finding; only you can (`docs/guides/temporal-state.md`).

## 5. Turning it off

Switch writes off, choose **What readers see**, or turn the module off in **Settings → Modules**
(the endpoint then answers `404`). Regenerate the token to cut off every client at once.
