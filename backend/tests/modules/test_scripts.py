"""The scripts module (``docs/modules/scripts.md``): a writing system's font is a ``media`` field,
so the font file is referenced (kept, published) and readers get it exactly when they see the
field; languages choose how their headwords show."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.entity_api import HEADERS, LinkApi, invalid, make_client
from tests.entity_modules import with_real_modules
from tests.modules.test_media import Library, sfnt, woff


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path, with_real_modules()) as made:
        yield made


@pytest.fixture
def library(client: TestClient) -> Library:
    return Library(LinkApi(client), client)


def test_writing_systems_hold_a_font_and_languages_a_headword_display(library: Library) -> None:
    api = library.api
    registry = library.client.get(f"{api.base}/registry").json()
    kinds = {kind["key"]: kind for kind in registry["kinds"]}
    script_fields = {f["key"]: f for f in kinds["writing_system"]["fields"]}
    assert script_fields["scripts.font"]["type"] == "media"
    assert {"scripts.font_scale", "scripts.sample"} <= set(script_fields)
    headwords = {f["key"]: f for f in kinds["language"]["fields"]}["scripts.headwords"]
    assert [option["key"] for option in headwords["options"]] == ["script", "plain"]

    font = library.uploaded(woff(), "runes.woff2")
    runes = api.make("writing_system", "Runes", fields={
        "scripts.font": font["id"], "scripts.font_scale": 120, "scripts.sample": "ᚠᚢᚦ",
    })  # fmt: skip
    assert runes["fields"]["scripts.font"] == font["id"]
    assert library.refs(font["id"]) == [(runes["id"], "field:scripts.font")]
    assert invalid(api.create("writing_system", "Bad", fields={"scripts.font": 3})) == [
        "fields.scripts.font"
    ]
    elvish = api.make("language", "Elvish", fields={"scripts.headwords": "plain"})
    assert elvish["fields"]["scripts.headwords"] == "plain"


def test_readers_get_the_font_only_with_the_field(library: Library) -> None:
    api = library.api
    shown = library.uploaded(sfnt(), "runes.ttf")
    secret = library.uploaded(sfnt(b"OTTO"), "secret.otf")
    api.make("writing_system", "Runes", fields={"scripts.font": shown["id"]})
    api.make("writing_system", "Cipher", fields={"scripts.font": secret["id"]},
             field_visibility={"scripts.font": "private"})  # fmt: skip
    assert library.file(shown["id"], as_reader=True).status_code == 200
    assert library.file(secret["id"], as_reader=True).status_code == 404


def test_disabling_the_module_hides_its_fields(library: Library) -> None:
    api = library.api
    font = library.uploaded(woff(), "runes.woff2")
    runes = api.make("writing_system", "Runes", fields={"scripts.font": font["id"]})
    assert api.modules("scripts", enabled=False).status_code == 200
    fields = api.get(runes["id"]).json()["fields"]
    assert "scripts.font" not in fields
    assert library.client.get(f"{api.base}/registry", headers=HEADERS).status_code == 200
