# ADR-0001: Monorepo layout and tooling

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

The product has a Python backend (managed with `uv`, per the brief), a TypeScript frontend
(`node`/`npm`, per the brief), and a time engine that must behave identically in both languages.
Many agents will work on it over a long period and need one predictable layout and one way to
run checks.

## Decision

- One repository with `backend/` (uv project, package `lore`), `frontend/` (`@lore/web`),
  `packages/chronology/` (`@lore/chronology`), `spec/` (shared language-agnostic assets: JSON
  Schemas, presets, conformance vectors) and `docs/`.
- npm **workspaces** at the root (`frontend`, `packages/*`). The root `package.json` only holds
  workspace config and scripts.
- A root **Makefile** is the single entry point for humans and agents (`make setup`, `dev`,
  `check`, `test`, `gen`, `e2e`, `docker`).
- Python 3.14 (`.python-version`), Node major pinned in `.nvmrc`, lockfiles committed.
- Quality tools: ruff, mypy `--strict`, import-linter, pytest/hypothesis; ESLint (flat config,
  typescript-eslint, boundaries), Prettier, Vitest, Playwright.

## Consequences

- Cross-cutting changes (API + client, engine in both languages) land atomically in one PR.
- CI must be path-aware to stay fast.
- Agents must use `make` targets rather than inventing commands. CLAUDE.md documents them.

## Alternatives considered

- Separate repos: rejected by the brief (one GitHub project) and it makes atomic contract changes
  hard.
- Turborepo/Nx/pnpm: unnecessary for two npm packages. The brief says npm.
- `just`/`task` runners: Make is preinstalled nearly everywhere.
