"""tools/backlog.py talks to GitHub through REST only (cloud sessions block GraphQL)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

BACKLOG = Path(__file__).resolve().parents[2] / "tools" / "backlog.py"


@pytest.fixture
def backlog() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backlog", BACKLOG)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rest_issue(number: int, **extra: Any) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "labels": [],
        "milestone": {"title": "M13: Post-MVP backlog"},
        "body": "",
        "html_url": f"https://github.com/Hidoni/lore-world-tracker/issues/{number}",
        **extra,
    }


def fake_gh(
    monkeypatch: pytest.MonkeyPatch, backlog: ModuleType, pages: list[list[dict[str, Any]]]
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def gh(*args: str) -> str:
        calls.append(args)
        if args[1].startswith(f"repos/{backlog.REPO}/issues?"):
            page = int(args[1].rsplit("page=", 1)[1])
            return json.dumps(pages[page - 1] if page <= len(pages) else [])
        return "{}"

    monkeypatch.setattr(backlog, "gh", gh)
    return calls


def test_load_issues_pages_by_number_and_skips_pull_requests(
    monkeypatch: pytest.MonkeyPatch, backlog: ModuleType
) -> None:
    monkeypatch.setattr(backlog, "PAGE_SIZE", 2)
    pages = [
        [rest_issue(1), rest_issue(2, pull_request={"url": "…"})],
        [rest_issue(3, state="closed", labels=[{"name": "priority:P1"}]), rest_issue(4)],
        [rest_issue(5, body="Blocked by: #3, #4")],
    ]
    calls = fake_gh(monkeypatch, backlog, pages)

    issues = backlog.load_issues()

    assert sorted(issues) == [1, 3, 4, 5]
    assert issues[3]["state"] == "CLOSED"
    assert issues[3]["labels"] == {"priority:P1"}
    assert issues[5]["blockers"] == [3, 4]
    assert issues[1]["url"].endswith("/issues/1")
    assert [args[0] for args in calls] == ["api"] * 3
    assert not backlog.is_ready(issues[5], issues)
    assert backlog.is_ready(issues[4], issues)


def test_claim_and_unclaim_use_rest_endpoints(
    monkeypatch: pytest.MonkeyPatch, backlog: ModuleType
) -> None:
    calls = fake_gh(monkeypatch, backlog, [[rest_issue(7)]])
    repo = f"repos/{backlog.REPO}"

    backlog.cmd_claim(backlog.argparse.Namespace(number=7, force=False))
    backlog.cmd_unclaim(backlog.argparse.Namespace(number=7))

    writes = [args for args in calls if "-X" in args]
    assert [(args[1], args[3]) for args in writes] == [
        (f"{repo}/issues/7/labels", "POST"),
        (f"{repo}/issues/7/comments", "POST"),
        (f"{repo}/issues/7/labels/status:in-progress", "DELETE"),
        (f"{repo}/issues/7/comments", "POST"),
    ]
    assert all(args[0] == "api" for args in calls)
