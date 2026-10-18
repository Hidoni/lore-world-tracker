"""The media module (``docs/modules/media.md``, ``security.md`` §3): validated uploads stored by
content, files with safe headers and thumbnails, references derived from bodies, covers and
galleries (undo included), reader visibility and the daily collection."""

import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lore.core.maintenance import check_vault
from lore.core.modules.spec import VaultContext
from lore.core.registry.types import FieldDef
from lore.modules.media import api as media_api
from lore.modules.media import storage
from lore.modules.media import svg as svg_rules
from lore.modules.media.fields import MEDIA_FIELD_TYPE
from lore.modules.media.gc import collect
from lore.modules.media.publish import copy_visible_media
from tests.entity_api import HEADERS, LinkApi, invalid, make_client
from tests.entity_modules import with_real_modules


def png(width: int = 40, height: int = 30, color: str = "red", mode: str = "RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (width, height), color if mode == "RGB" else 0).save(out, "PNG")
    return out.getvalue()


def doc(*content: Any) -> dict[str, Any]:
    return {"type": "doc", "content": list(content)}


def image(media_id: str, **attrs: Any) -> dict[str, Any]:
    return {"type": "image", "attrs": {"mediaId": media_id, **attrs}}


def block(level: str, *content: Any) -> dict[str, Any]:
    return {"type": "visibilityBlock", "attrs": {"level": level, "label": None},
            "content": list(content)}  # fmt: skip


class Library:
    def __init__(self, api: LinkApi, client: TestClient) -> None:
        self.api = api
        self.client = client
        self.base = f"{api.base}/m/media"

    def upload(self, data: bytes, filename: str = "picture.png", **form: str) -> Any:
        return self.client.post(
            f"{self.base}/items", files={"file": (filename, data)}, data=form, headers=HEADERS
        )

    def uploaded(self, data: bytes | None = None, filename: str = "picture.png") -> dict[str, Any]:
        response = self.upload(data if data is not None else png(), filename)
        assert response.status_code == 201, response.json()
        item: dict[str, Any] = response.json()["item"]
        return item

    def get(self, media_id: str, **params: Any) -> Any:
        return self.client.get(f"{self.base}/items/{media_id}", params=params)

    def file(self, media_id: str, **params: Any) -> Any:
        return self.client.get(f"{self.base}/items/{media_id}/file", params=params)

    def refs(self, media_id: str) -> list[tuple[str, str]]:
        found = self.get(media_id).json()["refs"]
        return [(ref["entity_id"], ref["context"]) for ref in found]

    def undo_last(self) -> None:
        last = self.client.get(f"{self.api.base}/changes", params={"limit": 1}).json()["items"][0]
        response = self.client.post(f"{self.api.base}/changes/{last['id']}/revert", headers=HEADERS)
        assert response.status_code == 200, response.json()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path, with_real_modules(), max_upload_mb=1) as made:
        yield made


@pytest.fixture
def library(client: TestClient) -> Library:
    return Library(LinkApi(client), client)


def vault_path(client: TestClient, library: Library) -> Path:
    manager = client.app.state.vaults  # type: ignore[attr-defined]
    path: Path = manager.open(library.api.vault).info.path
    return path


# --- uploads --------------------------------------------------------------------------------------


def test_uploads_are_stored_by_content_and_deduplicated(
    client: TestClient, library: Library
) -> None:
    data = png(40, 30)
    response = library.upload(data, "../../etc/portrait of Ilsa.png", alt="Ilsa")
    assert response.status_code == 201, response.json()
    first = response.json()
    item = first["item"]
    assert first["created"] is True
    assert (item["mime"], item["width"], item["height"], item["size"]) == (
        "image/png", 40, 30, len(data)
    )  # fmt: skip
    assert item["filename"] == "portrait of Ilsa.png"  # the last path component, display only
    assert item["alt"] == "Ilsa"
    stored = storage.file_path(vault_path(client, library), item["sha256"])
    assert stored.read_bytes() == data
    # The same bytes (under another name) are the same item.
    again = library.upload(data, "copy.png")
    assert again.status_code == 201
    assert (again.json()["created"], again.json()["item"]["id"]) == (False, item["id"])


