# Module: `characters` — Characters

> People and persons in the world, with relationships to each other (family, social, custom),
> participation in events, and (with the `worldlines` module) personal timelines. Covers R-CHR-1.

## Summary

| | |
|---|---|
| Module id | `characters` |
| Depends on | – (uses `species`, `groups`, `locations`, `languages` link types when enabled) |
| Default enabled | yes |
| Milestone | M6 (views), M7 (temporal relationships UI) |

## Kinds

| Kind | Label / plural | Icon | Allowed parents | Capabilities |
|------|----------------|------|-----------------|--------------|
| `character` | Character / Characters | `user` | `misc` | body, existence (born/died), multiversal, worldline |

### Fields (`character`)

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `full_name` | `text` | yes | public | Legal/formal name. The entity name is the display name. |
| `epithet` | `text` | yes | public | "the Bold" |
| `title` | `text` | **yes** (multiple) | public | titles held over time |
| `gender` | `text` | yes | public | free text |
| `occupation` | `text` | yes (multiple) | public | |
| `appearance` | `long_text` | no | public | |
| `personality` | `long_text` | no | public | |
| `secret` | `long_text` | no | **private** | Example of a private-by-default field. Authors often keep secrets per character. |

Birth/death are **existence facts** anchored to events (UI labels "Born"/"Died", with the
shortcut "create birth event").

## Link types

| Key | Source → target | Labels | Symmetric | Temporal | Data |
|-----|-----------------|--------|-----------|----------|------|
| `characters.parent_of` | character → character | parent of / child of | no | optional (adoption) | `{kind: biological|adoptive|step|foster|other}` |
| `characters.sibling_of` | character ↔ character | sibling of | yes | never | `{kind: full|half|step|adoptive}` |
| `characters.spouse_of` | character ↔ character | spouse of | yes | optional | `{kind: marriage|partnership|betrothal}` |
| `characters.romance` | character ↔ character | romantic partner of | yes | optional | – |
| `characters.friend_of` | character ↔ character | friend of | yes | optional | – |
| `characters.rival_of` | character ↔ character | rival of | yes | optional | – |
| `characters.enemy_of` | character ↔ character | enemy of | yes | optional | – |
| `characters.mentor_of` | character → character | mentor of / student of | no | optional | – |
| `characters.serves` | character → character or group | serves / served by | no | optional | `{capacity}` |
| `characters.relationship` | character → character | (role label) | no | optional | generic, custom role label |

Users add more via custom link types (core). Memberships (`groups.member_of`), residence
(`locations.resides_in`), species (`species.is_a`) and languages (`languages.speaks`) come from
their modules.

## Tables

None.

## API

- `GET /m/characters/{id}/relationships?timeline=&at=`: all relationship links grouped by
  category (family, social, custom) with as-of filtering.
- `GET /m/characters/{id}/family-tree?up=3&down=3&include_spouses=true&include_siblings=true&timeline=`:
  nodes (with existence spans) and edges (parent/spouse/sibling) for the genealogy layout.

## UI

- Sidebar section "Characters" (alphabetical, grouped by first tag or by misc parent).
- Character page panels: **Relationships** (grouped, with validity and as-of state),
  **Family tree** (embedded, depth control), **Affiliations** (memberships, residence, species,
  languages), **Life** (existence, events participated in, age at each event).
- **Family tree view** (`/m/characters/{id}/family-tree`): generations top to bottom,
  spouses adjacent, multiple marriages supported, deceased at the cursor shown muted. Layout via
  elkjs layered with marriage junction nodes, rendered in React Flow. A spike decides whether a
  dedicated genealogy layout library is better (issue in M6).
- **Relationship web** = the local graph filtered to character relationship types (graph module).

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `characters.parent_born_after_child` | warning | parent's existence starts after the child's |
| `characters.concurrent_spouses` | off | more than one spouse link valid at once |

## Disabling / removal notes

Disabling hides characters and their link types. Removal would convert characters to `misc`
(category "Character") and family/social links to `core.related` with role labels.

## Future ideas

Age plausibility against species lifespan; ancestry statistics; relationship "strength" over time
charts; character arcs (states over time with notes).
