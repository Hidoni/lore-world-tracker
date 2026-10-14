"""Unlinked mentions (R-LNK-3, ``api.md`` §2): names and aliases in other entities' text that
don't link to the entity, ignoring case and diacritics, at whole words, with positions."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lore.core.links.unlinked import find_occurrences, occurrences_in
from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules
from tests.test_richtext import block, doc, mention, p, text


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


def unlinked(api: LinkApi, entity_id: str, **params: Any) -> dict[str, Any]:
    response = api.client.get(f"{api.base}/entities/{entity_id}/unlinked-mentions", params=params)
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def spans(value: str, *terms: str) -> list[str]:
    return [value[start:end] for start, end in find_occurrences(value, terms)]


def test_matching_ignores_case_and_diacritics_at_whole_words() -> None:
    assert spans("Éowyn met EOWYN and eowyn's horse", "Eowyn") == ["Éowyn", "EOWYN", "eowyn"]
    assert spans("Eowyns and Leowyn", "Eowyn") == []
    # A precomposed name finds a decomposed text, and the reverse.
    assert spans("Café Noir", "Café") == ["Café"]
    # Overlapping terms: the longest wins.
    assert spans("the Iron Tower stands", "Tower", "Iron Tower") == ["Iron Tower"]
    # One-letter terms are never searched.
    assert spans("a b c", "a") == []


def test_positions_are_paths_and_utf16_offsets() -> None:
    body = doc(
        p(text("The 🐉 saw Varn.")),
        block("public", p(text("Already "), text("Varn", mention("v")), text(" and varn"))),
    )
    first, second = occurrences_in(body, "v", ["Varn"])
    # The dragon is two UTF-16 code units.
    assert (first.path, first.offset, first.length, first.text) == ([0, 0], 11, 4, "Varn")
    assert (first.before, first.after) == ("The 🐉 saw ", ".")
    assert (second.path, second.offset, second.text) == ([1, 0, 2], 5, "varn")


def test_unlinked_mentions(api: LinkApi) -> None:
    varn = api.make("location", "Várn", aliases=[{"alias": "the Old City"}])
    aria = api.make(
        "character",
        "Aria",
        body=doc(
            p(text("Born in VARN, raised in "), text("Várn", mention(varn["id"]))),
            p(text("She left the old city at dawn.")),
        ),
    )
    api.make("character", "Bram", body=doc(p(text("Varnish is not a place."))))
    api.make("character", "Cyl", body=doc(p(text("Visited "), text("Varn", mention(varn["id"])))))
    body = unlinked(api, varn["id"])
    assert body["terms"] == ["Várn", "the Old City"]
    assert body["truncated"] is False
    [item] = body["items"]
    assert item["entity"]["id"] == aria["id"]
    found = [(o["path"], o["offset"], o["text"]) for o in item["occurrences"]]
    assert found == [([0, 0], 8, "VARN"), ([1, 0], 9, "the old city")]
    # The entity's own text never counts.
    api.patch(api.get(varn["id"]).json(), body=doc(p(text("Várn is old."))))
    assert [i["entity"]["name"] for i in unlinked(api, varn["id"])["items"]] == ["Aria"]


def test_limit_and_truncation(api: LinkApi) -> None:
    tower = api.make("location", "Tower")
    for name in ("A", "B", "C"):
        api.make("misc", f"Note {name}", body=doc(p(text("the Tower"))))
    body = unlinked(api, tower["id"], limit=2)
    assert [i["entity"]["name"] for i in body["items"]] == ["Note A", "Note B"]
    assert body["truncated"] is True


def test_readers_see_only_what_they_may(api: LinkApi) -> None:
    varn = api.make("location", "Varn", aliases=[{"alias": "Hidden Name", "visibility": "private"}])
    api.make("misc", "Secret", visibility="private", body=doc(p(text("Varn"))))
    api.make(
        "misc",
        "Note",
        body=doc(p(text("Hidden Name")), block("private", p(text("Varn again")))),
    )
    author = unlinked(api, varn["id"])
    assert [i["entity"]["name"] for i in author["items"]] == ["Note", "Secret"]
    assert len(author["items"][0]["occurrences"]) == 2
    reader = unlinked(api, varn["id"], as_reader=True)
    assert reader["terms"] == ["Varn"]
    assert reader["items"] == []
    spy = api.make("character", "Spy", visibility="private")
    hidden = api.client.get(
        f"{api.base}/entities/{spy['id']}/unlinked-mentions", params={"as_reader": True}
    )
    problem(hidden, 404, "not_found")
