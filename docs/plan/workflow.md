# Agent workflow

How an implementing agent (or human) takes an issue from the backlog to merged code. Decision
background: ADR-0014. Repository: **`Hidoni/lore-world-tracker` only**. Never create other
repositories or GitHub Projects boards.

## 1. Find a ready issue

An issue is **ready** when it is open, not labeled `status:in-progress`, `status:needs-decision`
or `status:blocked`, and every issue it is blocked by is closed.

```bash
# helper (lists ready issues in milestone order, then priority)
uv run tools/backlog.py ready
uv run tools/backlog.py ready --milestone "M1"          # narrow down
uv run tools/backlog.py show 42                         # issue + blocker status
```

Without the helper: `gh issue list -R Hidoni/lore-world-tracker --milestone "<title>" --state open`
and check the "Blocked by" list in each body.

Preference order: lowest milestone first (M0 → M13), then `priority:P0` → `P1` → `P2`, then
lowest issue number. Work on M13 (post-MVP) only when the product owner asks.

## 2. Claim it

```bash
uv run tools/backlog.py claim 42      # adds status:in-progress + a claim comment with the date
```

All agents act as the same GitHub user, so the label is the lock. A claim with no linked PR or
branch activity for 48 hours is stale. Another agent may comment and take it over.

## 3. Prepare

1. `git switch main && git pull --ff-only`
2. Read `CLAUDE.md`, the issue, **every spec section it links**, and the ADRs it names. For any
   time-related work, read `docs/architecture/time-model.md` in full.
3. Check for related open PRs (`gh pr list`) to avoid overlapping changes.
4. If the spec is unclear:
   - **Technical gap:** decide, document the decision in the spec in your PR, and mention it in
     the PR body.
   - **Product question** (changes user-visible behavior or contradicts D1–D16): comment on the
     issue with options and a recommendation, add `status:needs-decision`, remove your claim, and
     pick another issue. Don't guess on product decisions.

## 4. Branch and implement

- Branch name: `<issue number>-<short-slug>` (e.g. `42-calendar-compile`).
- Stay within the issue's scope. Unrelated improvements become new issues (§8).
- Write tests with the code (`docs/architecture/testing.md`). Chronology bugs get conformance
  vectors.
- Commit in logical steps with Conventional Commits:
  `<type>(<scope>): <summary>` where type ∈ `feat, fix, refactor, test, docs, chore, ci, build,
  perf`. Scope is one of `chronology, core, time, api, db, ui, timeline, editor, search,
  history, visibility, consistency, docker, ci, docs`, or `mod-<module id>`.
- Keep `CLAUDE.md` and the docs truthful. If you change a command, convention or spec, update it
  in the same PR.

## 5. Verify locally

```bash
make check          # lint, format check, types, import contracts, unit/API tests, conformance, drift checks
make e2e            # when the issue touches UI flows covered by e2e journeys
```

Never disable, skip or weaken tests to get green. If a test is wrong, fix it and explain why in
the PR.

## 6. Open the PR

```bash
git push -u origin HEAD
gh pr create --title "feat(chronology): compile calendar definitions (#42)" --body-file <file>
```

The body follows `.github/pull_request_template.md`: `Closes #42`, a summary, the acceptance
criteria checklist copied from the issue (ticked), spec/ADR changes, test evidence, and
follow-ups.

If `git push` fails with "could not read Username for 'https://github.com'", git has no
credential helper. Run `gh auth setup-git` once, or push with
`git -c credential.helper='!gh auth git-credential' push -u origin HEAD`.

## 7. CI, merge, clean up

```bash
gh pr checks --watch                       # wait for CI; fix failures and push again
gh pr merge --squash --delete-branch       # only when every required check is green
git switch main && git pull --ff-only
```

The squash commit title is the PR title. The issue closes automatically via `Closes #N`. Confirm
it closed.

## 8. Follow-ups and backlog hygiene

- New work discovered → `gh issue create` using `.github/ISSUE_TEMPLATE/task.md`, with
  milestone, labels (`type:*`, `area:*`/`module:*`, `priority:*`, `size:*`) and a "Blocked by"
  line. Add the issue to `docs/plan/roadmap.md` in your PR (or in a small docs PR).
- Bugs found in merged work → `.github/ISSUE_TEMPLATE/bug.md`, label `type:bug`, the milestone
  currently in progress, `priority` by impact.
- If an issue turns out too big, split it: create the parts, link them, update the roadmap, and
  close the original as "split into #…".

## 9. Parallel-work conflicts

- **Rebase** on `main` (`git pull --rebase origin main`). Don't merge main into feature
  branches.
- **Alembic:** if `main` gained a migration, re-point your migration's `down_revision` to the
  new head and re-run `make check` (single-head check).
- **Generated files** (`schema.gen.ts`, chronology JSON Schemas/types): never hand-merge.
  Run `make gen` after rebasing and commit the result.
- **Conformance vectors:** keep both sides' vectors. If they contradict, the spec decides. If the
  spec is silent, raise it on the issue.

## 10. Definition of done

- [ ] Acceptance criteria in the issue are met.
- [ ] Tests added/updated, coverage targets kept (`testing.md` §1). Chronology changes include
      conformance vectors and both engines.
- [ ] `make check` passes locally. CI is green.
- [ ] Schema changes come with Alembic migrations (single head, `lore db check` clean). JSON
      document changes come with versioned upgraders.
- [ ] New read endpoints have leak-test recipes. Reader-facing endpoints are listed in
      `visibility-and-sharing.md` §6.
- [ ] Docs updated: specs, module docs, API catalog, glossary terms, CLAUDE.md if commands or
      conventions changed.
- [ ] No `TODO`/`FIXME` without an issue reference.
- [ ] PR title follows Conventional Commits and the body uses the template.

## 11. Milestone completion

When the last issue of a milestone closes, the next agent opens a **release PR**: version bump
(backend + npm workspaces), `CHANGELOG.md` entry, a new golden fixture vault
(`persistence-and-migrations.md` §3.5), and the roadmap status updated. After merge:
`git tag vX.Y.0 && git push --tags`, then close the milestone (`gh api -X PATCH
repos/Hidoni/lore-world-tracker/milestones/<n> -f state=closed`).
