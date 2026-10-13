"""API schemas of the lexicon (``docs/modules/languages.md``, Tables and API)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from lore.chronology.schema import TimePoint
from lore.core.consistency.schemas import SuppressItem
from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId
from lore.core.types import Affected, MomentStr

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Headword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

PARTS_OF_SPEECH = (
    "noun",
    "verb",
    "adjective",
    "adverb",
    "pronoun",
    "preposition",
    "conjunction",
    "interjection",
    "particle",
    "numeral",
    "affix",
    "phrase",
    "other",
)


class Example(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(max_length=2000)]
    translation: Annotated[str, StringConstraints(max_length=2000)] | None = None


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gloss: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    notes: Annotated[str, StringConstraints(max_length=5000)] | None = None
    examples: list[Example] = Field(default_factory=list, max_length=50)


class EtymologySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: EntityId | None = None
    language_id: EntityId | None = None
    form: Text | None = None


class Etymology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(max_length=5000)] | None = None
    sources: list[EtymologySource] = Field(default_factory=list, max_length=20)


class _EntryMembers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    romanization: Text | None = None
    pronunciation: Text | None = Field(default=None, description="IPA.")
    part_of_speech: Text | None = Field(
        default=None, description=f"Free text; suggested: {', '.join(PARTS_OF_SPEECH)}."
    )
    definitions: list[Definition] = Field(default_factory=list, max_length=100)
    etymology: Etymology = Field(default_factory=Etymology)
    notes: dict[str, Any] | None = Field(default=None, description="A rich-text document.")
    tags: list[Tag] = Field(default_factory=list, max_length=50)
    visibility: Visibility = "public"
    timeline_id: EntityId | None = Field(
        default=None, description="Required with an attestation bound: where it is dated."
    )
    valid_from: TimePoint | None = Field(default=None, description="First attested.")
    valid_to: TimePoint | None = Field(default=None, description="Last attested.")
    sort_key: Annotated[str, StringConstraints(max_length=100)] | None = None


class LexiconEntryCreate(_EntryMembers):
    headword: Headword
    suppress: list[SuppressItem] | None = None


class LexiconEntryUpdate(BaseModel):
    """Only the members sent change (``null`` clears a nullable one)."""

    model_config = ConfigDict(extra="forbid")

    revision: int
    headword: Headword | None = None
    romanization: Text | None = None
    pronunciation: Text | None = None
    part_of_speech: Text | None = None
    definitions: list[Definition] | None = Field(default=None, max_length=100)
    etymology: Etymology | None = None
    notes: dict[str, Any] | None = None
    tags: list[Tag] | None = Field(default=None, max_length=50)
    visibility: Visibility | None = None
    timeline_id: EntityId | None = None
    valid_from: TimePoint | None = None
    valid_to: TimePoint | None = None
    sort_key: Annotated[str, StringConstraints(max_length=100)] | None = None
    suppress: list[SuppressItem] | None = None


class LexiconEntryOut(BaseModel):
    id: str
    language_id: str
    headword: str
    romanization: str | None
    pronunciation: str | None
    part_of_speech: str | None
    definitions: list[Definition]
    etymology: Etymology
    notes: dict[str, Any] | None
    tags: list[str]
    collation_key: str
    visibility: Visibility
    timeline_id: str | None
    valid_from: TimePoint | None
    valid_to: TimePoint | None
    valid_from_t: MomentStr | None
    valid_to_t: MomentStr | None
    time_status: str | None
    sort_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class LexiconPage(BaseModel):
    items: list[LexiconEntryOut]
    next_cursor: str | None


class LexiconWriteResult(BaseModel):
    entry: LexiconEntryOut
    affected: Affected


type LexiconSort = Literal["collation", "headword", "recent"]


class ImportIn(BaseModel):
    """A CSV document (UTF-8 text with a header row) and how its columns map to fields."""

    model_config = ConfigDict(extra="forbid")

    csv: Annotated[str, StringConstraints(max_length=10_000_000)]
    columns: dict[str, str] | None = Field(
        default=None,
        description="Header → field (`headword`, `romanization`, `pronunciation`, "
        "`part_of_speech`, `definitions`, `tags`, `etymology`, `notes`, or `` to skip). "
        "Default: headers that name a field.",
    )


class ImportProblem(BaseModel):
    row: int = Field(description="1-based data row (the header is row 0).")
    column: str | None
    message: str


class ImportReport(BaseModel):
    rows: int
    created: int = Field(description="Entries created (0 for a dry run or a refused import).")
    columns: dict[str, str] = Field(description="The mapping used: header → field.")
    errors: list[ImportProblem]
    affected: Affected | None = None
