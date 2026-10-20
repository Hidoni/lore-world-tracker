"""The lexicon (``docs/modules/languages.md``, Tables and API): entries of a language sorted by
its own alphabet, with attestation periods, search documents, history and CSV import/export."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lore.modules.languages.collation import Alphabet
from tests.entity_api import LinkApi, make_client, problem
from tests.entity_modules import with_real_modules


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


def path(api: LinkApi, rest: str) -> str:
    return f"{api.base}/m/languages{rest}"


def add(api: LinkApi, language: dict[str, Any], headword: str, **body: Any) -> dict[str, Any]:
    response = api.client.post(
        path(api, f"/{language['id']}/lexicon"), json={"headword": headword, **body}
    )
    assert response.status_code == 201, response.json()
    entry: dict[str, Any] = response.json()["entry"]
    return entry


def words(api: LinkApi, language: dict[str, Any], **params: Any) -> list[str]:
    response = api.client.get(path(api, f"/{language['id']}/lexicon"), params=params)
    assert response.status_code == 200, response.json()
    return [item["headword"] for item in response.json()["items"]]


# --- collation ------------------------------------------------------------------------------


def test_collation_with_multigraphs() -> None:
    alphabet = Alphabet.parse("a b c ch d h")
    assert alphabet.tokens("Chad") == ["ch", "a", "d"]
    assert alphabet.tokens("chhad") == ["ch", "h", "a", "d"]
    ordered = sorted(["dab", "cha", "cab", "had", "Abc", "czz", "ach"], key=alphabet.key)
    # "ch" is its own letter after "c": every c-word comes before every ch-word.
    assert ordered == ["Abc", "ach", "cab", "czz", "cha", "dab", "had"]
    # Letters outside the alphabet come after it, by code point; case doesn't matter.
    assert alphabet.key("a!") > alphabet.key("ah")
    assert alphabet.key("CHA") == alphabet.key("cha")


def test_empty_alphabet_is_unicode_order() -> None:
    alphabet = Alphabet.parse("")
    assert sorted(["b", "A", "c", "ä"], key=alphabet.key) == ["A", "b", "c", "ä"]


# --- entries --------------------------------------------------------------------------------


def test_crud_and_sorting(api: LinkApi) -> None:
    varnish = api.make("language", "Varnish", fields={"alphabet_order": "a b c ch d"})
    cab = add(
        api,
        varnish,
        "cab",
        romanization="kab",
        part_of_speech="noun",
        definitions=[{"gloss": "a boat", "examples": [{"text": "cab a", "translation": "a boat"}]}],
        tags=["sea", "sea"],
    )
    add(api, varnish, "chad", part_of_speech="verb", definitions=[{"gloss": "to sail"}])
    add(api, varnish, "dab", definitions=[{"gloss": "wave"}], tags=["sea"])
    assert cab["tags"] == ["sea"]
    assert words(api, varnish) == ["cab", "chad", "dab"]
    assert words(api, varnish, sort="headword") == ["cab", "chad", "dab"]
    assert words(api, varnish, pos="verb") == ["chad"]
    assert words(api, varnish, tag="sea") == ["cab", "dab"]
    assert words(api, varnish, q="ka") == ["cab"]  # romanization
    assert words(api, varnish, q="sail") == ["chad"]  # a gloss
    assert words(api, varnish, q="%") == []

    # Paging by cursor.
    first = api.client.get(path(api, f"/{varnish['id']}/lexicon"), params={"limit": 2}).json()
    assert [i["headword"] for i in first["items"]] == ["cab", "chad"]
    rest = api.client.get(
        path(api, f"/{varnish['id']}/lexicon"), params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert ([i["headword"] for i in rest["items"]], rest["next_cursor"]) == (["dab"], None)
    bad = api.client.get(path(api, f"/{varnish['id']}/lexicon"), params={"cursor": "x"})
    problem(bad, 422, "validation_error")

    # Update with revisions, then trash.
    patched = api.client.patch(
        path(api, f"/lexicon/{cab['id']}"), json={"revision": 1, "headword": "dac"}
    )
    assert patched.status_code == 200, patched.json()
    assert patched.json()["entry"]["revision"] == 2
    stale = api.client.patch(
        path(api, f"/lexicon/{cab['id']}"), json={"revision": 1, "pronunciation": "x"}
    )
    problem(stale, 409, "revision_conflict")
    assert words(api, varnish) == ["chad", "dab", "dac"]
    assert api.client.delete(path(api, f"/lexicon/{cab['id']}")).status_code == 200
    assert words(api, varnish) == ["chad", "dab"]
    problem(
        api.client.patch(path(api, f"/lexicon/{cab['id']}"), json={"revision": 3}), 404, "not_found"
    )


def test_validation(api: LinkApi) -> None:
    varnish = api.make("language", "Varnish")
    url = path(api, f"/{varnish['id']}/lexicon")
    problem(api.client.post(url, json={"headword": " "}), 422, "validation_error")
    problem(
        api.client.post(url, json={"headword": "a", "definitions": [{"gloss": ""}]}),
        422,
        "validation_error",
    )
    point = {"anchor": {"kind": "absolute", "t": "5"}, "precision": "base"}
    no_timeline = api.client.post(url, json={"headword": "a", "valid_from": point})
    assert [e["path"] for e in problem(no_timeline, 422, "validation_error")["errors"]] == [
        "timeline_id"
    ]
    gadget = api.make("gadget")
    problem(
        api.client.post(path(api, f"/{gadget['id']}/lexicon"), json={"headword": "a"}),
        404,
        "not_found",
    )


def test_attestation_periods_resolve(api: LinkApi) -> None:
    world = api.make("dimension", "Aetheria")
    api.calendar(world["id"])
    timeline = world["ext"]["prime_timeline_id"]
    varnish = api.make("language", "Varnish", dimension_id=world["id"])

    def point(t: int) -> dict[str, Any]:
        return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}

    entry = add(
        api, varnish, "old", timeline_id=timeline, valid_from=point(100), valid_to=point(900)
    )
    assert (entry["valid_from_t"], entry["valid_to_t"], entry["time_status"]) == (
        "100",
        "900",
        "ok",
    )
    other = api.make("dimension", "Umbra")
    wrong = api.client.post(
        path(api, f"/{varnish['id']}/lexicon"),
        json={
            "headword": "x",
            "timeline_id": other["ext"]["prime_timeline_id"],
            "valid_from": point(1),
        },
    )
    problem(wrong, 422, "validation_error")


def test_alphabet_change_recollates(api: LinkApi) -> None:
    varnish = api.make("language", "Varnish")
    for word in ("cha", "ca", "da"):
        add(api, varnish, word)
    assert words(api, varnish) == ["ca", "cha", "da"]
    api.patch(varnish, fields={"alphabet_order": "a ch c d"})
    assert words(api, varnish) == ["cha", "ca", "da"]


def test_search_finds_entries_and_undo_reindexes(api: LinkApi) -> None:
    varnish = api.make("language", "Varnish")
    entry = add(api, varnish, "thalass", romanization="talas", definitions=[{"gloss": "the sea"}])

    def hits(q: str) -> list[str]:
        response = api.client.get(f"{api.base}/search", params={"q": q})
        assert response.status_code == 200, response.json()
        return [hit["name"] for hit in response.json()["items"]]

    assert "thalass" in hits("thalass")
    assert "thalass" in hits("talas")
    # From the web UI: the delete is not merged into the creation (another origin).
    api.client.delete(path(api, f"/lexicon/{entry['id']}"), headers={"X-Lore-Client": "web"})
    assert "thalass" not in hits("thalass")
    changes = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"]
    undone = api.client.post(f"{api.base}/changes/{changes[0]['id']}/revert")
    assert undone.status_code == 200, undone.json()
    assert "thalass" in hits("thalass")
    assert words(api, varnish) == ["thalass"]


def test_csv_round_trip_and_dry_run(api: LinkApi) -> None:
    varnish = api.make("language", "Varnish", fields={"alphabet_order": "a b c ch d"})
    url = path(api, f"/{varnish['id']}/lexicon/import")
    text = (
        "headword,romanization,part_of_speech,definitions,tags,etymology\n"
        "chad,chad,verb,to sail; to row,sea;old,from Old Tidespeech\n"
        "\n"
        "cab,kab,noun,a boat,sea,\n"
    )
    dry = api.client.post(url, params={"dry_run": "true"}, json={"csv": text}).json()
    assert (dry["rows"], dry["created"], dry["errors"]) == (2, 0, [])  # blank lines skipped
    assert words(api, varnish) == []
    done = api.client.post(url, json={"csv": text}).json()
    assert done["created"] == 2
    assert words(api, varnish) == ["cab", "chad"]
    exported = api.client.get(path(api, f"/{varnish['id']}/lexicon/export"))
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.text.splitlines() == [
        "headword,romanization,pronunciation,part_of_speech,definitions,tags,etymology",
        "cab,kab,,noun,a boat,sea,",
        "chad,chad,,verb,to sail; to row,sea; old,from Old Tidespeech",
    ]
    # Importing the export again doubles the lexicon (the format round-trips).
    again = api.client.post(url, json={"csv": exported.text}).json()
    assert again["created"] == 2

    # Problems refuse the whole import, with rows and columns.
    broken = "word,meaning\n,a gap\nok,fine\n"
    report = api.client.post(
        url, json={"csv": broken, "columns": {"word": "headword", "meaning": "definitions"}}
    ).json()
    assert report["created"] == 0
    assert [(e["row"], e["column"]) for e in report["errors"]] == [(1, "word")]
    unmapped = api.client.post(url, json={"csv": "word\nx\n"}).json()
    assert unmapped["errors"][0]["message"] == "No column for the headword."
    assert len(words(api, varnish)) == 4


def test_disabled_module_and_purge(api: LinkApi) -> None:
    varnish = api.make("language", "Varnish")
    add(api, varnish, "word")
    assert api.modules("scripts", enabled=False).status_code == 200  # it depends on languages
    assert api.modules("languages", enabled=False).status_code == 200
    problem(api.client.get(path(api, f"/{varnish['id']}/lexicon")), 404, "module_disabled")
    assert api.modules("languages", enabled=True).status_code == 200
    assert words(api, varnish) == ["word"]
    assert api.client.delete(f"{api.base}/entities/{varnish['id']}").status_code == 200
    purged = api.client.delete(f"{api.base}/entities/{varnish['id']}", params={"purge": "true"})
    assert purged.status_code in {200, 204}, purged.text


def test_get_entry_and_lexicon_refs(api: LinkApi) -> None:
    varnish = api.make("language", "Varnish")
    entry = add(api, varnish, "thalass", definitions=[{"gloss": "the sea"}])
    got = api.client.get(path(api, f"/lexicon/{entry['id']}"))
    assert got.status_code == 200, got.json()
    assert got.json()["headword"] == "thalass"
    api.client.delete(path(api, f"/lexicon/{entry['id']}"))
    problem(api.client.get(path(api, f"/lexicon/{entry['id']}")), 404, "not_found")

    ref = {"type": "lexiconRef", "attrs": {"entryId": entry["id"], "languageId": varnish["id"]}}
    body = {"type": "doc", "content": [{"type": "paragraph", "content": [ref]}]}
    note = api.make("gadget", "Note", body=body)
    assert api.get(note["id"]).json()["body"]["content"][0]["content"] == [ref]
    bad = dict(ref, attrs={"entryId": entry["id"], "languageId": varnish["id"], "word": "x"})
    refused = api.patch(
        note, body={"type": "doc", "content": [{"type": "paragraph", "content": [bad]}]}
    )
    problem(refused, 422, "validation_error")
