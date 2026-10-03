from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lore.core.entities.extensions import KindExtension
from lore.core.entities.service import slugify
from lore.core.fields import CORE_VALIDATORS
from lore.core.links.models import Link
from lore.core.modules import ModuleRegistry, ModuleSpec, RegistryError
from lore.core.registry import CORE_FIELD_TYPES, FieldContribution, FieldDef
from lore.core.vaults import VaultManager
from tests import entity_modules
from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, invalid, make_client, new_app, problem
from tests.entity_modules import ENTITY_MODULES, EXTRA, WORLD

ABSENT = object()


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return new_app(tmp_path)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with local_client(app, headers=HEADERS) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)


# --- create and read ------------------------------------------------------------------------


def test_create_and_get(api: Api) -> None:
    dimension = api.make("dimension", "Aetheria")
    response = api.create(
        "gadget",
        "  Élan Vital Engine ",
        dimension_id=dimension["id"],
        summary="A machine.",
        body={"type": "doc", "content": []},
        fields={"text": "brass", "color": "#AABBCC"},
        field_visibility={"text": "spoiler"},
        icon="cog",
        color="#00FF00",
        sort_key="a0",
        aliases=[
            {"alias": "The Engine"},
            {"alias": "Vital", "alias_kind": "nickname", "visibility": "private"},
        ],
        tags=["Steam", "steam", "Machines"],
    )
    assert response.status_code == 201
    created = response.json()
    entity = created["entity"]
    assert created["affected"] == {
        "entities": [entity["id"]],
        "dimensions": [dimension["id"]],
        "time_changed": False,
        "search_changed": True,
    }
    assert entity["name"] == "Élan Vital Engine"
    assert entity["slug"] == "elan-vital-engine"
    assert entity["fields"] == {"text": "brass", "color": "#aabbcc"}
    assert entity["field_visibility"] == {"text": "spoiler"}
    assert (entity["color"], entity["icon"], entity["sort_key"]) == ("#00ff00", "cog", "a0")
    assert entity["body_schema_version"] == 1
    assert entity["visibility"] == "public"
    assert entity["revision"] == 1
    assert entity["deleted_at"] is None
    assert entity["ext"] is None
    assert [(a["alias"], a["alias_kind"], a["visibility"]) for a in entity["aliases"]] == [
        ("The Engine", "alias", "public"),
        ("Vital", "nickname", "private"),
    ]
    assert [tag["name"] for tag in entity["tags"]] == ["Machines", "Steam"]
    assert api.get(entity["id"]).json() == entity


def test_default_visibility_comes_from_the_vault(api: Api, app: FastAPI) -> None:
    from lore.core.vaults.meta import get_meta, set_meta  # noqa: PLC0415

    manager: VaultManager = app.state.vaults
    with manager.open(api.vault).write_sessions() as session, session.begin():
        settings = get_meta(session, "settings")
        set_meta(session, "settings", {**settings, "defaults": {"visibility": "spoiler"}})
    assert api.make("misc")["visibility"] == "spoiler"
    assert api.make("misc", visibility="private")["visibility"] == "private"


def test_create_errors(api: Api) -> None:
    assert invalid(api.create("ghost")) == ["kind"]
    problem(api.create("misc", "   "), 422, "validation_error")
    problem(api.create("misc", extra=1), 422, "validation_error")
    problem(api.create("misc", color="red"), 422, "validation_error")
    problem(
        api.create("misc", aliases=[{"alias": "x", "alias_kind": "pun"}]), 422, "validation_error"
    )
    dimension = api.make("dimension")
    no_body = api.create(
        "relic", dimension_id=dimension["id"], fields={"origin": "x"}, body={"type": "doc"}
    )
    assert invalid(no_body) == ["body"]
    response = api.create("misc", ext={"x": 1})
    assert invalid(response) == ["ext"]


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Élan Vital", "elan-vital"),
        ("  The -- Great_War!  ", "the-great-war"),
        ("東京 タワー", "東京-タワー"),
        ("한국어", "한국어"),
        ("???", "entity"),
        ("x" * 100, "x" * 80),
    ],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


