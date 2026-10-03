import json
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lore.app import create_app
from lore.config import Settings
from lore.core.models import load_metadata
from lore.core.modules import ModuleRegistry, ModuleSpec, RegistryError
from lore.core.registry import (
    CORE_KINDS,
    FieldContribution,
    FieldDef,
    FieldTypeDef,
    KindDef,
    LinkTypeDef,
    RuleDef,
)
from lore.core.vaults import VaultManager
from tests import sample_modules
from tests.conftest import local_client
from tests.sample_modules import ADDON, BASE, OPTIONAL, SAMPLE, SAMPLE_MODULES

HEADERS = {"X-Lore-Client": "test"}


def spec(module_id: str, **values: Any) -> ModuleSpec:
    return ModuleSpec(id=module_id, name=module_id.title(), description="", **values)


def kind(key: str, **values: Any) -> KindDef:
    return KindDef(key, key.title(), key.title() + "s", icon="box", color="#000", **values)


def problems(*modules: ModuleSpec, core_metadata: MetaData | None = None) -> list[str]:
    with pytest.raises(RegistryError) as caught:
        ModuleRegistry(modules, core_metadata=core_metadata)
    return caught.value.problems


# --- validation -----------------------------------------------------------------------------


def test_the_sample_modules_and_the_real_ones_are_valid() -> None:
    from lore.modules import ALL_MODULES  # noqa: PLC0415

    ModuleRegistry(SAMPLE_MODULES, core_metadata=load_metadata())
    ModuleRegistry(ALL_MODULES, core_metadata=load_metadata())


def test_module_id_and_dependency_errors() -> None:
    assert problems(spec("Bad-Id"), spec("core"), spec("a"), spec("a")) == [
        "module id 'Bad-Id' must match ^[a-z][a-z0-9_]*$",
        "module id 'core' is reserved",
        "duplicate module id 'a'",
    ]
    assert problems(spec("a", depends_on=("ghost",))) == ["a: unknown dependency 'ghost'"]
    assert problems(
        spec("a", depends_on=("c",)), spec("b", depends_on=("a",)), spec("c", depends_on=("b",))
    ) == ["dependency cycle: a -> c -> b -> a"]


def test_kind_errors() -> None:
    assert problems(
        spec("a", kinds=(kind("event"), kind("Bad"), kind("thing", allowed_parents=("ghost",)))),
        spec("b", kinds=(kind("thing"),)),
    ) == [
        "a: kind 'event' is already registered by core",
        "a: kind 'Bad': keys must match ^[a-z][a-z0-9_]*$",
        "a: kind 'thing': unknown allowed parent kind 'ghost'",
        "b: kind 'thing' is already registered by a",
    ]


def test_field_errors() -> None:
    fields = (
        FieldDef("a.prefixed", "X", "text"),
        FieldDef("dup", "X", "text"),
        FieldDef("dup", "X", "text"),
        FieldDef("odd", "X", "no_such_type"),
        FieldDef("pick", "X", "enum"),
    )
    assert problems(spec("a", kinds=(kind("thing", fields=fields),))) == [
        "a: kind 'thing': own field 'a.prefixed' must be unprefixed (^[a-z][a-z0-9_]*$)",
        "a: kind 'thing': duplicate field 'dup'",
        "a: kind 'thing': field 'odd' has unknown type 'no_such_type'",
        "a: kind 'thing': field 'pick' needs options",
    ]
    assert problems(
        spec("a", kinds=(kind("thing", fields=(FieldDef("size", "Size", "text"),)),)),
        spec(
            "b",
            field_contributions=(
                FieldContribution("thing", (FieldDef("size", "S", "text"),)),
                FieldContribution("thing", (FieldDef("a.size", "S", "text"),)),
                FieldContribution("thing", (FieldDef("b.mood", "M", "text"),)),
                FieldContribution("thing", (FieldDef("b.mood", "M", "text"),)),
                FieldContribution("ghost", (FieldDef("b.x", "X", "text"),)),
            ),
            field_types=(FieldTypeDef("text", "Text again"),),
        ),
    ) == [
        "b: field type 'text' is already provided by core",
        "b: field contribution to 'thing': field 'size' must be named b.<key>",
        "b: field contribution to 'thing': duplicate field 'size'",  # clashes with a's own field
        "b: field contribution to 'thing': field 'a.size' must be named b.<key>",
        "b: field contribution to 'thing': duplicate field 'b.mood'",
        "b: field contribution to 'ghost': unknown kind",
    ]


