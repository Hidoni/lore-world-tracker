"""SVG sanitization (``security.md`` §3): uploaded SVGs are shown inline only as rewritten here.

The file is parsed with defusedxml (no entity declarations, no external references) and copied
element by element into a new document that keeps only what draws:

- Elements come from an allowlist of shapes, text, paint servers, clipping, masking and filters.
  Scripts, ``foreignObject``, animations (which can rewrite attributes such as ``href``), and
  anything outside the SVG namespace are dropped with their content; a link (``a``) is replaced
  by its content. Comments, processing instructions and the doctype don't survive parsing.
- Attributes come from an allowlist too (no event handlers, no ``xml:base``). ``href`` (or
  ``xlink:href``, written back as ``href``) may only point inside the document (``#id``), or on
  ``image`` and ``feImage`` to an embedded raster image (``data:image/png;base64,…``).
- Paint and other values may only use ``url(#id)``. ``style`` attributes and ``<style>`` sheets
  that load anything (``@import``, ``url()`` to anything but ``#id``, ``expression``, bindings)
  are dropped whole.

The stored file is never changed: the media service sanitizes on serving (and caches the result
by ``VERSION``, so a stricter sanitizer reaches files already stored).
"""

import re
import xml.etree.ElementTree as ET

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

# Part of the cached file's name: bump it whenever the rules below change.
VERSION = 1

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_FILTER_PRIMITIVES = frozenset(
    f"fe{name}"
    for name in _words(
        "Blend ColorMatrix ComponentTransfer Composite ConvolveMatrix DiffuseLighting "
        "DisplacementMap DistantLight DropShadow Flood FuncA FuncB FuncG FuncR GaussianBlur "
        "Image Merge MergeNode Morphology Offset PointLight SpecularLighting SpotLight Tile "
        "Turbulence"
    )
)
ELEMENTS = _FILTER_PRIMITIVES | _words(
    "svg g defs symbol use switch title desc path rect circle ellipse line polyline polygon "
    "text tspan textPath linearGradient radialGradient stop pattern clipPath mask marker "
    "image filter style view"
)
# Replaced by their content.
_UNWRAPPED = frozenset({"a"})

ATTRIBUTES = _words(
    # core and structure
    "id class lang tabindex style version baseProfile viewBox preserveAspectRatio "
    "x y x1 y1 x2 y2 cx cy r rx ry fx fy fr width height d points pathLength transform "
    "requiredFeatures requiredExtensions systemLanguage refX refY markerWidth markerHeight "
    "markerUnits orient patternUnits patternContentUnits patternTransform gradientUnits "
    "gradientTransform spreadMethod offset clipPathUnits maskUnits maskContentUnits "
    "zoomAndPan media type title "
    # text
    "dx dy rotate textLength lengthAdjust startOffset method spacing side "
    # filters
    "filterUnits primitiveUnits in in2 result mode values operator k1 k2 k3 k4 order "
    "kernelMatrix divisor bias targetX targetY edgeMode preserveAlpha surfaceScale "
    "diffuseConstant specularConstant specularExponent kernelUnitLength scale "
    "xChannelSelector yChannelSelector stdDeviation radius azimuth elevation "
    "pointsAtX pointsAtY pointsAtZ limitingConeAngle z baseFrequency numOctaves seed "
    "stitchTiles tableValues slope intercept amplitude exponent "
    # presentation attributes
    "alignment-baseline baseline-shift clip clip-path clip-rule color "
    "color-interpolation color-interpolation-filters color-rendering cursor direction "
    "display dominant-baseline fill fill-opacity fill-rule filter flood-color "
    "flood-opacity font font-family font-size font-size-adjust font-stretch font-style "
    "font-variant font-weight glyph-orientation-horizontal glyph-orientation-vertical "
    "image-rendering kerning letter-spacing lighting-color marker marker-end marker-mid "
    "marker-start mask mask-type opacity overflow paint-order pointer-events "
    "shape-rendering stop-color stop-opacity stroke stroke-dasharray stroke-dashoffset "
    "stroke-linecap stroke-linejoin stroke-miterlimit stroke-opacity stroke-width "
    "text-anchor text-decoration text-rendering transform-origin unicode-bidi "
    "vector-effect visibility white-space word-spacing writing-mode"
)
_XML_ATTRIBUTES = frozenset({"space", "lang"})
_EMBEDDED_IMAGE = re.compile(r"data:image/(png|jpeg|gif|webp|avif);base64,[A-Za-z0-9+/=\s]*")
_URL_START = re.compile(r"url\s*\(", re.IGNORECASE)
_URL = re.compile(r"url\s*\(\s*(['\"]?)([^'\")]*)\1\s*\)", re.IGNORECASE)
_CSS_DANGER = re.compile(
    r"\\|@import|expression\s*\(|-moz-binding|behavior\s*:|image-set\s*\(|src\s*\(",
    re.IGNORECASE,
)


