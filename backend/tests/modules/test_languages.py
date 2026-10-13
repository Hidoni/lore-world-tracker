"""The languages module (``docs/modules/languages.md``): the ``language`` and
``writing_system`` kinds, their link types and the family tree."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


def tree(api: LinkApi, **params: Any) -> Any:
    response = api.client.get(f"{api.base}/m/languages/family-tree", params=params)
    assert response.status_code == 200, response.json()
    return response.json()


def test_kinds_and_link_types(api: LinkApi) -> None:
    registry = api.client.get(f"{api.base}/registry").json()
    kinds = {kind["key"]: kind for kind in registry["kinds"]}
    language, script = kinds["language"], kinds["writing_system"]
    assert (language["icon"], language["allowed_parents"]) == ("languages", ["language", "misc"])
    assert [field["key"] for field in language["fields"]] == [
        "modality",
        "status",
        "word_order",
        "alphabet_order",
        "phonology",
        "grammar",
        "code",
    ]
    assert [field["key"] for field in script["fields"]] == [
        "script_type",
        "direction",
        "glyph_count",
    ]
    keys = {link["key"] for link in registry["link_types"] if link["module"] == "languages"}
    assert keys == {
        "languages.descended_from",
        "languages.borrowed_from",
        "languages.uses_script",
        "languages.speaks",
    }


def test_link_rules(api: LinkApi) -> None:
    old = api.make("language", "Old Varnish", fields={"modality": ["spoken", "written"]})
    varnish = api.make("language", "Varnish", fields={"status": "living", "word_order": "SOV"})
    runes = api.make("writing_system", "Tide Runes", fields={"direction": "rtl"})
    ilsa = api.make("character", "Ilsa")
    api.made_link("languages.descended_from", varnish, old)
    api.made_link("languages.uses_script", varnish, runes)
    api.made_link("languages.speaks", ilsa, varnish, data={"fluency": "native"})
    bad = api.link("languages.speaks", ilsa, old, data={"fluency": "great"})
    problem(bad, 422, "validation_error")
    problem(api.link("languages.uses_script", runes, varnish), 422, "link_type_not_allowed")
    bad_field = api.create("language", "X", fields={"modality": ["sung"]})
    problem(bad_field, 422, "validation_error")


def test_family_tree(api: LinkApi) -> None:
    world = api.make("dimension", "Aetheria")
    elsewhere = api.make("dimension", "Umbra")
    old = api.make("language", "Old Varnish", dimension_id=world["id"])
    varnish = api.make("language", "Varnish", dimension_id=world["id"])
    harbor = api.make("language", "Harbor Cant", dimension_id=world["id"], parent_id=varnish["id"])
    common = api.make("language", "Common")  # multiversal
    shadow = api.make("language", "Shadowtongue", dimension_id=elsewhere["id"])
    descent = api.made_link("languages.descended_from", varnish, old)
    loan = api.made_link("languages.borrowed_from", varnish, common, data={"note": "trade words"})
    api.made_link("languages.borrowed_from", shadow, common)
    api.made_link("core.related", varnish, old)

    graph = tree(api, dimension=world["id"])
    assert [node["name"] for node in graph["nodes"]] == [
        "Common",
        "Harbor Cant",
        "Old Varnish",
        "Varnish",
    ]
    assert next(n for n in graph["nodes"] if n["id"] == harbor["id"])["parent_id"] == varnish["id"]
    assert sorted((e["kind"], e["source_id"], e["target_id"]) for e in graph["edges"]) == sorted(
        [
            ("descended_from", varnish["id"], old["id"]),
            ("borrowed_from", varnish["id"], common["id"]),
            ("dialect", harbor["id"], varnish["id"]),
        ]
    )
    assert {e["id"] for e in graph["edges"]} >= {descent["id"], loan["id"]}
    assert len(tree(api)["nodes"]) == 5
    limited = tree(api, limit=2)
    assert (len(limited["nodes"]), limited["truncated"]) == (2, True)


def test_disabling_hides_the_family(api: LinkApi) -> None:
    varnish = api.make("language", "Varnish")
    assert api.modules("languages", enabled=False).status_code == 200
    response = api.client.get(f"{api.base}/m/languages/family-tree")
    problem(response, 404, "module_disabled")
    problem(api.get(varnish["id"]), 404, "module_disabled")
    assert api.modules("languages", enabled=True).status_code == 200
    assert [node["name"] for node in tree(api)["nodes"]] == ["Varnish"]