def test_link_type_and_rule_errors() -> None:
    rule = RuleDef(
        id="a.rule", owner="a", title="", description="", category="module",
        default_severity="warning",
    )  # fmt: skip
    assert problems(
        spec(
            "a",
            link_types=(
                LinkTypeDef("core.mine", "x"),
                LinkTypeDef("a.likes", "x", source_kinds=("ghost",)),
                LinkTypeDef("a.likes", "x"),
            ),
            consistency_rules=(
                rule,
                replace(rule, id="b.rule"),
                replace(rule, id="a.other", owner="core"),
                rule,
            ),
        ),
    ) == [
        "a: link type 'core.mine': keys must start with 'a.'",
        "a: link type 'a.likes': unknown kind 'ghost'",
        "a: link type 'a.likes' is already registered by a",
        "a: rule 'b.rule': ids must start with 'a.'",
        "a: rule 'a.other': owner is 'core', expected 'a'",
        "a: rule 'a.rule' is already registered by a",
    ]


class OtherBase(DeclarativeBase):
    pass


class Unprefixed(OtherBase):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class Stolen(OtherBase):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class Owned(OtherBase):
    __tablename__ = "a_things"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


def test_table_errors() -> None:
    core = MetaData()
    Table("entities", core, Column("id", String, primary_key=True))
    Table("b_core_table", core, Column("id", String, primary_key=True))
    assert problems(
        spec("a", models=(Owned, Unprefixed, str)),
        spec("b", models=(Stolen,)),
        spec("c", models=(Owned,)),
        core_metadata=core,
    ) == [
        "a: table 'notes' must be prefixed 'a_'",
        "a: str is not a mapped table model",
        "b: table 'entities' must be prefixed 'b_'",
        "b: table 'entities' is a core table",
        "c: table 'a_things' must be prefixed 'c_'",
        "c: table 'a_things' is also defined by a",
        "core table 'b_core_table' uses module 'b''s prefix",
    ]


def test_create_app_refuses_an_invalid_registry() -> None:
    with pytest.raises(RegistryError):
        create_app(Settings(), modules=[spec("a", depends_on=("ghost",))])


# --- views ----------------------------------------------------------------------------------

REGISTRY = ModuleRegistry(SAMPLE_MODULES)


def test_dependencies_and_effective_enablement() -> None:
    assert REGISTRY.dependencies("addon") == ["base", "sample"]
    assert REGISTRY.dependents("base") == ["sample", "addon"]
    assert REGISTRY.effective({}) == {"base", "sample", "addon"}
    assert REGISTRY.effective({"optional": True}) == {"base", "sample", "addon", "optional"}
    # a module whose dependency is off is off too, whatever its own setting
    assert REGISTRY.effective({"base": False, "addon": True}) == frozenset()
    assert REGISTRY.effective({"addon": False}) == {"base", "sample"}


