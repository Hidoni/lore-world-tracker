"""``VisibilityPolicy`` details the canary suite doesn't reach: module row filters, their
registry validation, field visibility overrides and the policy dependency."""

from pathlib import Path

import pytest
from sqlalchemy import ColumnElement, ForeignKey, String, select
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleRegistry, ModuleSpec, RegistryError
from lore.core.visibility import AUTHOR, READER, VisibilityFilter
from tests.entity_api import Api
from tests.visibility.canary import leak_client


class PinBase(DeclarativeBase):
    pass


class PinsPin(PinBase):
    __tablename__ = "pins_pins"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    map_id: Mapped[str] = mapped_column(ForeignKey("entities.id"))
    target_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    visibility: Mapped[str] = mapped_column(String)


PIN_FILTER = VisibilityFilter(PinsPin, entity_columns=("map_id", "target_id"))


def _sql(policy_conditions: list[ColumnElement[bool]]) -> str:
    statement = select(PinsPin.id).where(*policy_conditions)
    return str(statement.compile(dialect=sqlite.dialect()))


def test_module_rows_filter_for_readers_only() -> None:
    assert AUTHOR.module_rows(PIN_FILTER) == []
    sql = _sql(READER.module_rows(PIN_FILTER))
    assert "pins_pins.visibility !=" in sql
    assert "pins_pins.map_id IS NULL OR (EXISTS" in sql
    assert "pins_pins.target_id IS NULL OR (EXISTS" in sql
    no_column = VisibilityFilter(PinsPin, visibility_column=None, entity_columns=("map_id",))
    assert "visibility !=" not in _sql(READER.module_rows(no_column)).split("EXISTS")[0]


def _module(*filters: object, models: tuple[type, ...] = (PinsPin,)) -> ModuleSpec:
    return ModuleSpec(
        id="pins",
        name="Pins",
        description="Pins.",
        models=models,
        history_tables=tuple(HistoryTable.of(model) for model in models),
        visibility_filters=filters,  # type: ignore[arg-type]
    )


def test_the_registry_accepts_valid_filters() -> None:
    ModuleRegistry([_module(PIN_FILTER)])


@pytest.mark.parametrize(
    ("filters", "problem"),
    [
        ((object(),), "pins: visibility filters must be VisibilityFilter"),
        (
            (VisibilityFilter(PinBase),),
            "pins: visibility filter of PinBase: the model isn't one of the module's models",
        ),
        (
            (PIN_FILTER, PIN_FILTER),
            "pins: visibility filter of PinsPin: the model already has a filter",
        ),
        (
            (VisibilityFilter(PinsPin, entity_columns=("owner_id",)),),
            "pins: visibility filter of PinsPin: no column 'owner_id'",
        ),
        (
            (VisibilityFilter(PinsPin, visibility_column="level"),),
            "pins: visibility filter of PinsPin: no column 'level'",
        ),
    ],
)
def test_the_registry_refuses_invalid_filters(filters: tuple[object, ...], problem: str) -> None:
    with pytest.raises(RegistryError) as caught:
        ModuleRegistry([_module(*filters)])
    assert caught.value.problems == [problem]


def test_field_overrides_decide_reader_visibility(tmp_path: Path) -> None:
    with leak_client(tmp_path) as client:
        api = Api(client)
        gadget = api.make(
            "gadget",
            "Box",
            fields={"secret": "shown", "text": "hidden", "nicknames": ["Crate"]},
            field_visibility={"secret": "spoiler", "text": "private"},
        )
        as_reader = {"as_reader": "true"}
        reader = client.get(f"{api.base}/entities/{gadget['id']}", params=as_reader).json()
        assert reader["fields"] == {"secret": "shown", "nicknames": ["Crate"]}
        assert reader["field_visibility"] == {"secret": "spoiler"}
        listed = client.get(f"{api.base}/entities", params=as_reader).json()["items"]
        assert listed[0]["fields"] == reader["fields"]
        values = f"{api.base}/entities/field-values"
        for field, expected in (("secret", ["shown"]), ("text", []), ("nicknames", ["Crate"])):
            params = {"kind": "gadget", "field": field, **as_reader}
            items = client.get(values, params=params).json()["items"]
            assert [item["value"] for item in items] == expected

        author = client.get(f"{api.base}/entities/{gadget['id']}").json()
        assert author["fields"]["text"] == "hidden"


def test_as_reader_hides_history_and_the_trash(tmp_path: Path) -> None:
    with leak_client(tmp_path) as client:
        api = Api(client)
        api.make("misc", "Thing")
        for path in ("changes", "trash"):
            assert client.get(f"{api.base}/{path}").status_code == 200
            response = client.get(f"{api.base}/{path}", params={"as_reader": "true"})
            assert response.status_code == 404