def test_replacing_a_file_keeps_the_item(client: TestClient, library: Library) -> None:
    item = library.uploaded(png(40, 30), "old.png")
    url = f"{library.base}/items/{item['id']}/file"

    def replace(data: bytes, filename: str, revision: int) -> Any:
        return client.put(url, files={"file": (filename, data)},
                          data={"revision": str(revision)}, headers=HEADERS)  # fmt: skip

    new = png(80, 60, "blue")
    response = replace(new, "new.png", item["revision"])
    assert response.status_code == 200, response.json()
    replaced = response.json()
    assert replaced["id"] == item["id"]
    assert (replaced["filename"], replaced["width"], replaced["sha256"]) == (
        "new.png", 80, storage.digest(new)
    )  # fmt: skip
    assert library.file(item["id"]).content == new
    assert replace(png(10, 10), "x.png", item["revision"]).status_code == 409  # stale
    # An image stays an image; bytes another item holds name it.
    pdf = replace(b"%PDF-1.4\n%%EOF\n", "x.pdf", replaced["revision"])
    assert invalid(pdf) == ["file"]
    # Undo brings the old file back.
    library.undo_last()
    assert library.file(item["id"]).content == png(40, 30)
    other = library.uploaded(png(5, 5, "green"), "other.png")
    taken = replace(png(5, 5, "green"), "again.png", library.get(item["id"]).json()["revision"])
    assert taken.status_code == 409
    assert taken.json()["context"]["media_id"] == other["id"]


@pytest.mark.parametrize(
    ("data", "filename", "message"),
    [
        (b"MZ\x90\x00 not really a picture", "picture.png", "isn't supported"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "broken.png", "can't be read"),
        (b"#!/bin/sh\necho hi\x00", "notes.txt", "isn't supported"),
        (b"<html><body>no</body></html>", "page.svg", "isn't supported"),
    ],
)
def test_files_are_judged_by_their_bytes(
    library: Library, data: bytes, filename: str, message: str
) -> None:
    response = library.upload(data, filename)
    assert invalid(response) == ["file"]
    assert message in response.json()["errors"][0]["message"]


def test_oversized_files_and_decompression_bombs_are_refused(library: Library) -> None:
    too_big = library.upload(b"a" * ((1 << 20) + 1), "big.txt")
    assert invalid(too_big) == ["file"]
    assert too_big.json()["errors"][0]["code"] == "too_large"
    # A 10,000 by 10,000 image compresses to almost nothing but would need 100 megapixels.
    bomb = png(10_000, 10_000, mode="1")
    assert len(bomb) < (1 << 20)
    refused = library.upload(bomb, "bomb.png")
    assert invalid(refused) == ["file"]
    assert "too many pixels" in refused.json()["errors"][0]["message"]


