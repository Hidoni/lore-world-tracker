"""Media files on disk (``docs/modules/media.md``, ``security.md`` §3).

- Files live at ``media/<sha256[0:2]>/<sha256>`` in the vault folder, named by their content and
  never by what the uploader called them. Writes go to a temporary file in the same folder and
  are renamed into place, so a file is either complete or absent.
- The type comes from the bytes (magic numbers), from an allowlist: images (png, jpeg, webp, gif,
  avif), documents (pdf, plain text, Markdown), SVG (shown inline only once sanitized) and fonts
  (woff2, woff, ttf, otf: writing systems' script fonts, #155), whose headers must be whole. A file
  whose bytes don't match the name's extension is still judged by its bytes; text files must be
  UTF-8 without NUL bytes.
- Raster images are decoded with libvips (pyvips), streaming, with the loader of their type; images
  above ``MAX_PIXELS`` are refused before decoding (the decompression-bomb guard), and their
  dimensions are recorded.
- Thumbnails (``THUMB_WIDTHS``) are WebP files in ``media/thumbs/<sha256>_<width>.webp``, made on
  first request and regenerable. Where the vault folder can't be written (a read-only server) the
  thumbnail is made in memory each time.
- Tiles (#162, deep zoom): a raster image's pyramid of ``TILE_SIZE`` px WebP tiles, level ``k``
  being the image shrunk ``2^k`` times, down to the level where it fits in one tile
  (``tile_levels``). The whole pyramid is made on the first tile's request (libvips ``dzsave``) in
  ``media/tiles/<sha256>/<k>/<x>_<y>.webp`` and is regenerable; a read-only server makes the
  requested tile alone, in memory. Clients tile images whose longer side is above
  ``TILED_SIDE`` (``tiled``).
- SVGs must be readable by the sanitizer (``lore.modules.media.svg``) to be stored. Their
  sanitized copy is cached the same way, in ``media/thumbs/<sha256>_safe<svg.VERSION>.svg``.
"""

import hashlib
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

import pyvips

from lore.modules.media import svg

MEDIA_DIR = "media"
THUMBS_DIR = "thumbs"
TILES_DIR = "tiles"
THUMB_WIDTHS = (160, 480, 1280)
# The decompression-bomb guard: images with more pixels than this are refused before decoding.
# libvips decodes them streaming, so memory stays small (a 16k by 16k map is 268 megapixels).
MAX_PIXELS = 400_000_000
TILE_SIZE = 256
# Images whose longer side is above this are shown as tiles: about the largest texture browsers
# and GPUs (mobile ones especially) take whole.
TILED_SIDE = 8192
_CHUNK = 1 << 20
_UNBOUNDED = 10_000_000  # libvips' largest coordinate: "no limit" for a thumbnail's height
# Files are content-addressed and read once per use: libvips' operation cache would only hold
# decoded images in memory.
pyvips.cache_set_max(0)

# Each raster type's libvips loader: an image is only ever decoded as the type its bytes say.
_LOADERS = {
    "image/png": "pngload_buffer",
    "image/jpeg": "jpegload_buffer",
    "image/webp": "webpload_buffer",
    "image/gif": "gifload_buffer",
    "image/avif": "heifload_buffer",
}
RASTER = frozenset(_LOADERS)
SVG = "image/svg+xml"
TEXT = frozenset({"text/plain", "text/markdown"})
FONTS = frozenset({"font/woff2", "font/woff", "font/ttf", "font/otf"})
ALLOWED = RASTER | TEXT | FONTS | frozenset({"application/pdf", SVG})
# What pages show as pictures: raster images and (sanitized) SVGs.
IMAGES = RASTER | frozenset({SVG})


class MediaRejectedError(ValueError):
    """An upload this module won't store (its message is shown to the uploader)."""


@dataclass(frozen=True)
class Sniffed:
    mime: str
    width: int | None = None
    height: int | None = None


# (prefix offset, prefix, mime): checked in order.
_SIGNATURES: tuple[tuple[int, bytes, str], ...] = (
    (0, b"\x89PNG\r\n\x1a\n", "image/png"),
    (0, b"\xff\xd8\xff", "image/jpeg"),
    (0, b"GIF87a", "image/gif"),
    (0, b"GIF89a", "image/gif"),
    (0, b"%PDF-", "application/pdf"),
    (4, b"ftypavif", "image/avif"),
    (4, b"ftypavis", "image/avif"),
    (0, b"wOF2", "font/woff2"),
    (0, b"wOFF", "font/woff"),
    (0, b"OTTO", "font/otf"),
    (0, b"\x00\x01\x00\x00", "font/ttf"),
    (0, b"true", "font/ttf"),
)
# A font's header: WOFF/WOFF2 have their length at bytes 8 to 12; an sfnt (ttf/otf) table directory
# is 12 bytes, then 16 per table (at most this many tables).
_FONT_HEADER = 12
_TABLE_RECORD = 16
_MAX_TABLES = 256


