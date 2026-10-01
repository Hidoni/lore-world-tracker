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

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `groups.member_outside_group_existence` | warning | membership validity outside the group's existence |
| `groups.leader_not_member` | off | leader without an overlapping membership |

## Disabling / removal notes

Disabling hides groups and their link types. Removal would convert groups to `misc` (category
"Group") and links to `core.related`.

## Future ideas

Territories drawn on maps over time (with `maps`); diplomatic-state matrices; group timelines
(founding, schisms, mergers) as event templates.