class SvgRejectedError(ValueError):
    """An SVG that can't be read (not XML, entity declarations, or not an ``svg`` root)."""


def _local(name: str) -> tuple[str | None, str]:
    """``{namespace}local`` as (namespace, local); ``None`` for no namespace."""
    if name.startswith("{"):
        namespace, _, local = name[1:].partition("}")
        return namespace, local
    return None, name


def _only_local_urls(value: str) -> bool:
    """Whether every ``url()`` in the value points inside the document (CSS escapes, which could
    spell ``url`` or ``@import`` in disguise, aren't accepted at all)."""
    if _CSS_DANGER.search(value):
        return False
    for start in _URL_START.finditer(value):
        found = _URL.match(value, start.start())
        if found is None or not found.group(2).strip().startswith("#"):
            return False
    return True


def _href(tag: str, value: str) -> str | None:
    value = value.strip()
    if value.startswith("#"):
        return value
    if tag in {"image", "feImage"} and _EMBEDDED_IMAGE.fullmatch(value):
        return value
    return None


def _attributes(tag: str, source: ET.Element) -> dict[str, str]:
    kept: dict[str, str] = {}
    for name, value in source.attrib.items():
        namespace, local = _local(name)
        if (namespace is None and local == "href") or (namespace == XLINK_NS and local == "href"):
            href = _href(tag, value)
            if href is not None:
                kept["href"] = href
        elif namespace == XML_NS and local in _XML_ATTRIBUTES:
            kept[name] = value
        elif namespace is None and local in ATTRIBUTES and _only_local_urls(value):
            kept[local] = value
    return kept


def _copy(source: ET.Element, target: ET.Element) -> None:
    """Copy the allowed children of ``source`` (and its text) into ``target``."""
    target.text = source.text
    for child in source:
        namespace, tag = _local(child.tag) if isinstance(child.tag, str) else (None, "")
        in_svg = namespace in (None, SVG_NS)
        if in_svg and tag in _UNWRAPPED:
            # Its content takes its place.
            holder = ET.Element("holder")
            _copy(child, holder)
            _append_text(target, holder.text)
            for grandchild in holder:
                target.append(grandchild)
            _append_text(target, child.tail)
            continue
        if not in_svg or tag not in ELEMENTS:
            _append_text(target, child.tail)
            continue
        if tag == "style" and (len(child) or not _only_local_urls(child.text or "")):
            _append_text(target, child.tail)
            continue
        copied = ET.SubElement(target, tag, _attributes(tag, child))
        if tag == "style":
            copied.text = child.text
        else:
            _copy(child, copied)
        copied.tail = child.tail


def _append_text(target: ET.Element, text: str | None) -> None:
    """Text after the last child (or inside, when there is none)."""
    if not text:
        return
    if len(target):
        last = target[-1]
        last.tail = (last.tail or "") + text
    else:
        target.text = (target.text or "") + text


def sanitize(data: bytes) -> bytes:
    """The SVG rewritten to what is safe to show inline (UTF-8, no XML declaration); raises
    ``SvgRejectedError`` for a file that can't be read as an SVG."""
    try:
        root = fromstring(data)
    except (ET.ParseError, DefusedXmlException, ValueError) as error:
        raise SvgRejectedError("The SVG can't be read.") from error
    namespace, tag = _local(root.tag)
    if namespace not in (None, SVG_NS) or tag != "svg":
        raise SvgRejectedError("The SVG can't be read.")
    # Unqualified names in the output, the SVG namespace declared once on the root.
    out = ET.Element("svg", {"xmlns": SVG_NS, **_attributes("svg", root)})
    _copy(root, out)
    serialized: bytes = ET.tostring(out, encoding="utf-8", xml_declaration=False)
    return serialized


__all__ = ["ATTRIBUTES", "ELEMENTS", "VERSION", "SvgRejectedError", "sanitize"]
