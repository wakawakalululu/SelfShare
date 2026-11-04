"""Continuous sync watcher: debounce filesystem events, then run a sync pass."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable, Optional

POLL_INTERVAL = 5.0      # seconds between cheap stat scans
DEBOUNCE = 2.0           # settle time after the last detected change


class Watcher:
    """Portable polling watcher.

    A polling scan is used instead of OS notifications because it behaves
    identically on Windows, SMB shares, network drives and Linux, and the stat
    scan is cheap enough for typical document folders. Change detection uses
    (size, mtime) so no hashing is done while idle.
    """

    def __init__(self, syncer_factory: Callable[[], object], folder: str,
                 interval: float = POLL_INTERVAL, debounce: float = DEBOUNCE,
                 log: Optional[Callable[[str], None]] = None,
                 post_sync: Optional[Callable[[], None]] = None):
        self.syncer_factory = syncer_factory
        self.folder = folder
        self.interval = interval
        self.debounce = debounce
        self._log = log or (lambda m: None)
        self._post_sync = post_sync
        self._stop = threading.Event()
        self._last_snapshot: Optional[dict] = None
        self._pending_since: Optional[float] = None
        self.state = "starting"

    def stop(self) -> None:
        self._stop.set()

    def _snapshot(self) -> dict:
        from .util import stat_sig_map
        from .sync import STATE_DIR

        snap = stat_sig_map(self.folder)
        return {k: v for k, v in snap.items() if not k.startswith(STATE_DIR + "/")}

    def run_forever(self, sync_interval: float = 0.0) -> None:
        self._log("监视已启动: %s (轮询 %.1fs, 静默 %.1fs)" % (self.folder, self.interval, self.debounce))
        self._last_snapshot = self._snapshot()
        last_full_sync = time.time()
        try:
            while not self._stop.is_set():
                self._stop.wait(self.interval)
                if self._stop.is_set():
                    break
                try:
                    current = self._snapshot()
                except OSError as exc:
                    self._log("扫描失败: %s" % exc)
                    continue
                if current != self._last_snapshot:
                    self._last_snapshot = current
                    self._pending_since = time.time()
                    self.state = "pending"
                if self._pending_since and (time.time() - self._pending_since) >= self.debounce:
                    self._pending_since = None
                    self._run_once("本地变更")
                    last_full_sync = time.time()
                elif sync_interval and (time.time() - last_full_sync) >= sync_interval:
                    self._run_once("定时巡检")
                    last_full_sync = time.time()
        finally:
            self._log("监视已停止")

    def _run_once(self, reason: str) -> bool:
        self.state = "syncing"
        try:
            with self.syncer_factory() as syncer:  # type: ignore[attr-defined]
                report = syncer.sync()
            self._log("[%s] %s" % (reason, report.summary()))
            for err in report.errors:
                self._log("  ! %s" % err)
            for rel in report.conflicts:
                self._log("  * 冲突已保留副本: %s" % rel)
            # refresh snapshot after sync so our own writes don't retrigger
            self._last_snapshot = self._snapshot()
            if self._post_sync:
                try:
                    self._post_sync()
                except Exception as exc:
                    self._log("  peer 广播刷新失败: %s" % exc)
            return True
        except Exception as exc:
            self._log("同步失败: %s" % exc)
            return False
        finally:
            self.state = "idle"