# --- fields ---------------------------------------------------------------------------------

TIME_POINT = {"anchor": {"kind": "absolute", "t": "42"}, "precision": "base"}
DURATION = {"kind": "base", "units": "-5"}

VALID: list[tuple[str, Any, Any]] = [
    ("text", "Brass", ABSENT),
    ("text", "", ABSENT),
    ("long_text", "line 1\nline 2", ABSENT),
    ("rich_text", {"type": "doc", "content": []}, ABSENT),
    ("integer", "-" + "9" * 40, ABSENT),
    ("integer", 12, "12"),
    ("integer", "0", ABSENT),
    ("decimal", "1.50", ABSENT),
    ("decimal", "-0.5", ABSENT),
    ("decimal", 3, "3"),
    ("boolean", False, ABSENT),
    ("enum", "red", ABSENT),
    ("multi_enum", ["blue", "red"], ABSENT),
    ("multi_enum", [], ABSENT),
    ("url", "https://example.com/a?b=c", ABSENT),
    ("url", "HTTP://example.com", ABSENT),
    ("color", "#A1B2C3", "#a1b2c3"),
    ("duration", DURATION, ABSENT),
    (
        "duration",
        {"kind": "calendar", "calendar_id": "c1", "amounts": {"year": "2"}, "sign": -1},
        ABSENT,
    ),
    ("time_point", TIME_POINT, {**TIME_POINT, "approximate": False}),
    ("measurement", {"value": "1.75", "unit": " m "}, {"value": "1.75", "unit": "m"}),
    ("nicknames", ["Bob", "Bobby"], ABSENT),
    ("nicknames", [], ABSENT),
]

INVALID: list[tuple[str, Any]] = [
    ("text", "two\nlines"),
    ("text", 5),
    ("long_text", ["x"]),
    ("rich_text", "plain"),
    ("integer", "007"),
    ("integer", "-0"),
    ("integer", 1.5),
    ("integer", True),
    ("integer", "1" * 1001),
    ("decimal", 1.5),
    ("decimal", "1."),
    ("decimal", ".5"),
    ("decimal", "-0.0"),
    ("decimal", "1e5"),
    ("boolean", "true"),
    ("boolean", 1),
    ("enum", "green"),
    ("enum", ["red"]),
    ("multi_enum", "red"),
    ("multi_enum", ["red", "red"]),
    ("multi_enum", ["green"]),
    ("url", "javascript:alert(1)"),
    ("url", "ftp://example.com"),
    ("url", "https://"),
    ("url", "https://exa mple.com"),
    ("color", "#abc"),
    ("color", "blue"),
    ("duration", {"kind": "base", "units": "1.5"}),
    ("duration", {"kind": "weeks"}),
    ("time_point", {"anchor": {"kind": "absolute", "t": "-1"}, "precision": "base"}),
    ("time_point", {**TIME_POINT, "range": {}}),
    ("measurement", {"value": "1.75"}),
    ("measurement", {"value": 1.75, "unit": "m"}),
    ("measurement", {"value": "1", "unit": " "}),
    ("measurement", {"value": "1", "unit": "m", "x": 1}),
    ("nicknames", "Bob"),
    ("nicknames", ["Bob", 1]),
]


@pytest.mark.parametrize(("key", "value", "stored"), VALID)
def test_valid_field_values(api: Api, key: str, value: Any, stored: Any) -> None:
    entity = api.make("gadget", fields={key: value})
    assert entity["fields"] == {key: value if stored is ABSENT else stored}


@pytest.mark.parametrize(("key", "value"), INVALID)
def test_invalid_field_values(api: Api, key: str, value: Any) -> None:
    response = api.create("gadget", fields={key: value})
    body = problem(response, 422, "validation_error")
    assert body["errors"][0]["path"] == f"fields.{key}"
    assert body["errors"][0]["code"] == "invalid_value"