def test_views_follow_enablement() -> None:
    every = REGISTRY.kinds_for({"base", "sample", "addon"})
    assert [k.key for k in every] == [*(k.key for k in CORE_KINDS), "place", "creature"]
    by_key = {k.key: k for k in every}
    assert [f.key for f in by_key["event"].fields] == ["sample.mood"]
    assert [f.key for f in by_key["place"].fields] == ["sample.lair"]
    assert by_key["creature"].owner == "sample"
    assert by_key["event"].owner == "core"
    only_base = {k.key: k for k in REGISTRY.kinds_for({"base"})}
    assert "creature" not in only_base
    assert only_base["place"].fields == ()  # sample's contribution is gone with it
    assert [t.key for t in REGISTRY.field_types_for({"sample"})][-1] == "sample_rating"
    assert "sample_rating" not in [t.key for t in REGISTRY.field_types_for(set())]
    link_keys = [t.definition.key for t in REGISTRY.link_types_for({"base", "sample", "optional"})]
    assert link_keys == [
        "core.participant", "core.causes", "core.related", "sample.hunts", "sample.lives_in",
        "optional.studies",
    ]  # fmt: skip
    # optional.studies targets creatures only: hidden without the sample module
    assert "optional.studies" not in [
        t.definition.key for t in REGISTRY.link_types_for({"optional"})
    ]
    assert [r.id for r in REGISTRY.rules_for({"sample"})] == ["sample.creature.too_dangerous"]
    assert REGISTRY.rules_for({"base"}) == []


# --- API ------------------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    app = create_app(Settings(data_dir=tmp_path), modules=SAMPLE_MODULES)
    sample_modules.HOOK_CALLS.clear()
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with local_client(app, headers=HEADERS) as test_client:
        yield test_client


def new_vault(client: TestClient, name: str = "Aetheria") -> str:
    vault_id: str = client.post("/api/v1/vaults", json={"name": name}).json()["id"]
    return vault_id


def states(client: TestClient, vault_id: str) -> dict[str, bool]:
    modules = client.get(f"/api/v1/vaults/{vault_id}/registry").json()["modules"]
    return {module["id"]: module["enabled"] for module in modules}


def patch(client: TestClient, vault_id: str, module_id: str, **body: Any) -> Any:
    return client.patch(f"/api/v1/vaults/{vault_id}/modules/{module_id}", json=body)


def test_registry_endpoint(client: TestClient) -> None:
    vault = new_vault(client)
    registry = client.get(f"/api/v1/vaults/{vault}/registry").json()
    assert set(registry) == {"kinds", "field_types", "link_types", "modules", "consistency_rules"}
    assert registry["modules"][1] == {
        "id": "sample",
        "name": "Sample",
        "description": "Every extension point.",
        "depends_on": ["base"],
        "default_enabled": True,
        "enabled": True,
    }
    assert states(client, vault) == {"base": True, "sample": True, "addon": True, "optional": False}
    kinds = {k["key"]: k for k in registry["kinds"]}
    assert set(kinds) == {"dimension", "timeline", "calendar", "event", "place", "creature"}
    creature = kinds["creature"]
    assert creature["module"] == "sample"
    assert creature["allowed_parents"] == ["creature", "misc"]
    assert creature["capabilities"]["can_have_worldline"] is True
    assert creature["fields"][0] == {
        "key": "diet", "label": "Diet", "type": "enum",
        "options": [{"key": "meat", "label": "Meat", "color": None},
                    {"key": "plants", "label": "Plants", "color": "#0f0"}],
        "multiple": False, "required": False, "temporal": False, "default_visibility": "public",
        "section": None, "sort": 0, "help": "", "searchable": True, "archived": False,
    }  # fmt: skip
    assert kinds["event"]["capabilities"]["is_time_bound"] is True
    assert kinds["event"]["fields"][0]["key"] == "sample.mood"
    assert kinds["dimension"]["capabilities"]["is_system"] is True
    links = {t["key"]: t for t in registry["link_types"]}
    assert links["sample.hunts"] == {
        "key": "sample.hunts", "module": "sample", "user_defined": False, "label": "hunts",
        "inverse_label": "hunted by", "description": "", "source_kinds": ["creature"],
        "target_kinds": "*", "symmetric": False, "temporal": "optional", "unique": "per_pair",
        "max_targets_per_source": 3, "max_sources_per_target": None,
        "data_schema": {"type": "object"}, "graph": {"color": "#f00", "dashed": True, "weight": 2},
        "archived": False, "revision": None,
    }  # fmt: skip
    assert links["core.related"]["symmetric"] is True
    assert "optional.studies" not in links
    assert [t["key"] for t in registry["field_types"]][-1] == "sample_rating"
    [rule] = registry["consistency_rules"]
    assert rule == {
        "id": "sample.creature.too_dangerous", "owner": "sample", "title": "Too dangerous",
        "description": "Lower the danger.", "category": "module", "default_severity": "warning",
        "configurable": True, "triggers": [{"kind": "field", "key": "danger"}],
        "quick_fixes": [{"id": "sample.calm", "title": "Calm it down"}],
    }  # fmt: skip


