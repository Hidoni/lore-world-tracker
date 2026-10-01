# ADR-0005: Static module registry, per-vault toggles, single migration history

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

The brief requires non-core features to be designed as toggleable modules that may be expanded
or removed. Modules need DB tables, API routes, UI, link types, consistency rules, etc.

## Decision

- Modules are first-party code registered **statically** (`ALL_MODULES` in Python,
  `modules/index.ts` in TS) through a `ModuleSpec`/`defineModule` contract with explicit
  extension points (`modules.md`).
- Enablement is **per vault** (settings). Disabling hides everything and never deletes data.
- Boundaries are enforced by import-linter/eslint: core never imports modules, and modules import
  only declared dependencies' public APIs.
- **One linear Alembic history** for core and modules. Module tables exist in every vault
  regardless of enablement, are prefixed with the module id, and have migrations labeled with the
  owner.
- Removing a module is a two-release process with a conversion migration (`modules.md` §7).

## Consequences

- Toggling is cheap and safe. Upgrading never depends on which modules a vault uses.
- No runtime plugin loading (no third-party plugins). This is acceptable for the product's scope.
- Unused module tables are present but empty (negligible).

## Alternatives considered

- Python entry points / dynamic plugins: more flexible, but adds discovery and versioning
  complexity with no current need.
- Per-module Alembic branches: multiple heads and ordering problems across vaults. Rejected.
- Dropping tables when disabled: violates "never lose data".