def test_every_core_field_type_has_a_validator() -> None:
    assert set(CORE_VALIDATORS) == {field_type.key for field_type in CORE_FIELD_TYPES}
    assert {field.type for field in entity_modules.EVERY_TYPE} == set(CORE_VALIDATORS)


def test_module_field_types_use_their_validator(api: Api) -> None:
    assert api.make("gadget", fields={"extra.stars": 4})["fields"] == {"extra.stars": 4}
    response = api.create("gadget", fields={"extra.stars": 9})
    assert problem(response, 422, "validation_error")["errors"][0]["message"] == (
        "must be 1 to 5 stars"
    )


def test_field_merging_and_unknown_keys(api: Api) -> None:
    entity = api.make("gadget", fields={"text": "a", "boolean": True})
    response = api.patch(entity, fields={"text": "b", "boolean": None, "enum": "red"})
    assert response.json()["entity"]["fields"] == {"text": "b", "enum": "red"}
    unknown = api.patch(response.json()["entity"], fields={"nope": 1, "relic.origin": "x"})
    body = problem(unknown, 422, "validation_error")
    assert [(e["path"], e["code"]) for e in body["errors"]] == [
        ("fields.nope", "unknown_field"),
        ("fields.relic.origin", "unknown_field"),
    ]


def test_field_visibility(api: Api) -> None:
    entity = api.make("gadget", field_visibility={"secret": "public", "text": "private"})
    assert entity["field_visibility"] == {"secret": "public", "text": "private"}
    entity = api.patch(entity, field_visibility={"secret": None}).json()["entity"]
    assert entity["field_visibility"] == {"text": "private"}
    bad = api.patch(entity, field_visibility={"nope": "public"})
    assert invalid(bad) == ["field_visibility.nope"]
    problem(api.patch(entity, field_visibility={"text": "hidden"}), 422, "validation_error")