def test_documents_and_svg(library: Library) -> None:
    notes = library.uploaded(b"# Notes\n\nThe gate opens at dusk.\n", "notes.md")
    assert notes["mime"] == "text/markdown"
    assert library.file(notes["id"]).headers["content-disposition"].startswith("attachment")
    svg = library.uploaded(
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script>'
        b'<circle r="4" fill="gold"/></svg>',
        "glyph.svg",
    )
    assert svg["mime"] == "image/svg+xml"
    served = library.file(svg["id"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/svg+xml"
    assert served.headers["content-disposition"].startswith("inline")
    assert served.headers["content-security-policy"].startswith("default-src 'none'")
    # Sanitized (``lore.modules.media.svg``): the circle, not the script or the handler.
    assert served.content == (
        b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4" fill="gold" /></svg>'
    )
    assert served.headers["etag"] == f'"{svg["sha256"]}-original-svg{svg_rules.VERSION}"'
    assert library.file(svg["id"], size="160").status_code == 422  # no thumbnails
    unreadable = library.upload(b'<svg xmlns="http://www.w3.org/2000/svg"><g></svg>', "x.svg")
    assert invalid(unreadable) == ["file"]
    assert "can't be read" in unreadable.json()["errors"][0]["message"]


def test_svgs_the_sanitizer_cant_read_stay_attachments(
    client: TestClient, library: Library
) -> None:
    """A file stored before the sanitizer (here: its bytes changed on disk) is sent as it is."""
    item = library.uploaded(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "old.svg")
    stored = storage.file_path(vault_path(client, library), item["sha256"])
    stored.write_bytes(b"<svg><script>alert(1)</script>")
    served = library.file(item["id"])
    assert served.status_code == 200
    assert served.headers["content-disposition"].startswith("attachment")
    assert served.content == b"<svg><script>alert(1)</script>"


def test_svgs_are_replaced_only_by_images(library: Library) -> None:
    item = library.uploaded(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "seal.svg")

    def replace(data: bytes, filename: str) -> Any:
        revision = library.get(item["id"]).json()["revision"]
        return library.client.put(
            f"{library.base}/items/{item['id']}/file", files={"file": (filename, data)},
            data={"revision": str(revision)}, headers=HEADERS,
        )  # fmt: skip

    assert invalid(replace(b"%PDF-1.4\n%%EOF\n", "seal.pdf")) == ["file"]
    assert replace(png(8, 8), "seal.png").status_code == 200
    # A raster image stays a raster image.
    assert invalid(replace(b'<svg xmlns="http://www.w3.org/2000/svg"/>', "seal.svg")) == ["file"]


# --- files ----------------------------------------------------------------------------------------


def test_files_are_served_with_safe_headers_and_thumbnails(
    client: TestClient, library: Library
) -> None:
    item = library.uploaded(png(1000, 500))
    original = library.file(item["id"])
    assert original.status_code == 200
    assert original.headers["content-type"] == "image/png"
    assert original.headers["x-content-type-options"] == "nosniff"
    assert original.headers["content-security-policy"].startswith("default-src 'none'")
    assert original.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert original.headers["content-disposition"].startswith("inline")
    etag = original.headers["etag"]
    assert item["sha256"] in etag
    cached = client.get(f"{library.base}/items/{item['id']}/file",
                        headers={"If-None-Match": etag})  # fmt: skip
    assert cached.status_code == 304
    thumb = library.file(item["id"], size="160")
    assert thumb.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(thumb.content)) as made:
        assert made.size == (160, 80)
    path = storage.thumb_path(vault_path(client, library), item["sha256"], 160)
    assert path.is_file()  # made once, then served from disk
    assert library.file(item["id"], size="999").status_code == 422


# --- references -----------------------------------------------------------------------------------


def test_references_follow_bodies_covers_and_galleries(library: Library) -> None:
    api = library.api
    portrait = library.uploaded(png(color="blue"))
    banner = library.uploaded(png(color="green"))
    ilsa = api.make("misc", "Ilsa", body=doc(image(portrait["id"], alt="Ilsa at sea")))
    assert library.refs(portrait["id"]) == [(ilsa["id"], "body")]
    # The cover is checked: an unknown item is refused.
    refused = api.patch(
        api.get(ilsa["id"]).json(), cover_media_id="01999999-0000-7000-8000-000000000000"
    )
    assert invalid(refused) == ["cover_media_id"]
    covered = api.patch(api.get(ilsa["id"]).json(), cover_media_id=banner["id"])
    assert covered.status_code == 200, covered.json()
    assert library.refs(banner["id"]) == [(ilsa["id"], "cover")]
    # Another module's context isn't touched by the entity's saves.
    vault = library.client.app.state.vaults.open(api.vault)  # type: ignore[attr-defined]
    with vault.write_sessions.begin() as session:
        media_api.reference(session, banner["id"], ilsa["id"], "map")
    # Taking the image out of the body drops that reference; undo brings it back.
    cleared = api.patch(api.get(ilsa["id"]).json(), body=doc())
    assert cleared.status_code == 200, cleared.json()
    assert library.refs(portrait["id"]) == []
    assert sorted(library.refs(banner["id"])) == [(ilsa["id"], "cover"), (ilsa["id"], "map")]
    library.undo_last()
    assert library.refs(portrait["id"]) == [(ilsa["id"], "body")]
    # A gallery item, then out of the gallery.
    gallery_url = f"{library.base}/entities/{ilsa['id']}/gallery"
    added = library.client.post(gallery_url, json={"media_id": portrait["id"], "caption": "Young"},
                                headers=HEADERS)  # fmt: skip
    assert added.status_code == 201, added.json()
    assert sorted(library.refs(portrait["id"])) == [(ilsa["id"], "body"), (ilsa["id"], "gallery")]
    gallery = library.client.get(gallery_url).json()
    assert [i["caption"] for i in gallery["items"]] == ["Young"]
    removed = library.client.delete(f"{library.base}/gallery/{added.json()['id']}",
                                    headers=HEADERS)  # fmt: skip
    assert removed.status_code == 204
    assert library.refs(portrait["id"]) == [(ilsa["id"], "body")]
    # The library lists by use.
    unused = library.uploaded(png(color="white"))
    listed = library.client.get(f"{library.base}/items", params={"unused": True}).json()
    assert [i["id"] for i in listed["items"]] == [unused["id"]]
    used_by = library.client.get(f"{library.base}/items", params={"entity": ilsa["id"]}).json()
    assert {i["id"] for i in used_by["items"]} == {portrait["id"], banner["id"]}


def test_the_media_field_type() -> None:
    one = FieldDef(key="portrait", label="Portrait", type="media")
    many = FieldDef(key="plates", label="Plates", type="media", multiple=True)
    assert MEDIA_FIELD_TYPE.validate is not None
    assert MEDIA_FIELD_TYPE.validate("01abc", one) == "01abc"
    assert MEDIA_FIELD_TYPE.validate(["01a", "01b"], many) == ["01a", "01b"]
    for bad, field in (("../x", one), (["01a", 3], many), ("01a", many)):
        with pytest.raises(ValueError, match="media item"):
            MEDIA_FIELD_TYPE.validate(bad, field)


# --- reader visibility ----------------------------------------------------------------------------


def test_readers_see_items_only_through_visible_contexts(library: Library) -> None:
    api = library.api
    secret = library.uploaded(png(color="black"))
    shown = library.uploaded(png(color="yellow"))
    unused = library.uploaded(png(color="purple"))
    api.make("misc", "Diary", body=doc(block("private", image(secret["id"])), image(shown["id"])))
    for hidden in (secret, unused):
        assert library.get(hidden["id"], as_reader=True).status_code == 404
        assert library.file(hidden["id"], as_reader=True).status_code == 404
    assert library.get(shown["id"], as_reader=True).status_code == 200
    assert library.file(shown["id"], as_reader=True).status_code == 200
    listed = library.client.get(f"{library.base}/items", params={"as_reader": True}).json()
    assert [i["id"] for i in listed["items"]] == [shown["id"]]
    # A private entity's images are private too.
    hidden_page = api.make("misc", "Hidden", visibility="private", body=doc(image(unused["id"])))
    assert library.get(unused["id"], as_reader=True).status_code == 404
    gallery = library.client.get(f"{library.base}/entities/{hidden_page['id']}/gallery",
                                 params={"as_reader": True})  # fmt: skip
    assert gallery.status_code == 404


# --- collection -----------------------------------------------------------------------------------


def test_unused_items_are_trashed_then_purged(client: TestClient, library: Library) -> None:
    used = library.uploaded(png(color="orange"))
    unused = library.uploaded(png(color="gray"))
    library.api.make("misc", "Page", body=doc(image(used["id"])))
    manager = client.app.state.vaults  # type: ignore[attr-defined]
    vault = manager.open(library.api.vault)
    registry = client.app.state.registry  # type: ignore[attr-defined]
    day0 = datetime.now(UTC)

    def run(now: datetime) -> dict[str, int]:
        with vault.write_sessions.begin() as session:
            return collect(VaultContext(vault, session, registry), now)

    assert run(day0)["marked"] == 1
    assert run(day0 + timedelta(days=29))["trashed"] == 0
    assert run(day0 + timedelta(days=31))["trashed"] == 1
    assert library.get(unused["id"]).json()["deleted_at"] is not None
    assert library.get(used["id"]).json()["deleted_at"] is None
    path = storage.file_path(vault.info.path, unused["sha256"])
    assert path.is_file()  # in the trash, the file is kept
    assert run(day0 + timedelta(days=60))["purged"] == 0
    assert run(day0 + timedelta(days=62))["purged"] == 1
    assert library.get(unused["id"]).status_code == 404
    assert not path.exists()
    assert storage.file_path(vault.info.path, used["sha256"]).is_file()


def test_vault_check_reports_missing_files(client: TestClient, library: Library) -> None:
    item = library.uploaded(png(color="teal"))
    library.api.make("misc", "Page", body=doc(image(item["id"])))
    manager = client.app.state.vaults  # type: ignore[attr-defined]
    assert check_vault(manager, library.api.vault).problems == ()
    storage.file_path(manager.open(library.api.vault).info.path, item["sha256"]).unlink()
    problems = check_vault(manager, library.api.vault).problems
    assert [(p.check, p.code) for p in problems] == [("media", "missing_file")]


def test_publishing_copies_only_what_readers_see(
    client: TestClient, library: Library, tmp_path: Path
) -> None:
    secret = library.uploaded(png(color="black"))
    shown = library.uploaded(png(500, 300, color="yellow"))
    seal = library.uploaded(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "seal.svg")
    library.api.make("misc", "Diary", body=doc(block("private", image(secret["id"])),
                                               image(shown["id"]), image(seal["id"])))  # fmt: skip
    vault = client.app.state.vaults.open(library.api.vault)  # type: ignore[attr-defined]
    registry = client.app.state.registry  # type: ignore[attr-defined]
    target = tmp_path / "published"
    with vault.sessions() as session:
        copied = copy_visible_media(VaultContext(vault, session, registry), target)
    assert copied == sorted([shown["id"], seal["id"]])
    assert storage.file_path(target, shown["sha256"]).is_file()
    assert storage.thumb_path(target, shown["sha256"], 160).is_file()
    # A reader-side server may not be able to write the sanitized copy: it is made in advance.
    assert storage.safe_svg_path(target, seal["sha256"]).is_file()
    assert not storage.file_path(target, secret["sha256"]).exists()