def test_registry_includes_user_defined_link_types(app: FastAPI, client: TestClient) -> None:
    from lore.core.links.models import CustomLinkType  # noqa: PLC0415

    vault = new_vault(client)
    manager: VaultManager = app.state.vaults
    with manager.open(vault).write_sessions.begin() as session:
        session.add(CustomLinkType(key="custom.sworn_enemy", label="sworn enemy of",
                                   symmetric=True))  # fmt: skip
        session.add(CustomLinkType(key="custom.tames", label="tames",
                                   target_kinds=["creature"]))  # fmt: skip
    links = {
        t["key"]: t for t in client.get(f"/api/v1/vaults/{vault}/registry").json()["link_types"]
    }
    assert links["custom.sworn_enemy"]["user_defined"] is True
    assert links["custom.sworn_enemy"]["module"] == "core"
    assert links["custom.sworn_enemy"]["revision"] == 1
    assert links["custom.sworn_enemy"]["graph"] == {"color": None, "dashed": False, "weight": 1}
    assert "custom.tames" in links
    patch(client, vault, "sample", enabled=False, cascade=True)
    after = client.get(f"/api/v1/vaults/{vault}/registry").json()["link_types"]
    keys = {link_type["key"] for link_type in after}
    assert "custom.tames" not in keys  # its target kind is gone
    assert "custom.sworn_enemy" in keys


def test_enabling_enables_dependencies(client: TestClient) -> None:
    vault = new_vault(client)
    assert patch(client, vault, "base", enabled=False, cascade=True).json()["disabled"] == [
        "base", "sample", "addon",
    ]  # fmt: skip
    assert states(client, vault) == {"base": False, "sample": False, "addon": False,
                                     "optional": False}  # fmt: skip
    response = patch(client, vault, "addon", enabled=True)
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] == ["base", "sample", "addon"]
    assert body["disabled"] == []
    assert {m["id"]: m["enabled"] for m in body["modules"]}["addon"] is True
    assert sample_modules.HOOK_CALLS[-2:] == [("enable", "base"), ("enable", "sample")]


def test_disabling_with_dependents_needs_cascade(client: TestClient) -> None:
    vault = new_vault(client)
    refused = patch(client, vault, "base", enabled=False)
    assert refused.status_code == 409
    assert refused.json()["code"] == "module_has_dependents"
    assert refused.json()["context"] == {"dependents": ["sample", "addon"]}
    assert states(client, vault)["base"] is True
    # a leaf module goes without cascade
    leaf = patch(client, vault, "addon", enabled=False).json()
    assert (leaf["enabled"], leaf["disabled"]) == ([], ["addon"])
    cascaded = patch(client, vault, "base", enabled=False, cascade=True).json()
    assert cascaded["disabled"] == ["base", "sample"]
    assert sample_modules.HOOK_CALLS == [
        ("disable", "addon"), ("disable", "base"), ("disable", "sample"),
    ]  # fmt: skip
    # no-op requests change nothing
    again = patch(client, vault, "base", enabled=False).json()
    assert (again["enabled"], again["disabled"]) == ([], [])


