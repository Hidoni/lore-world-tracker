---
name: next-issue
description: Pick up the next ready issue (or a given issue number) from the Lore World Tracker GitHub backlog and take it through the full project workflow — claim, branch, implement with tests, make check, PR, green CI, squash-merge. Use when asked to "work on the next issue/task", "continue the implementation", or "implement #N".
---

# Implement a backlog issue end-to-end

The authoritative procedure is `docs/plan/workflow.md`. Read it and `CLAUDE.md` first. Then:

1. **Choose.** If the user named an issue, use it. Otherwise run `uv run tools/backlog.py ready`
   and take the first entry (lowest milestone, then priority). Never pick `post-mvp` issues
   unless the user asks.
2. **Understand.** Run `uv run tools/backlog.py show <n>` (confirm `ready: yes`) and
   `gh issue view <n> -R Hidoni/lore-world-tracker`. Read **every** spec section and ADR the
   issue links. For time-related work, read `docs/architecture/time-model.md` in full.
3. **Claim.** `uv run tools/backlog.py claim <n>`.
4. **Branch.** `git switch main && git pull --ff-only && git switch -c <n>-<short-slug>`.
5. **Implement** exactly the issue's scope, with tests (chronology changes need conformance
   vectors and both engines). Update docs in the same branch when behavior or conventions change.
6. **Verify.** `make check`, plus `make e2e` when UI flows are touched. Fix failures, and never
   weaken tests.
7. **PR.** Push and `gh pr create` using `.github/pull_request_template.md` (body starts with
   `Closes #<n>`, ticks the acceptance criteria).
8. **CI.** `gh pr checks --watch`. Fix until green, then `gh pr merge --squash --delete-branch`,
   then `git switch main && git pull --ff-only`.
9. **Wrap up.** Confirm the issue closed. File follow-up issues (template
   `.github/ISSUE_TEMPLATE/task.md`, with milestone, labels and a "Blocked by" line) for anything
   discovered. Report to the user what was done, with the PR link.

Stop and ask instead of guessing when a product decision is involved (anything contradicting
D1–D16 in `docs/plan/planning-log.md` or changing user-visible behavior beyond the spec). In that
case, label the issue `status:needs-decision`, comment with the options and a recommendation, and
release the claim (`uv run tools/backlog.py unclaim <n>`).

Only ever use the GitHub repository `Hidoni/lore-world-tracker`. Never create other repositories
or GitHub Projects boards.
