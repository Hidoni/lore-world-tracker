"""The in-process maintenance scheduler (``persistence-and-migrations.md`` §2, §5): a daemon
thread that, every ``interval`` seconds while the app runs, calls
``VaultManager.run_scheduled_backups`` and ``VaultManager.run_scheduled_optimize`` (the daily
``PRAGMA optimize``). The app starts it in author mode only; a read-only server never writes."""

import logging
import threading

from lore.core.vaults.manager import VaultManager

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 600.0


class MaintenanceScheduler:
    def __init__(self, manager: VaultManager, interval: float = CHECK_INTERVAL_SECONDS) -> None:
        if manager.read_only:
            raise ValueError("a read-only server never runs scheduled maintenance")
        self.manager = manager
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lore-maintenance", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None

    def run_once(self) -> None:
        for task in (self.manager.run_scheduled_backups, self.manager.run_scheduled_optimize):
            try:
                task()
            except Exception:  # pragma: no cover - the tasks log their own failures
                logger.exception("scheduled maintenance task %s failed", task.__name__)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.run_once()