def test_settings_are_stored_in_vault_meta(app: FastAPI, client: TestClient) -> None:
    from lore.core.vaults.meta import get_meta  # noqa: PLC0415

    vault = new_vault(client)
    patch(client, vault, "optional", enabled=True)
    manager: VaultManager = app.state.vaults
    with manager.open(vault).sessions() as session:
        settings = get_meta(session, "settings")
    assert settings["modules"] == {
        "base": {"enabled": True, "settings": {}},
        "sample": {"enabled": True, "settings": {}},
        "addon": {"enabled": True, "settings": {}},
        "optional": {"enabled": True, "settings": {}},
    }
    assert settings["defaults"] == {"visibility": "public"}  # the rest is untouched


def test_disabled_module_routes(client: TestClient) -> None:
    vault = new_vault(client)
    base = f"/api/v1/vaults/{vault}/m"
    assert client.get(f"{base}/sample/ping").json() == {"pong": "sample"}
    assert client.get(f"{base}/addon/ping").json() == {"pong": "addon"}
    patch(client, vault, "sample", enabled=False, cascade=True)
    for module_id in ("sample", "addon"):
        response = client.get(f"{base}/{module_id}/ping")
        assert response.status_code == 404
        assert response.json()["code"] == "module_disabled"
    patch(client, vault, "addon", enabled=True)
    assert client.get(f"{base}/sample/ping").status_code == 200


def test_registry_is_per_vault(client: TestClient) -> None:
    first, second = new_vault(client, "First"), new_vault(client, "Second")
    patch(client, first, "sample", enabled=False, cascade=True)
    assert states(client, first)["sample"] is False
    assert states(client, second)["sample"] is True
    first_kinds = {k["key"] for k in client.get(f"/api/v1/vaults/{first}/registry").json()["kinds"]}
    assert "creature" not in first_kinds
    assert client.get(f"/api/v1/vaults/{second}/m/sample/ping").status_code == 200
    assert client.get(f"/api/v1/vaults/{first}/m/sample/ping").status_code == 404


def test_module_errors(client: TestClient) -> None:
    vault = new_vault(client)
    unknown = patch(client, vault, "ghost", enabled=True)
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "module_not_found"
    assert patch(client, vault, "Bad-Id", enabled=True).status_code == 422
    assert patch(client, vault, "sample", enabled=True, extra=1).status_code == 422
    assert (
        client.get("/api/v1/vaults/0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b/registry").json()["code"]
        == "vault_not_found"
    )


def test_read_only_server_refuses_module_changes(tmp_path: Path) -> None:
    vault = VaultManager(tmp_path).create("Aetheria").id
    app = create_app(Settings(data_dir=tmp_path, read_only=True), modules=SAMPLE_MODULES)
    with local_client(app, headers=HEADERS) as client:
        assert client.get(f"/api/v1/vaults/{vault}/registry").status_code == 200
        response = patch(client, vault, "sample", enabled=False, cascade=True)
    assert response.status_code == 403
    assert response.json()["code"] == "read_only"


