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

- `GET /m/characters/{id}/life?timeline=`: the events the character takes part in
  (`core.participant`) on a timeline, by start, with their roles (the Life panel; #92).

## UI

- Sidebar section "Characters" (alphabetical, grouped by first tag or by misc parent).
- Character page panels: **Relationships** (grouped, with validity and as-of state),
  **Family tree** (embedded, depth control), **Affiliations** (memberships, residence, species,
  languages), **Life** (existence, events participated in, age at each event).
- **Family tree view** (`/m/characters/{id}/family-tree`): generations top to bottom,
  spouses adjacent, multiple marriages supported, deceased at the cursor shown muted. Laid out
  by relatives-tree (the #93 spike, ADR-0015) and rendered in React Flow.
- **Relationship web** = the local graph filtered to character relationship types (graph module).

Implementation (#92): `backend/src/lore/modules/characters/` and
`frontend/src/modules/characters/`. `characters.serves` targets characters and groups (#94). Panels: **Relationships** (Family, Social, Other, with `data.kind`,
capacity and roles, and "Add relationship" through the link dialog), **Life** (the time
context's timeline), **Affiliations** (the `out` links of `groups.member_of`,
`locations.resides_in`, `locations.origin`, `species.is_a` and `languages.speaks` of the enabled
modules). As-of filtering comes with its own issue. The sample world has the royal house of Varn over three generations, a rival with a
secret and roles in events.

Family tree (#93): `GET /m/characters/{id}/family-tree` gathers the family generation by
generation, one set of links at a time:

- `up` generations of ancestors and `down` of descendants (0–10, default 3 each);
- with `include_siblings`, the siblings of the character and of their ancestors (linked
  siblings, and the other children of the parents in the tree);
- with `include_spouses`, everyone's spouses, and the other parents of children in the tree
  within the generations asked for (the parents of a half-sibling or a grandchild).

The response is `{root_id, people: [{id, name, visibility, generation, from_t, to_t}], edges:
[{id, kind: parent|spouse|sibling, source_id, target_id, relation}], truncated}` (`limit`, default
500 people). Only links the request sees, between characters outside the trash, count.
`from_t`/`to_t` (existence) are `null` until temporal facts land (M7). The UI shows "Lifespan
unknown" for now and will mute the deceased at the cursor. `timeline` is checked like other
reads.

The **Family tree** panel (character pages) shows two generations each way. Clicking a relative
re-centers the panel on them, with "Back to this character". The panel links to the view, which
starts at three generations. Both have generations up/down, Spouses, Siblings and "As a list"
(people by generation, with parents and spouses). In the view, a click re-centers on the
relative's tree, and the icon on a box opens the person's page. The layout is ADR-0015's
relatives-tree adapter: at most two parents a person (biological first), an "Unknown parent"
for siblings without recorded ones, and spouses on opposite sides.

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
