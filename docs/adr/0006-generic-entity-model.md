# ADR-0006: Generic entities with JSON fields and typed links

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

There are many kinds (core, modules, user-defined custom kinds) and they all need names, rich
text, search, linking, history, visibility, graph presence and temporal state. Fields evolve
often, and users can add their own (D16).

## Decision

- A single `entities` table with `kind`, common columns, `fields` (JSON, validated per kind by
  registry-defined field definitions) and `field_visibility`.
- **Relations are links, never fields:** a single `links` table with registry-defined link
  types (core, module, user-defined), optional validity periods and visibility.
- Extension tables only where structure demands it (dimensions, timelines, calendars, events,
  lexicon, maps…).
- Temporal field values are `entity_facts` rows (field key + value + validity).
- The frontend generates forms and pages from the registry, so a module with only kinds, fields and
  link types needs almost no UI code.

## Consequences

- Search, graph, backlinks, history and visibility are implemented once.
- Custom fields/kinds come almost for free.
- Field-level queries use JSON functions (fine at this scale). Indexes on JSON expressions can be
  added where needed.
- Field shape changes require data migrations of JSON (documented, tested).

## Alternatives considered

- One table per kind with typed columns: strict but every field change is a schema migration,
  custom fields need EAV anyway, and cross-kind features get duplicated.
- Pure EAV for everything: hard to validate and query, poor developer ergonomics.
