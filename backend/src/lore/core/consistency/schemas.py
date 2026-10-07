"""API models of consistency (``docs/architecture/api.md`` §2, consistency)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy.orm import Session

Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Note = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
RuleId = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$", max_length=200)
]


class SuppressItem(BaseModel):
    """Findings the write declares intentional ("save anyway", ``consistency.md`` §3): one
    finding by ``fingerprint``, or by ``rule_id`` every new blocking finding of that rule the
    write produces (a create's findings name an id that is new on every attempt; decided with
    #55). Give exactly one of them."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: Fingerprint | None = None
    rule_id: RuleId | None = None
    note: Note

    @model_validator(mode="after")
    def _one(self) -> SuppressItem:
        if (self.fingerprint is None) == (self.rule_id is None):
            raise ValueError("give exactly one of fingerprint and rule_id")
        return self


SUPPRESS_DESCRIPTION = (
    "Findings this write declares intentional (from a `422 consistency_error`): they are "
    "suppressed in the same changeset. Hard rules can't be suppressed."
)


class SuppressIn(BaseModel):
    """The optional body of writes that have none otherwise (trash, restore, undo, …)."""

    model_config = ConfigDict(extra="forbid")

    suppress: list[SuppressItem] = Field(
        default_factory=list, max_length=500, description=SUPPRESS_DESCRIPTION
    )


def request_suppress(session: Session, items: Sequence[SuppressItem] | None) -> None:
    """Hand a write's ``suppress`` member to the consistency engine."""
    from lore.core.consistency.engine import request_suppress as hand  # noqa: PLC0415

    if items:
        hand(session, ((item.fingerprint, item.rule_id, item.note) for item in items))


# --- findings and rules ---------------------------------------------------------------------------

type ShownSeverity = Literal["error", "warning", "info"]


class FindingSubject(BaseModel):
    id: str
    name: str | None = Field(description="Null when the entity no longer exists.")
    kind: str | None


class SuppressionOut(BaseModel):
    note: str
    created_at: datetime


class FindingOut(BaseModel):
    fingerprint: str
    rule_id: str
    owner: str
    title: str
    severity: ShownSeverity = Field(
        description="The rule's severity; `info` for possible (uncertain) findings."
    )
    certainty: Literal["definite", "possible"]
    message: str
    subjects: list[FindingSubject]
    timeline_id: str | None
    data: dict[str, Any]
    suppression: SuppressionOut | None
    created_at: datetime
    updated_at: datetime


class FindingPage(BaseModel):
    items: list[FindingOut] = Field(description="By severity (error, warning, info), newest first.")
    next_cursor: str | None


class RuleInfo(BaseModel):
    id: str
    owner: str
    title: str
    description: str
    category: str
    default_severity: Literal["off", "warning", "error"]
    severity: Literal["off", "warning", "error"] = Field(description="This vault's severity.")
    configurable: bool = Field(description="False: a hard rule (always `error`).")
    findings: int = Field(description="Open findings (not suppressed).")


class RuleList(BaseModel):
    items: list[RuleInfo]


class RuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["off", "warning", "error"] | None = Field(
        description="The vault's severity; null goes back to the rule's default."
    )


class SuppressionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: Fingerprint
    note: Note


class ScanResult(BaseModel):
    rules: int = Field(description="Rules evaluated.")
    findings: int = Field(description="Open findings after the scan (suppressed included).")