def _magic(head: bytes) -> str | None:
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    for offset, prefix, mime in _SIGNATURES:
        if head[offset : offset + len(prefix)] == prefix:
            return mime
    return None


def _text_kind(data: bytes, filename: str) -> str | None:
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    start = text.lstrip("﻿ \t\r\n")[:512].lower()
    if start.startswith("<svg") or (start.startswith("<?xml") and "<svg" in start):
        return SVG
    if filename.lower().endswith((".md", ".markdown")):
        return "text/markdown"
    if filename.lower().endswith(".svg"):
        return None  # SVG by name but not by content
    return "text/plain"


def sniff(data: bytes, filename: str) -> Sniffed:
    """The file's type from its bytes and, for raster images, its dimensions; raises
    ``MediaRejectedError`` for anything not on the allowlist or not decodable."""
    mime = _magic(data[:16]) or _text_kind(data, filename)
    if mime is None or mime not in ALLOWED:
        raise MediaRejectedError("This type of file isn't supported.")
    if mime == SVG:
        try:
            svg.sanitize(data)
        except svg.SvgRejectedError as error:
            raise MediaRejectedError(str(error)) from error
    if mime in FONTS:
        _check_font(data, mime)
    if mime not in RASTER:
        return Sniffed(mime)
    width, height = _decode(data, mime)
    return Sniffed(mime, width, height)


def _check_font(data: bytes, mime: str) -> None:
    """A font's header must be whole: a WOFF/WOFF2 file as long as it says, an sfnt (ttf/otf)
    file with its table directory. Browsers parse (and sanitize) the tables themselves."""
    bad = MediaRejectedError("This font file is damaged or incomplete.")
    if mime in ("font/woff", "font/woff2"):
        if len(data) < _FONT_HEADER or int.from_bytes(data[8:_FONT_HEADER]) != len(data):
            raise bad
        return
    tables = int.from_bytes(data[4:6]) if len(data) >= _FONT_HEADER else 0
    if not 0 < tables <= _MAX_TABLES or len(data) < _FONT_HEADER + _TABLE_RECORD * tables:
        raise bad


def _decode(data: bytes, mime: str) -> tuple[int, int]:
    """Decode the whole image (not only its header), refusing it before decoding when it has
    more pixels than ``MAX_PIXELS``."""
    try:
        image = pyvips.Operation.call(
            _LOADERS[mime], data, access="sequential", fail_on="truncated"
        )
        width, height = int(image.width), int(image.height)
        if width * height > MAX_PIXELS:
            raise MediaRejectedError("The image is too large (too many pixels).")
        image.avg()  # reads every pixel
    except pyvips.Error as error:
        raise MediaRejectedError("The image can't be read.") from error
    return width, height


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def media_root(vault_path: Path) -> Path:
    return vault_path / MEDIA_DIR


def file_path(vault_path: Path, sha256: str) -> Path:
    return media_root(vault_path) / sha256[:2] / sha256


def thumb_path(vault_path: Path, sha256: str, width: int) -> Path:
    return media_root(vault_path) / THUMBS_DIR / f"{sha256}_{width}.webp"


def safe_svg_path(vault_path: Path, sha256: str) -> Path:
    return media_root(vault_path) / THUMBS_DIR / f"{sha256}_safe{svg.VERSION}.svg"


