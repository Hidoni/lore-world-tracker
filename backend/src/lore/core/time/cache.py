"""Process-wide LRU caches: compiled calendars (``time-model.md`` §7.2, ``chronology-engine.md``
§4) and timeline windows (``lore.core.time.window``).

Keys are ``(vault id, calendar id, definition revision, digest of the definition and the compile
context)``: the context holds the resolved anchors, the base unit and ``D``, so any change to them
misses (and so does another definition under the same revision, as a proposal's rolled-back dry
run leaves behind). A vault's entries are dropped when its engine closes (a restore can bring
back old revisions).
"""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

from lore.chronology.calendar import CompiledCalendar

type CacheKey = tuple[str, str, int, str]

MAX_CALENDARS = 128


class CompiledCalendars:
    def __init__(self, size: int = MAX_CALENDARS) -> None:
        self.size = size
        self.hits = 0
        self.misses = 0
        self._entries: OrderedDict[CacheKey, CompiledCalendar] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: CacheKey, build: Callable[[], CompiledCalendar]) -> CompiledCalendar:
        with self._lock:
            found = self._entries.get(key)
            if found is not None:
                self._entries.move_to_end(key)
                self.hits += 1
                return found
            self.misses += 1
        compiled = build()  # outside the lock: compiling may take a while
        with self._lock:
            self._entries[key] = compiled
            self._entries.move_to_end(key)
            while len(self._entries) > self.size:
                self._entries.popitem(last=False)
        return compiled

    def forget_vault(self, vault_id: str) -> None:
        with self._lock:
            for key in [k for k in self._entries if k[0] == vault_id]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = self.misses = 0


CALENDARS = CompiledCalendars()


MAX_WINDOWS = 64


class WindowCache:
    """Computed timeline windows (decided 2026-10-07: zoomed-out windows over 100k events take a
    few hundred ms cold). Keys start with ``(vault id, write generation)``: any committed write to
    the vault (``OpenVault.writes``) makes every older entry unreachable, and they age out."""

    def __init__(self, size: int = MAX_WINDOWS) -> None:
        self.size = size
        self.hits = 0
        self.misses = 0
        self._entries: OrderedDict[tuple[str, int, Hashable], Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, vault_id: str, generation: int, key: Hashable, build: Callable[[], Any]) -> Any:
        full = (vault_id, generation, key)
        with self._lock:
            if full in self._entries:
                self._entries.move_to_end(full)
                self.hits += 1
                return self._entries[full]
            self.misses += 1
        value = build()
        with self._lock:
            self._entries[full] = value
            while len(self._entries) > self.size:
                self._entries.popitem(last=False)
        return value

    def forget_vault(self, vault_id: str) -> None:
        with self._lock:
            for key in [k for k in self._entries if k[0] == vault_id]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = self.misses = 0


WINDOWS = WindowCache()
