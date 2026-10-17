# Lore World Tracker

A locally hosted, single-user **living wiki for fictional worlds**, built around **strictly
tracked time**. Define dimensions with their own time flow (from inception to heat death),
interpret it through any number of calendars (as strange as your world needs), place events with
causes, effects, sub-events and recurrences, and connect characters, locations, species, groups,
languages and anything else into an explorable compendium. Timeline, graph, maps, alternate
timelines, time travelers and read-only sharing are all there.

> **Status:** the MVP (milestones M0–M12) is implemented; see the
> [changelog](CHANGELOG.md) and the [traceability](docs/plan/mvp-traceability.md) of every
> requirement. Post-MVP work lives in the
> [M13 backlog](https://github.com/Hidoni/lore-world-tracker/milestones).

## Highlights (MVP scope)

- **Vaults:** multiple independent universes, each a portable folder (SQLite + media).
- **Exact time:** arbitrary-precision integer time per dimension; calendars with leap rules,
  alternating year layouts, intercalary days, week/parallel cycles, eras, reforms and
  astronomical overlays.
- **Events:** precision and "circa" dates, live-linked relative anchors, sub-events, cause →
  effect chains, participants, and every kind of recurrence without ever storing occurrences in
  bulk.
- **World state over time:** relationships, fields and existence with validity periods; view
  anything "as of" any moment.
- **Advanced time:** alternate timelines (branches), cross-dimension time correspondences,
  personal timelines for time travelers.
- **Modules:** locations, species, characters, groups, languages (with lexicon), misc, media,
  interactive maps, custom fields & kinds, graph view. Each can be toggled per vault.
- **Explore:** zoomable timeline (cosmic scale down to the base unit), Obsidian-like graph,
  family trees, org charts, causality chains, backlinks, full-text search.
- **Share safely:** public/spoiler/private visibility down to individual text blocks; read-only
  server mode from sanitized published snapshots.

## Quick start

```bash
mkdir -p data published         # create them yourself so they stay writable by you
docker compose up -d            # author instance on http://127.0.0.1:8080 (LORE_UID/LORE_GID
                                # default to 1000; set them if `id -u`/`id -g` differ)
# development
make setup && make dev          # backend :8000, frontend :5173
```

## Documentation

New here? Read the [user guide](docs/guides/getting-started.md). Everything else starts at
[`docs/README.md`](docs/README.md). AI agents: read [`CLAUDE.md`](CLAUDE.md) first.
