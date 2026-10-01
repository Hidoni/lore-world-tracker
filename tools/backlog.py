#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Backlog helper for agents working on Hidoni/lore-world-tracker.

Usage (from the repo root):
    uv run tools/backlog.py ready [--milestone M3] [--limit 10] [--include-post-mvp]
    uv run tools/backlog.py show 42
    uv run tools/backlog.py claim 42 [--force]
    uv run tools/backlog.py unclaim 42
    uv run tools/backlog.py stats

"Ready" = open, not labeled status:in-progress / status:needs-decision / status:blocked,
and every issue listed on the body's "Blocked by:" line is closed. Ordering: milestone
number, then priority label (P0 < P1 < P2), then issue number. Requires the `gh` CLI.
See docs/plan/workflow.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

REPO = os.environ.get("LORE_REPO", "Hidoni/lore-world-tracker")
STATUS_LABELS = {"status:in-progress", "status:needs-decision", "status:blocked"}
BLOCKED_RE = re.compile(r"^Blocked by:\s*(.+)$", re.MULTILINE)
MILESTONE_RE = re.compile(r"^M(\d+)\b")
PRIORITY_ORDER = {"priority:P0": 0, "priority:P1": 1, "priority:P2": 2}


def gh(*args: str) -> str:
    try:
        return subprocess.run(
            ["gh", *args], check=True, capture_output=True, text=True
        ).stdout
    except subprocess.CalledProcessError as exc:  # pragma: no cover - CLI helper
        sys.exit(f"gh {' '.join(args)} failed:\n{exc.stderr}")


def load_issues() -> dict[int, dict]:
    raw = gh(
        "issue", "list", "-R", REPO, "--state", "all", "--limit", "1000",
        "--json", "number,title,state,labels,milestone,body,url",
    )
    issues = {}
    for item in json.loads(raw):
        item["labels"] = {label["name"] for label in item["labels"]}
        item["blockers"] = blockers_from_body(item.get("body") or "")
        issues[item["number"]] = item
    return issues


def blockers_from_body(body: str) -> list[int]:
    match = BLOCKED_RE.search(body)
    if not match:
        return []
    return [int(n) for n in re.findall(r"#(\d+)", match.group(1))]


def milestone_no(issue: dict) -> int:
    title = (issue.get("milestone") or {}).get("title", "")
    match = MILESTONE_RE.match(title)
    return int(match.group(1)) if match else 999


def priority(issue: dict) -> int:
    return min((PRIORITY_ORDER[l] for l in issue["labels"] if l in PRIORITY_ORDER), default=3)


def open_blockers(issue: dict, issues: dict[int, dict]) -> list[int]:
    return [b for b in issue["blockers"] if issues.get(b, {}).get("state") != "CLOSED"]


def is_ready(issue: dict, issues: dict[int, dict]) -> bool:
    return (
        issue["state"] == "OPEN"
        and not (issue["labels"] & STATUS_LABELS)
        and not open_blockers(issue, issues)
    )


def fmt(issue: dict) -> str:
    ms = (issue.get("milestone") or {}).get("title", "-").split(":")[0]
    prio = next((l.split(":")[1] for l in issue["labels"] if l.startswith("priority:")), "-")
    size = next((l.split(":")[1] for l in issue["labels"] if l.startswith("size:")), "-")
    return f"#{issue['number']:<4} {ms:<4} {prio:<3} {size:<3} {issue['title']}"


def cmd_ready(args: argparse.Namespace) -> None:
    issues = load_issues()
    candidates = [
        i for i in issues.values()
        if is_ready(i, issues)
        and (args.include_post_mvp or "post-mvp" not in i["labels"])
        and (not args.milestone or (i.get("milestone") or {}).get("title", "").startswith(args.milestone + ":"))
    ]
    candidates.sort(key=lambda i: (milestone_no(i), priority(i), i["number"]))
    if not candidates:
        print("No ready issues (check claimed/needs-decision issues with `stats`).")
        return
    for issue in candidates[: args.limit]:
        print(fmt(issue))


def cmd_show(args: argparse.Namespace) -> None:
    issues = load_issues()
    issue = issues.get(args.number) or sys.exit(f"#{args.number} not found")
    print(fmt(issue))
    print(f"state: {issue['state']}  labels: {', '.join(sorted(issue['labels']))}")
    print(f"url: {issue['url']}")
    if issue["blockers"]:
        print("blocked by:")
        for b in issue["blockers"]:
            blocker = issues.get(b)
            state = blocker["state"] if blocker else "UNKNOWN"
            title = blocker["title"] if blocker else ""
            print(f"  #{b:<4} {state:<6} {title}")
    print("ready:", "yes" if is_ready(issue, issues) else "no")


def cmd_claim(args: argparse.Namespace) -> None:
    issues = load_issues()
    issue = issues.get(args.number) or sys.exit(f"#{args.number} not found")
    if not args.force and not is_ready(issue, issues):
        sys.exit(f"#{args.number} is not ready (use `show` to see why, or --force).")
    today = dt.date.today().isoformat()
    gh("issue", "edit", str(args.number), "-R", REPO, "--add-label", "status:in-progress")
    gh("issue", "comment", str(args.number), "-R", REPO, "--body",
       f"Claimed by an agent session on {today}. A claim without a linked branch/PR activity "
       f"for 48 hours is stale (see docs/plan/workflow.md §2).")
    print(f"claimed #{args.number}: {issue['title']}")


def cmd_unclaim(args: argparse.Namespace) -> None:
    gh("issue", "edit", str(args.number), "-R", REPO, "--remove-label", "status:in-progress")
    gh("issue", "comment", str(args.number), "-R", REPO, "--body", "Claim released.")
    print(f"unclaimed #{args.number}")


def cmd_stats(_: argparse.Namespace) -> None:
    issues = load_issues()
    by_ms: dict[str, list[dict]] = {}
    for issue in issues.values():
        by_ms.setdefault((issue.get("milestone") or {}).get("title", "(none)"), []).append(issue)
    for title in sorted(by_ms, key=lambda t: int(m.group(1)) if (m := MILESTONE_RE.match(t)) else 999):
        group = by_ms[title]
        closed = sum(i["state"] == "CLOSED" for i in group)
        claimed = [i["number"] for i in group if "status:in-progress" in i["labels"] and i["state"] == "OPEN"]
        decide = [i["number"] for i in group if "status:needs-decision" in i["labels"] and i["state"] == "OPEN"]
        ready = sum(is_ready(i, issues) for i in group)
        extra = ""
        if claimed:
            extra += f"  in-progress: {', '.join(f'#{n}' for n in claimed)}"
        if decide:
            extra += f"  needs-decision: {', '.join(f'#{n}' for n in decide)}"
        print(f"{title:<36} {closed:>3}/{len(group):<3} closed  {ready:>3} ready{extra}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ready", help="list issues ready to work on")
    p.add_argument("--milestone", help='milestone prefix, e.g. "M3"')
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--include-post-mvp", action="store_true")
    p.set_defaults(func=cmd_ready)
    p = sub.add_parser("show", help="show an issue and its blockers")
    p.add_argument("number", type=int)
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("claim", help="claim an issue (adds status:in-progress)")
    p.add_argument("number", type=int)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_claim)
    p = sub.add_parser("unclaim", help="release a claim")
    p.add_argument("number", type=int)
    p.set_defaults(func=cmd_unclaim)
    p = sub.add_parser("stats", help="progress per milestone")
    p.set_defaults(func=cmd_stats)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
