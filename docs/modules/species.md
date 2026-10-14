# Module: `species` — Species

> Peoples, creatures and organisms, with subspecies, descent and origin. They can take part in
> events. Covers R-SPC-1.

## Summary

| | |
|---|---|
| Module id | `species` |
| Depends on | – (uses `locations` link types when enabled) |
| Default enabled | yes |
| Milestone | M6 |

## Kinds

| Kind | Label / plural | Icon | Allowed parents | Capabilities |
|------|----------------|------|-----------------|--------------|
| `species` | Species / Species | `dna` | `species` (subspecies, breed), `misc` | body, existence (emerged/extinct), multiversal |

### Fields (`species`)

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `classification` | `text` | no | public | taxonomy/free text |
| `sapience` | `enum` | no | public | non_sapient, semi_sapient, sapient, unknown |
| `typical_lifespan` | `duration` | no | public | calendar duration (used by future "age plausibility" rules) |
| `maturity_age` | `duration` | no | public | |
| `average_height` | `measurement` | no | public | |
| `average_mass` | `measurement` | no | public | |
| `diet` | `text` | no | public | |
| `population` | `integer` | **yes** | public | |

## Link types

| Key | Source → target | Labels | Symmetric | Temporal | Data |
|-----|-----------------|--------|-----------|----------|------|
| `species.is_a` | any (character, custom kinds…) → species | is a / members | no | optional (transformations) | – |
| `species.descended_from` | species → species | descended from / ancestor of | no | optional (`valid_from` = divergence) | – |
| `species.native_to` | species → location | native to / native species | no | optional | requires `locations` |

## Tables

None.

## API

- `GET /m/species/{id}/members?timeline=&at=`: entities that are this species (as of).
- `GET /m/species/descent-tree?dimension=`: graph of `descended_from` (nodes + edges) for the
  evolution view.

## UI

- Sidebar section "Species" (tree by subspecies).
- Species page panels: **Members** (as-of), **Descent** (ancestors/descendants), **Native to**.
- **Descent tree view** (React Flow + elkjs, time-ordered by emergence).
- Character pages show the species as a header chip (from `species.is_a`).

Implementation (#91): `backend/src/lore/modules/species/` and `frontend/src/modules/species/`.
`species.native_to` names the `location` kind, so it is offered only while the locations module is
enabled. Panels: **Members**, **Descent** (descended from, ancestor of, subspecies; a link to the
tree view) and **Native to**. The descent tree view (`/v/<vault>/m/species/descent-tree`, also in
the command palette) draws the time context's dimension with React Flow and ELK (ancestors above
descendants, subspecies dotted) with an "As a list" alternative; ordering by emergence comes with
existence (M7). The species chip is the module's `entityHeaderMedia` for `character`. The sample
world has First Folk → Tideborn (with Shoal Tideborn), the multiversal Leviathans, members and a
native land.

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `species.member_before_emergence` | warning | a member exists before the species emerged (or after extinction) |

Implemented in `lore.modules.species.consistency` (#106, `consistency.md` §6): each existence
period of an `is_a` member within the species' existence (one finding per pair and timeline).

## Disabling / removal notes

Disabling hides species and their link types. Removal would convert species to `misc` (category
"Species") and `is_a` links to `core.related` with role "species".

## Future ideas

Age plausibility rules (a character older than the typical lifespan); hybrid species (multiple
`descended_from` with weights).