def _write_atomically(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        Path(temporary).replace(target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def store(vault_path: Path, sha256: str, data: bytes) -> None:
    """Put the bytes in place (a file already there with this hash is kept)."""
    target = file_path(vault_path, sha256)
    if not target.is_file():
        _write_atomically(target, data)


def tiles_path(vault_path: Path, sha256: str) -> Path:
    return media_root(vault_path) / TILES_DIR / sha256


def tile_path(vault_path: Path, sha256: str, level: int, x: int, y: int) -> Path:
    return tiles_path(vault_path, sha256) / str(level) / f"{x}_{y}.webp"


def remove(vault_path: Path, sha256: str) -> None:
    """Delete the file, its thumbnails and its tiles (missing ones are fine)."""
    file_path(vault_path, sha256).unlink(missing_ok=True)
    for width in THUMB_WIDTHS:
        thumb_path(vault_path, sha256, width).unlink(missing_ok=True)
    for safe in (media_root(vault_path) / THUMBS_DIR).glob(f"{sha256}_safe*.svg"):
        safe.unlink(missing_ok=True)
    shutil.rmtree(tiles_path(vault_path, sha256), ignore_errors=True)


def _webp(image: pyvips.Image) -> bytes:
    return cast(bytes, image.webpsave_buffer(Q=82, effort=4))


def _render_thumbnail(source: Path, width: int) -> bytes:
    # The first frame of an animation, shrunk (never enlarged) to the width; orientation as
    # stored, like the recorded size.
    image = pyvips.Image.thumbnail(
        str(source), width, height=_UNBOUNDED, size="down", no_rotate=True
    )
    return _webp(image)


def thumbnail(vault_path: Path, sha256: str, width: int) -> tuple[Path | None, bytes | None]:
    """The thumbnail: its cached file, or (when the folder can't be written) its bytes."""
    cached = thumb_path(vault_path, sha256, width)
    if cached.is_file():
        return cached, None
    data = _render_thumbnail(file_path(vault_path, sha256), width)
    try:
        _write_atomically(cached, data)
    except OSError:
        return None, data
    return cached, None


def tiled(width: int | None, height: int | None) -> bool:
    """Whether clients show the image as tiles rather than whole (its longer side is above
    ``TILED_SIDE``)."""
    return width is not None and height is not None and max(width, height) > TILED_SIDE


def tile_levels(width: int, height: int) -> int:
    """The coarsest tile level: the image halved (rounding up) this many times fits in one tile.
    Level ``k`` is ``ceil(width / 2^k)`` by ``ceil(height / 2^k)`` pixels."""
    side, levels = max(width, height), 0
    while side > TILE_SIZE:
        side, levels = (side + 1) // 2, levels + 1
    return levels


def tile_count(width: int, height: int, level: int) -> tuple[int, int]:
    """How many tiles level ``level`` has across and down."""
    scale = 1 << level
    across, down = -(-width // scale), -(-height // scale)
    return -(-across // TILE_SIZE), -(-down // TILE_SIZE)


_tile_locks: dict[str, threading.Lock] = {}
_tile_locks_lock = threading.Lock()


def pyramid(vault_path: Path, sha256: str) -> None:
    """Make the image's whole tile pyramid (one pass of libvips ``dzsave``, whose levels count
    up from the one-tile level) into a temporary folder, then rename it into place."""
    with _tile_locks_lock:
        lock = _tile_locks.setdefault(sha256, threading.Lock())
    with lock:
        target = tiles_path(vault_path, sha256)
        if target.is_dir():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=target.parent, prefix=".tiles-"))
        try:
            image = pyvips.Image.new_from_file(
                str(file_path(vault_path, sha256)), access="sequential"
            )
            image.dzsave(
                str(work / "dz"), layout="dz", tile_size=TILE_SIZE, overlap=0,
                suffix=".webp[Q=82,effort=4]", depth="onetile",
            )  # fmt: skip
            built = work / "dz_files"
            levels = sorted(int(name.name) for name in built.iterdir() if name.name.isdigit())
            coarsest = levels[-1]
            pyramid = work / "pyramid"
            pyramid.mkdir()
            for level in levels:
                (built / str(level)).rename(pyramid / str(coarsest - level))
            pyramid.rename(target)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def _render_tile(source: Path, size: tuple[int, int], level: int, x: int, y: int) -> bytes:
    """One tile, made alone (from the whole image shrunk to its level)."""
    scale = 1 << level
    across, down = -(-size[0] // scale), -(-size[1] // scale)
    image = pyvips.Image.thumbnail(str(source), across, height=down, size="force", no_rotate=True)
    left, top = x * TILE_SIZE, y * TILE_SIZE
    tile = image.crop(left, top, min(TILE_SIZE, across - left), min(TILE_SIZE, down - top))
    return _webp(tile)


def tile(
    vault_path: Path, sha256: str, *, size: tuple[int, int], level: int, x: int, y: int
) -> tuple[Path | None, bytes | None]:
    """A tile of the raster image of ``size`` (the caller checks that it exists): its cached
    file, or (when the folder can't be written) its bytes. The first request makes the whole
    pyramid."""
    cached = tile_path(vault_path, sha256, level, x, y)
    if cached.is_file():
        return cached, None
    if not tiles_path(vault_path, sha256).is_dir():
        try:
            pyramid(vault_path, sha256)
        except OSError:
            return None, _render_tile(file_path(vault_path, sha256), size, level, x, y)
    return cached, None


def safe_svg(vault_path: Path, sha256: str) -> tuple[Path | None, bytes | None]:
    """The SVG as sanitized: its cached file, or (when the folder can't be written) its bytes;
    raises ``svg.SvgRejectedError`` for a stored file the sanitizer can't read (one stored before
    it existed)."""
    cached = safe_svg_path(vault_path, sha256)
    if cached.is_file():
        return cached, None
    data = svg.sanitize(file_path(vault_path, sha256).read_bytes())
    try:
        _write_atomically(cached, data)
    except OSError:
        return None, data
    return cached, None


def read_limited(stream: BinaryIO, limit: int) -> bytes:
    """Read at most ``limit`` bytes from an upload; raises ``MediaRejectedError`` beyond."""
    read = stream.read
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise MediaRejectedError(f"The file is larger than {limit // (1 << 20)} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = [
    "ALLOWED",
    "IMAGES",
    "RASTER",
    "SVG",
    "THUMB_WIDTHS",
    "TILED_SIDE",
    "TILE_SIZE",
    "MediaRejectedError",
    "Sniffed",
    "digest",
    "file_path",
    "media_root",
    "pyramid",
    "read_limited",
    "remove",
    "safe_svg",
    "safe_svg_path",
    "sniff",
    "store",
    "thumbnail",
    "tile",
    "tile_count",
    "tile_levels",
    "tile_path",
    "tiled",
    "tiles_path",
]
