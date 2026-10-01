# Documentation index

## Reading paths

| You are… | Read, in order |
|----------|----------------|
| Any agent starting work | `../CLAUDE.md` → `plan/workflow.md` → your issue → the spec sections it links |
| New to the project | `product/vision.md` → `product/glossary.md` → `architecture/overview.md` → `architecture/time-model.md` |
| Working on time/calendars/recurrence | `architecture/time-model.md` → `architecture/chronology-engine.md` → `architecture/recurrence.md` → ADR-0003/0004/0007/0008/0009 |
| Working on the backend platform | `architecture/data-model.md` → `architecture/persistence-and-migrations.md` → `architecture/api.md` → `architecture/modules.md` → `architecture/visibility-and-sharing.md` |
| Working on the frontend | `architecture/frontend.md` → `architecture/api.md` → `architecture/modules.md` §3 |
| Working on a module | `architecture/modules.md` → `modules/<id>.md` |

## Contents

### Product
- [`product/vision.md`](product/vision.md): what we're building, principles, non-goals, MVP definition
- [`product/requirements.md`](product/requirements.md): original brief, decisions D1–D16, numbered requirements
- [`product/glossary.md`](product/glossary.md): canonical vocabulary

### Architecture
- [`architecture/overview.md`](architecture/overview.md): system, stack, repo layout, layering, golden rules
- [`architecture/time-model.md`](architecture/time-model.md): **normative** time model
- [`architecture/chronology-engine.md`](architecture/chronology-engine.md): **normative** calendar format and algorithms
- [`architecture/recurrence.md`](architecture/recurrence.md): **normative** recurrence rules and algorithms
- [`architecture/data-model.md`](architecture/data-model.md): tables, fields, links, facts, history, search
- [`architecture/modules.md`](architecture/modules.md): module system and catalog
- [`architecture/persistence-and-migrations.md`](architecture/persistence-and-migrations.md): vault format, SQLite, migrations, backups
- [`architecture/api.md`](architecture/api.md): API conventions and endpoint catalog
- [`architecture/frontend.md`](architecture/frontend.md): SPA architecture, editor, timeline view
- [`architecture/consistency.md`](architecture/consistency.md): rule engine and catalog
- [`architecture/visibility-and-sharing.md`](architecture/visibility-and-sharing.md): visibility, read-only mode, publishing, leak tests
- [`architecture/security.md`](architecture/security.md): threat model and mitigations
- [`architecture/testing.md`](architecture/testing.md): test strategy, CI, performance budgets
- [`architecture/deployment.md`](architecture/deployment.md): configuration, Docker, compose, dev environment

### Modules
[`modules/_template.md`](modules/_template.md) · [`misc`](modules/misc.md) ·
[`locations`](modules/locations.md) · [`species`](modules/species.md) ·
[`characters`](modules/characters.md) · [`groups`](modules/groups.md) ·
[`languages`](modules/languages.md) · [`media`](modules/media.md) · [`maps`](modules/maps.md) ·
[`custom_fields`](modules/custom_fields.md) · [`graph`](modules/graph.md) ·
[`branches`](modules/branches.md) · [`correspondences`](modules/correspondences.md) ·
[`worldlines`](modules/worldlines.md)

### Decisions
- [`adr/README.md`](adr/README.md): architecture decision records

### Plan
- [`plan/roadmap.md`](plan/roadmap.md): milestones, dependency graph, issue index
- [`plan/workflow.md`](plan/workflow.md): agent workflow and definition of done
- [`plan/planning-log.md`](plan/planning-log.md): how the plan was made, product-owner decisions
