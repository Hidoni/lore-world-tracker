"""Media files on disk (``docs/modules/media.md``, ``security.md`` §3).

- Files live at ``media/<sha256[0:2]>/<sha256>`` in the vault folder, named by their content and
  never by what the uploader called them. Writes go to a temporary file in the same folder and
  are renamed into place, so a file is either complete or absent.
- The type comes from the bytes (magic numbers), from an allowlist: images (png, jpeg, webp, gif,
  avif), documents (pdf, plain text, Markdown), SVG (shown inline only once sanitized) and fonts
  (woff2, woff, ttf, otf: writing systems' script fonts, #155), whose headers must be whole. A file
  whose bytes don't match the name's extension is still judged by its bytes; text files must be
  UTF-8 without NUL bytes.
- Raster images are decoded with Pillow, which refuses images above ``MAX_PIXELS`` (the
  decompression-bomb guard), and their dimensions are recorded.
- Thumbnails (``THUMB_WIDTHS``) are WebP files in ``media/thumbs/<sha256>_<width>.webp``, made on
  first request and regenerable. Where the vault folder can't be written (a read-only server) the
  thumbnail is made in memory each time.
- SVGs must be readable by the sanitizer (``lore.modules.media.svg``) to be stored. Their
  sanitized copy is cached the same way, in ``media/thumbs/<sha256>_safe<svg.VERSION>.svg``.
"""

import hashlib
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

from lore.modules.media import svg

MEDIA_DIR = "media"
THUMBS_DIR = "thumbs"
THUMB_WIDTHS = (160, 480, 1280)
# The decompression-bomb guard: Pillow refuses to decode images with more pixels than this.
MAX_PIXELS = 50_000_000
_CHUNK = 1 << 20
# Pillow's own guard as a backstop (it raises at twice this); sizes are checked before decoding.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

RASTER = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"})
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
    width, height = _decode(data)
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


def _decode(data: bytes) -> tuple[int, int]:
    """Decode the whole image (not only its header), refusing it before decoding when it has
    more pixels than ``MAX_PIXELS``."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise MediaRejectedError("The image is too large (too many pixels).")
            image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise MediaRejectedError("The image is too large (too many pixels).") from error
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
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


def remove(vault_path: Path, sha256: str) -> None:
    """Delete the file and its thumbnails (missing ones are fine)."""
    file_path(vault_path, sha256).unlink(missing_ok=True)
    for width in THUMB_WIDTHS:
        thumb_path(vault_path, sha256, width).unlink(missing_ok=True)
    for safe in (media_root(vault_path) / THUMBS_DIR).glob(f"{sha256}_safe*.svg"):
        safe.unlink(missing_ok=True)


def _render_thumbnail(source: Path, width: int) -> bytes:
    with Image.open(source) as image:
        image.seek(0)  # the first frame of an animation
        frame = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
        if frame.width > width:
            height = max(1, round(frame.height * width / frame.width))
            frame = frame.resize((width, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        frame.save(out, "WEBP", quality=82, method=4)
        return out.getvalue()


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
    "MediaRejectedError",
    "Sniffed",
    "digest",
    "file_path",
    "media_root",
    "read_limited",
    "remove",
    "safe_svg",
    "safe_svg_path",
    "sniff",
    "store",
    "thumbnail",
]
