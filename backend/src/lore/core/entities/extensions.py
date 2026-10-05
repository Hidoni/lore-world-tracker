"""Hooks the entity service calls so kinds and modules can attach their own data
(``docs/architecture/modules.md`` §2.1).

- A ``KindExtension`` owns a kind's ``ext`` data (the extension tables of dimensions, timelines,
  calendars, events in M3+): the service hands it the ``ext`` object of a create/patch, inside the
  request's transaction, and asks it for the ``ext`` of a read. Optional hooks run when an
  entity of the kind is trashed or restored, before it is purged (ahead of the purge checks, so
  it can remove records it owns, e.g. a dimension's prime timeline), and when an undo is vetted.
- A ``PurgeHook`` runs before an entity is permanently deleted, so records depending on it can be
  fixed (e.g. anchor freezing in M3, ``time-model.md`` §7.3). Hooks of **every** module run, also
  disabled ones: their data is kept while disabled and must stay consistent.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from lore.core.entities.models import Entity

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext


@dataclass(frozen=True)
class KindExtension:
    kind: str
    # (context, entity, ext, creating): validate and store. Called on every create (``ext`` may
    # be None) and on a patch that sends ``ext``. Raise ``InvalidInputError`` for bad data.
    write: Callable[[VaultContext, Entity, dict[str, Any] | None, bool], None]
    # (context, entity) -> the ``ext`` object of a read.
    read: Callable[[VaultContext, Entity], dict[str, Any] | None]
    # (context, entity, sent): after a PATCH applied its members (``sent``: the member names);
    # may refuse with a ``LoreError`` or update records that follow the entity.
    update: Callable[[VaultContext, Entity, frozenset[str]], None] | None = None
    # (context, entity, trashing): before the entity is trashed (True) or restored (False); may
    # refuse with a ``LoreError``. Only called when the trash state actually changes.
    trash: Callable[[VaultContext, Entity, bool], None] | None = None
    # (context, entity): before the purge checks and purge hooks; deletes the extension rows.
    purge: Callable[[VaultContext, Entity], None] | None = None
    # (context, entity) -> rules the stored entity breaks (vetting an undo).
    stored_problems: Callable[[VaultContext, Entity], list[str]] | None = None


type PurgeHook = Callable[[VaultContext, Entity], None]

CORE_PURGE_HOOKS: tuple[PurgeHook, ...] = ()  # anchor freezing: M3
