"""Upgraders of stored rich-text documents (``data-model.md`` §10): ``UPGRADERS[n]`` turns a
version-``n`` document into version ``n + 1``. Version 1 is current, so there are none yet."""

from collections.abc import Callable

from lore.core.richtext import SCHEMA_VERSION
from lore.core.richtext.handlers import Node

UPGRADERS: dict[int, Callable[[Node], Node]] = {}


def upgrade(doc: Node, from_version: int) -> Node:
    """The document at ``SCHEMA_VERSION``."""
    if from_version > SCHEMA_VERSION:
        raise ValueError(f"rich-text version {from_version} is newer than this app")
    for version in range(from_version, SCHEMA_VERSION):
        doc = UPGRADERS[version](doc)
    return doc