def test_openapi_operations(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert paths["/api/v1/vaults/{vault_id}/registry"]["get"]["operationId"] == "registry_get"
    assert paths["/api/v1/vaults/{vault_id}/modules/{module_id}"]["patch"]["operationId"] == (
        "modules_update"
    )
    assert paths["/api/v1/vaults/{vault_id}/m/sample/ping"]["get"]["operationId"] == "sample_ping"


def test_unused_extension_points_are_stored() -> None:
    assert len(SAMPLE.slot_providers) == len(SAMPLE.publish_contributors) == 1
    assert SAMPLE.settings_model is not None
    assert SAMPLE.settings_model().greeting == "hello"  # type: ignore[attr-defined]
    assert (BASE.default_enabled, OPTIONAL.default_enabled, ADDON.depends_on) == (
        True, False, ("sample",),
    )  # fmt: skip


# --- recorded states (modules.md §4, decided 2026-10-03) ------------------------------------


def stored_modules(path: Path) -> dict[str, Any]:
    """vault_meta.settings.modules read straight from the file (no app, no open)."""
    connection = sqlite3.connect(path)
    try:
        (value,) = connection.execute(
            "SELECT value FROM vault_meta WHERE key = 'settings'"
        ).fetchone()
    finally:
        connection.close()
    modules: dict[str, Any] = json.loads(value)["modules"]
    return modules


def flipped(module: ModuleSpec) -> ModuleSpec:
    return replace(module, default_enabled=not module.default_enabled)


def test_new_vaults_record_every_module_state(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path, module_registry=ModuleRegistry(SAMPLE_MODULES))
    info = manager.create("Aetheria")
    assert stored_modules(info.database_path) == {
        "base": {"enabled": True, "settings": {}},
        "sample": {"enabled": True, "settings": {}},
        "addon": {"enabled": True, "settings": {}},
        "optional": {"enabled": False, "settings": {}},
    }


def test_later_default_changes_do_not_affect_existing_vaults(tmp_path: Path) -> None:
    VaultManager(tmp_path, module_registry=ModuleRegistry(SAMPLE_MODULES)).create("Aetheria")
    # a later release turns optional on by default and retires addon (default off, §7)
    later = (BASE, SAMPLE, flipped(ADDON), flipped(OPTIONAL))
    app = create_app(Settings(data_dir=tmp_path), modules=later)
    with local_client(app, headers=HEADERS) as client:
        [vault] = client.get("/api/v1/vaults").json()["items"]
        assert states(client, vault["id"]) == {
            "base": True, "sample": True, "addon": True, "optional": False,
        }  # fmt: skip
        assert client.get(f"/api/v1/vaults/{vault['id']}/m/addon/ping").status_code == 200
        # ...but vaults created now get the new defaults
        fresh = new_vault(client, "Fresh")
        assert states(client, fresh)["addon"] is False
        assert states(client, fresh)["optional"] is True


def test_modules_added_later_are_recorded_on_first_open(tmp_path: Path) -> None:
    info = VaultManager(tmp_path, module_registry=ModuleRegistry((BASE,))).create("Aetheria")
    assert set(stored_modules(info.database_path)) == {"base"}
    manager = VaultManager(tmp_path, module_registry=ModuleRegistry(SAMPLE_MODULES))
    manager.open(info.id)
    manager.close()
    assert stored_modules(info.database_path) == {
        "base": {"enabled": True, "settings": {}},
        "sample": {"enabled": True, "settings": {}},
        "addon": {"enabled": True, "settings": {}},
        "optional": {"enabled": False, "settings": {}},
    }
    # recorded now: flipping sample's default afterwards changes nothing
    later = (BASE, flipped(SAMPLE), ADDON, OPTIONAL)
    with local_client(create_app(Settings(data_dir=tmp_path), modules=later),
                      headers=HEADERS) as client:  # fmt: skip
        assert states(client, info.id)["sample"] is True


def test_vaults_without_states_are_recorded_and_toggles_are_kept(tmp_path: Path) -> None:
    info = VaultManager(tmp_path).create("Older")  # no registry: nothing recorded
    assert stored_modules(info.database_path) == {}
    app = create_app(Settings(data_dir=tmp_path), modules=SAMPLE_MODULES)
    with local_client(app, headers=HEADERS) as client:
        patch(client, info.id, "optional", enabled=True)
    assert stored_modules(info.database_path)["optional"] == {"enabled": True, "settings": {}}
    assert stored_modules(info.database_path)["base"] == {"enabled": True, "settings": {}}


def test_read_only_servers_never_record(tmp_path: Path) -> None:
    info = VaultManager(tmp_path).create("Older")
    app = create_app(Settings(data_dir=tmp_path, read_only=True), modules=SAMPLE_MODULES)
    with local_client(app, headers=HEADERS) as client:
        assert states(client, info.id) == {
            "base": True, "sample": True, "addon": True, "optional": False,
        }  # fmt: skip
    assert stored_modules(info.database_path) == {}