def test_required_fields_are_checked_on_every_save(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        api = Api(client)
        dimension = api.make("dimension")
        missing = api.create("relic", dimension_id=dimension["id"])
        assert problem(missing, 422, "validation_error")["errors"] == [
            {"path": "fields.origin", "code": "required", "message": "Origin is required"}
        ]
        empty = api.create("relic", dimension_id=dimension["id"], fields={"origin": ""})
        assert invalid(empty) == ["fields.origin"]
        relic = api.make("relic", dimension_id=dimension["id"], fields={"origin": "Old"})
        cleared = api.patch(relic, fields={"origin": None})
        assert invalid(cleared) == ["fields.origin"]
        gadget = api.make("gadget", dimension_id=dimension["id"])
    # a later release makes a gadget field required: existing gadgets must fill it on next save
    kinds = tuple(
        replace(k, fields=(*k.fields, FieldDef("serial", "Serial", "text", required=True)))
        if k.key == "gadget"
        else k
        for k in WORLD.kinds
    )
    with make_client(tmp_path, (replace(WORLD, kinds=kinds), EXTRA)) as client:
        api = Api(client, api.vault)
        assert api.get(gadget["id"]).status_code == 200
        rename = api.patch(gadget, name="Renamed")
        assert invalid(rename) == ["fields.serial"]
        assert api.patch(gadget, name="Renamed", fields={"serial": "S-1"}).status_code == 200


def test_archived_and_disabled_fields_are_preserved(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        api = Api(client)
        gadget = api.make(
            "gadget",
            fields={"text": "a", "extra.wings": True},
            field_visibility={"extra.wings": "spoiler"},
        )
        assert api.modules("extra", enabled=False).status_code == 200
        hidden = api.get(gadget["id"]).json()
        assert hidden["fields"] == {"text": "a"}
        assert hidden["field_visibility"] == {}
        refused = api.patch(hidden, fields={"extra.wings": False})
        problem(refused, 422, "validation_error")
        hidden = api.patch(hidden, fields={"text": "b"}).json()["entity"]
        api.modules("extra", enabled=True)
        back = api.get(gadget["id"]).json()
        assert back["fields"] == {"text": "b", "extra.wings": True}
        assert back["field_visibility"] == {"extra.wings": "spoiler"}
    # a later release archives the text field: its value is kept but hidden
    kinds = tuple(
        replace(k, fields=tuple(replace(f, archived=f.key == "text") for f in k.fields))
        if k.key == "gadget"
        else k
        for k in WORLD.kinds
    )
    with make_client(tmp_path, (replace(WORLD, kinds=kinds), EXTRA)) as client:
        api = Api(client, api.vault)
        archived = api.get(gadget["id"]).json()
        assert archived["fields"] == {"extra.wings": True}
        problem(api.patch(archived, fields={"text": "c"}), 422, "validation_error")
        api.patch(archived, fields={"boolean": True})
    with make_client(tmp_path) as client:
        assert Api(client, api.vault).get(gadget["id"]).json()["fields"] == {
            "text": "b",
            "extra.wings": True,
            "boolean": True,
        }


# --- dimensions and parents -----------------------------------------------------------------


def test_dimension_rules(api: Api) -> None:
    dimension = api.make("dimension")
    misc = api.make("misc", dimension_id=dimension["id"])
    nested = api.create("dimension", dimension_id=dimension["id"])
    assert invalid(nested) == ["dimension_id"]
    for kind in ("event", "timeline", "calendar", "relic"):  # can't be multiversal
        response = api.create(kind, fields={"origin": "x"} if kind == "relic" else {})
        assert invalid(response) == ["dimension_id"]
    assert api.make("event", dimension_id=dimension["id"])["dimension_id"] == dimension["id"]
    assert api.make("gadget")["dimension_id"] is None  # multiversal
    not_a_dimension = api.create("misc", dimension_id=misc["id"])
    problem(not_a_dimension, 422, "validation_error")
    problem(
        api.create("misc", dimension_id="0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"),
        422,
        "validation_error",
    )
    api.delete(dimension["id"])
    problem(api.create("misc", dimension_id=dimension["id"]), 422, "validation_error")


def test_moving_between_dimensions(api: Api) -> None:
    first, second = api.make("dimension", "First"), api.make("dimension", "Second")
    parent = api.make("misc", dimension_id=first["id"])
    child = api.make("misc", dimension_id=first["id"], parent_id=parent["id"])
    stranded = api.patch(parent, dimension_id=second["id"])
    assert invalid(stranded) == ["dimension_id"]
    # the child can't move away from its parent's dimension either...
    problem(api.patch(child, dimension_id=second["id"]), 422, "parent_not_allowed")
    # ...but it can become multiversal, and then the parent can move
    child = api.patch(child, dimension_id=None).json()["entity"]
    moved = api.patch(parent, dimension_id=second["id"])
    assert moved.status_code == 200
    assert moved.json()["affected"]["dimensions"] == [first["id"], second["id"]]
    event = api.make("event", dimension_id=first["id"])
    problem(api.patch(event, dimension_id=second["id"]), 422, "validation_error")


def test_parent_rules(api: Api) -> None:
    first, second = api.make("dimension", "First"), api.make("dimension", "Second")
    folder = api.make("misc", dimension_id=first["id"])
    gadget = api.make("gadget", dimension_id=first["id"], parent_id=folder["id"])
    assert gadget["parent_id"] == folder["id"]
    part = api.make("gadget", dimension_id=first["id"], parent_id=gadget["id"])
    created = api.create("gadget", dimension_id=first["id"], parent_id=gadget["id"]).json()
    assert created["affected"]["entities"] == [created["entity"]["id"], gadget["id"]]

    # kind not allowed
    for kind, parent in (("misc", gadget), ("relic", gadget)):
        response = api.create(
            kind,
            dimension_id=first["id"],
            parent_id=parent["id"],
            fields={"origin": "x"} if kind == "relic" else {},
        )
        body = problem(response, 422, "parent_not_allowed")
        assert body["errors"][0]["path"] == "parent_id"
    problem(
        api.create("event", dimension_id=first["id"], parent_id=gadget["id"]),
        422,
        "parent_not_allowed",
    )
    # cycles
    problem(api.patch(gadget, parent_id=gadget["id"]), 422, "parent_not_allowed")
    problem(api.patch(gadget, parent_id=part["id"]), 422, "parent_not_allowed")
    # dimension mismatch, unless one side is multiversal
    problem(
        api.create("misc", dimension_id=second["id"], parent_id=folder["id"]),
        422,
        "parent_not_allowed",
    )
    assert api.create("misc", parent_id=folder["id"]).status_code == 201
    multiversal = api.make("misc")
    assert (
        api.create("misc", dimension_id=second["id"], parent_id=multiversal["id"]).status_code
        == 201
    )
    # missing and trashed parents
    problem(
        api.create("misc", parent_id="0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"),
        422,
        "parent_not_allowed",
    )
    api.delete(multiversal["id"])
    problem(api.create("misc", parent_id=multiversal["id"]), 422, "parent_not_allowed")
    # moving: affected lists both parents; clearing the parent makes a root
    moved = api.patch(part, parent_id=folder["id"])
    assert moved.json()["affected"]["entities"] == [part["id"], gadget["id"], folder["id"]]
    root = api.patch(moved.json()["entity"], parent_id=None).json()["entity"]
    assert root["parent_id"] is None


def test_parent_of_a_disabled_kind(api: Api) -> None:
    beast = api.make("beast")
    api.modules("extra", enabled=False)
    problem(api.create("misc", parent_id=beast["id"]), 422, "parent_not_allowed")


# --- concurrency ----------------------------------------------------------------------------


def test_revision_conflict(api: Api) -> None:
    entity = api.make("misc", "One")
    updated = api.patch(entity, name="Two").json()["entity"]
    assert updated["revision"] == 2
    assert updated["slug"] == "two"
    stale = api.patch(entity, name="Three")
    body = problem(stale, 409, "revision_conflict")
    assert body["context"]["current"]["name"] == "Two"
    assert body["context"]["current"]["revision"] == 2
    assert api.get(entity["id"]).json()["name"] == "Two"
    problem(api.patch(entity, revision=None), 422, "validation_error")
    assert (
        api.client.patch(f"{api.base}/entities/{entity['id']}", json={"name": "x"}).status_code
        == 422
    )


def test_revision_bumps_on_every_change(api: Api) -> None:
    entity = api.make("misc", aliases=[{"alias": "A"}])
    same = api.patch(entity).json()["entity"]  # nothing sent: nothing changes
    assert same["revision"] == 1
    assert same["updated_at"] == entity["updated_at"]
    response = api.patch(entity, tags=["new"])
    assert response.json()["entity"]["revision"] == 2
    assert response.json()["affected"]["search_changed"] is True
    response = api.patch(response.json()["entity"], sort_key="b0")
    assert response.json()["entity"]["revision"] == 3
    assert response.json()["affected"]["search_changed"] is False


def test_null_for_required_members(api: Api) -> None:
    entity = api.make("misc")
    problem(api.patch(entity, name=None), 422, "validation_error")
    problem(api.patch(entity, visibility=None), 422, "validation_error")
    problem(api.patch(entity, summary=None), 422, "validation_error")
    cleared = api.patch(api.make("misc", icon="x", color="#000000"), icon=None, color=None)
    assert (cleared.json()["entity"]["icon"], cleared.json()["entity"]["color"]) == (None, None)


# --- aliases and tags -----------------------------------------------------------------------


def test_aliases_are_replaced_and_kept_by_id(api: Api) -> None:
    entity = api.make("misc", aliases=[{"alias": "A"}, {"alias": "B"}])
    first, second = entity["aliases"]
    response = api.patch(
        entity,
        aliases=[
            {"id": second["id"], "alias": "B2", "visibility": "spoiler"},
            {"alias": "C"},
        ],
    )
    aliases = response.json()["entity"]["aliases"]
    assert [(a["alias"], a["visibility"]) for a in aliases] == [("B2", "spoiler"), ("C", "public")]
    assert aliases[0]["id"] == second["id"]
    other = api.make("misc", aliases=[{"alias": "X"}])
    foreign = api.patch(
        response.json()["entity"], aliases=[{"id": other["aliases"][0]["id"], "alias": "X"}]
    )
    assert invalid(foreign) == ["aliases.0.id"]
    gone = api.patch(response.json()["entity"], aliases=[{"id": first["id"], "alias": "A"}])
    problem(gone, 422, "validation_error")


def test_tags_are_shared_case_insensitively(api: Api) -> None:
    first = api.make("misc", tags=["Élan"])
    second = api.make("misc", tags=["élan", "Other"])
    # same tag with its original spelling (sorted by the case-folded name: "other" < "élan")
    assert second["tags"][1] == first["tags"][0]
    cleared = api.patch(second, tags=[]).json()["entity"]
    assert cleared["tags"] == []
    assert api.get(first["id"]).json()["tags"] == first["tags"]


# --- trash, restore, purge ------------------------------------------------------------------


def test_trash_and_restore(api: Api) -> None:
    parent = api.make("misc")
    child = api.make("misc", parent_id=parent["id"])
    trashed = api.delete(parent["id"])
    assert trashed.status_code == 200
    result = trashed.json()
    assert result["purged"] is False
    assert result["entity"]["deleted_at"] is not None
    assert result["affected"]["search_changed"] is True
    assert api.get(parent["id"]).json()["deleted_at"] is not None
    assert api.get(child["id"]).json()["parent_id"] == parent["id"]  # children stay
    assert api.delete(parent["id"]).json()["entity"]["deleted_at"] == result["entity"]["deleted_at"]
    problem(api.patch(result["entity"], name="x"), 409, "conflict")
    restored = api.restore(parent["id"])
    assert restored.status_code == 200
    assert restored.json()["entity"]["deleted_at"] is None
    assert api.restore(parent["id"]).status_code == 200  # idempotent
    assert api.patch(restored.json()["entity"], name="Back").status_code == 200


def test_purge(api: Api, app: FastAPI) -> None:
    dimension = api.make("dimension")
    entity = api.make("misc", dimension_id=dimension["id"], aliases=[{"alias": "A"}], tags=["T"])
    other = api.make("misc", dimension_id=dimension["id"], tags=["T"])
    # The link service arrives with #36: insert the link directly.
    manager: VaultManager = app.state.vaults
    with manager.open(api.vault).write_sessions() as session, session.begin():
        session.add(Link(link_type="core.related", source_id=other["id"], target_id=entity["id"]))

    problem(api.delete(entity["id"], purge=True), 409, "conflict")  # not in the trash
    api.delete(entity["id"])
    purged = api.delete(entity["id"], purge=True)
    assert purged.status_code == 200
    assert purged.json() == {
        "id": entity["id"],
        "purged": True,
        "entity": None,
        "affected": {
            "entities": [entity["id"], other["id"]],
            "dimensions": [dimension["id"]],
            "time_changed": False,
            "search_changed": True,
        },
    }
    assert [entity["id"]] == entity_modules.PURGED
    problem(api.get(entity["id"]), 404, "not_found")
    assert api.get(other["id"]).json()["tags"] == other["tags"]
    with manager.open(api.vault).sessions() as session:
        assert session.query(Link).count() == 0


def test_purge_is_refused_while_children_or_contents_exist(api: Api) -> None:
    dimension = api.make("dimension")
    parent = api.make("misc", dimension_id=dimension["id"])
    child = api.make("misc", dimension_id=dimension["id"], parent_id=parent["id"])
    api.delete(parent["id"])
    api.delete(child["id"])  # trashed children count too
    body = problem(api.delete(parent["id"], purge=True), 409, "conflict")
    assert body["context"] == {"references": {"children": 1}}
    api.delete(dimension["id"])
    body = problem(api.delete(dimension["id"], purge=True), 409, "conflict")
    assert body["context"] == {"references": {"entities in this dimension": 2}}
    assert api.delete(child["id"], purge=True).status_code == 200
    assert api.delete(parent["id"], purge=True).status_code == 200
    assert api.delete(dimension["id"], purge=True).status_code == 200


def test_unknown_entity(api: Api) -> None:
    missing = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    problem(api.get(missing), 404, "not_found")
    problem(api.delete(missing), 404, "not_found")
    problem(api.restore(missing), 404, "not_found")
    problem(api.patch({"id": missing, "revision": 1}, name="x"), 404, "not_found")
    problem(api.get("not-an-id"), 422, "validation_error")


# --- modules, extensions, read-only ---------------------------------------------------------


def test_entities_of_disabled_modules(api: Api) -> None:
    beast = api.make("beast")
    api.modules("extra", enabled=False)
    for response in (
        api.create("beast"),
        api.get(beast["id"]),
        api.patch(beast, name="x"),
        api.delete(beast["id"]),
        api.restore(beast["id"]),
    ):
        problem(response, 404, "module_disabled")
    api.modules("extra", enabled=True)
    assert api.get(beast["id"]).json()["name"] == beast["name"]


def test_kind_extensions(api: Api) -> None:
    beast = api.make("beast")
    assert beast["ext"] == {"habitat": "unknown"}  # called on create without ext
    beast = api.make("beast", ext={"habitat": "caves"})
    assert beast["ext"] == {"habitat": "caves"}
    bad = api.create("beast", ext={"color": "red"})
    assert invalid(bad) == ["ext.habitat"]
    updated = api.patch(beast, ext={"habitat": "sea"}).json()["entity"]
    assert (updated["ext"], updated["revision"]) == ({"habitat": "sea"}, 2)


def test_kind_extension_registration() -> None:
    def ext(kind: str) -> KindExtension:
        return KindExtension(kind, write=lambda *_: None, read=lambda *_: None)

    with pytest.raises(RegistryError) as caught:
        ModuleRegistry(
            [
                ModuleSpec(
                    id="a", name="A", description="", kind_extensions=(ext("ghost"), ext("event"))
                ),
                ModuleSpec(id="b", name="B", description="", kind_extensions=(ext("event"),)),
            ]
        )
    assert caught.value.problems == [
        "a: kind extension for 'ghost': unknown kind",
        "b: kind extension for 'event': the kind already has one (a)",
    ]


def test_contributions_to_kinds_of_disabled_modules_do_not_break(tmp_path: Path) -> None:
    other = ModuleSpec(
        id="other",
        name="O",
        description="",
        field_contributions=(
            FieldContribution("beast", (FieldDef("other.size", "Size", "integer"),)),
        ),
    )
    with make_client(tmp_path, (*ENTITY_MODULES, other)) as client:
        api = Api(client)
        assert api.make("beast", fields={"other.size": "3"})["fields"] == {"other.size": "3"}


def test_read_only_server(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        api = Api(client)
        entity = api.make("misc")
    with make_client(tmp_path, read_only=True) as client:
        api = Api(client, api.vault)
        assert api.get(entity["id"]).status_code == 200
        problem(api.create("misc"), 403, "read_only")
        problem(api.patch(entity, name="x"), 403, "read_only")
        problem(api.delete(entity["id"]), 403, "read_only")
        problem(api.restore(entity["id"]), 403, "read_only")


def test_openapi_operations(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    collection = paths["/api/v1/vaults/{vault_id}/entities"]
    item = paths["/api/v1/vaults/{vault_id}/entities/{entity_id}"]
    assert collection["post"]["operationId"] == "entities_create"
    assert {method: item[method]["operationId"] for method in ("get", "patch", "delete")} == {
        "get": "entities_get",
        "patch": "entities_update",
        "delete": "entities_delete",
    }
    restore = paths["/api/v1/vaults/{vault_id}/entities/{entity_id}/restore"]["post"]
    assert restore["operationId"] == "entities_restore"
