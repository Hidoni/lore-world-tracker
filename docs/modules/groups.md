# Module: `groups` — Groups

> Social and organizational groups (militaries, governments, guilds, secret societies, noble
> houses) with sub-groups, memberships, leadership, inter-group relations and territory, all over
> time. Covers R-GRP-1.

## Summary

| | |
|---|---|
| Module id | `groups` |
| Depends on | – (territory link type requires `locations`) |
| Default enabled | yes |
| Milestone | M6 |

## Kinds

| Kind | Label / plural | Icon | Allowed parents | Capabilities |
|------|----------------|------|-----------------|--------------|
| `group` | Group / Groups | `users` | `group` (sub-group), `misc` | body, existence (founded/dissolved), multiversal |

### Fields (`group`)

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `group_type` | `enum` | no | public | government, military, religion, guild, company, criminal, secret_society, noble_house, tribe, academic, political_party, other |
| `motto` | `text` | yes | public | |
| `ideology` | `long_text` | no | public | |
| `size` | `integer` | **yes** | public | |
| `headquarters_note` | `text` | yes | public | use `locations.resides_in` for a linked HQ |

## Link types

| Key | Source → target | Labels | Symmetric | Temporal | Data |
|-----|-----------------|--------|-----------|----------|------|
| `groups.member_of` | any (character, group, custom) → group | member of / members | no | optional | `{rank, title, is_leader: bool}` |
| `groups.led_by` | group → any (character usually) | led by / leads | no | optional | `{title}`. Succession = sequence of validity periods. |
| `groups.part_of` | group → group | part of / has part | no | optional | time-varying structure (in addition to the static `parent_id`) |
| `groups.allied_with` | group ↔ group | allied with | yes | optional | – |
| `groups.at_war_with` | group ↔ group | at war with | yes | optional | `{war_event_id?}` |
| `groups.vassal_of` | group → group | vassal of / overlord of | no | optional | – |
| `groups.controls` | group → location | controls / controlled by | no | optional | requires `locations` |

## Tables

None.

## API

- `GET /m/groups/{id}/org-chart?timeline=&at=&depth=`: sub-groups (by `parent_id` and active
  `part_of`) with their leaders and member counts as of a moment.
- `GET /m/groups/{id}/members?timeline=&at=&include_subgroups=`: members as of a moment, or the
  full membership history (no `at`).
- `GET /m/groups/{id}/leaders?timeline=`: leadership succession (ordered validity periods).
- `GET /m/groups/{id}/territory?timeline=&at=`: controlled locations.

## UI

- Sidebar section "Groups" (tree by sub-group).
- Group page panels: **Members** (as-of, with ranks; history toggle shows a Gantt of memberships),
  **Leadership** (succession list), **Structure** (sub-groups), **Relations** (alliances, wars,
  vassalage over time), **Territory**.
- **Org chart view** (React Flow + elkjs): sub-groups and leaders as of the cursor.

Implementation (#94): `backend/src/lore/modules/groups/` and `frontend/src/modules/groups/`.
`groups.controls` names the `location` kind, so it is offered only while the locations module is
enabled; `characters.serves` now also targets groups. The leadership succession is ordered by
the links' resolved validity (timeless leaders first). Panels:
**Members** (ranks, titles, leaders; "Include sub-groups"), **Structure** (sub-groups and
`part_of` parts), **Leadership**, **Group relations** (alliances, wars, vassalage; the core
Relations panel lists every link) and **Territory**. The sample world has the Empire of the Tides with
two ministries, House Varn (vassal), the private Whisperers and a war with the Free Shoals.

Org chart and membership Gantt (#95):

- `GET /m/groups/{id}/org-chart` walks `depth` levels (1–10, default 3) below the group. Each
  level brings sub-groups (`parent_id`) and parts (`part_of` links valid at `at`). Each unit has
  its leaders (`led_by`, with `data.title`) and a count of its own members (`member_of`), both
  limited to links valid at `at`, or all of them without `at`. Counts include only what the
  request sees. Units: at most 500 (`truncated`).
- Memberships (`/members`) report their resolved validity (`from_t`, `to_t`; #102 resolves it).
  Members, leaders and territory take `timeline` and `at` (the links valid then, #102).
- The **org chart view** (`/v/<vault>/m/groups/<group>/org-chart`, linked from the Structure
  panel) draws the units top down (ELK `mrtree`, React Flow). Parts hang from dashed edges, each
  box shows the leaders and member count, and a click opens the group. It has a "Levels" control
  and "As a list". It asks for the time context's cursor (`at`, `timeline`).
- The Members panel's **History** toggle shows a Gantt chart: one bar per membership, positioned
  with the `@lore/chronology` viewport over the known bounds (plus a margin). The axis uses the
  group's dimension's display calendar (`ticks`). Open bounds run to the edge (lighter), and the
  bounds read as dates in the display calendar ("always", "ongoing" when open). Until validity
  resolves, every bar spans the chart and a note says so.

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `groups.member_outside_group_existence` | warning | membership validity outside the group's existence |
| `groups.leader_not_member` | off | leader without an overlapping membership |

Implemented in `lore.modules.groups.consistency` (#106, `consistency.md` §6): a temporal
`member_of` link's validity within the group's existence; a `led_by` link overlapping (or
touching) one of the leader's `member_of` links to the group, a timeless one overlapping
everything.

## Disabling / removal notes

Disabling hides groups and their link types. Removal would convert groups to `misc` (category
"Group") and links to `core.related`.

## Future ideas

Territories drawn on maps over time (with `maps`); diplomatic-state matrices; group timelines
(founding, schisms, mergers) as event templates.
