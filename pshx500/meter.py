"""Level meter (after docs/level_meter.md) with ballistics:
- Bar: instant attack on a new peak, slow release (no flickering to 0).
- Peak hold: holds the maximum, falls slowly after the hold time, but NEVER below
  the current bar level.
- OVER: latched (visible briefly after full scale).
The input signal is measured (before gain), as in the Windows application.
process() runs in the USB thread, read() in the GUI thread -> protected by a lock.
"""
from __future__ import annotations

import math
import threading
import time

import numpy as np

from . import formats as F

FLOOR = -120.0


class LevelMeter:
    def __init__(self, container_bytes: int, channels: int = F.CHANNELS,
                 release_db_per_s: float = 26.0, hold_s: float = 1.5,
                 hold_decay_db_per_s: float = 12.0, over_hold_s: float = 1.2):
        self.container_bytes = container_bytes
        self.channels = channels
        self.full = float(1 << (container_bytes * 8 - 1))
        self._dtype = np.dtype("<i2") if container_bytes == 2 else np.dtype("<i4")
        self.release = release_db_per_s
        self.hold_s = hold_s
        self.hold_decay = hold_decay_db_per_s
        self.over_hold_s = over_hold_s
        self._lock = threading.Lock()
        self._pending = [FLOOR] * channels      # max. block peak since the last read()
        self._over_seen = [False] * channels
        self._level = [FLOOR] * channels
        self._hold = [FLOOR] * channels
        self._hold_t = [0.0] * channels
        self._over_t = [-1e9] * channels
        self._last = time.monotonic()

    def process(self, raw: bytes) -> None:
        step = self.container_bytes * self.channels
        n = (len(raw) // step) * step
        if n == 0:
            return
        arr = np.frombuffer(raw[:n], dtype=self._dtype).reshape(-1, self.channels)
        with self._lock:
            for ch in range(self.channels):
                col = arr[:, ch].astype(np.int64)
                peak = int(np.abs(col).max()) if col.size else 0
                db = 20.0 * math.log10(peak / self.full) if peak > 0 else FLOOR
                if db > self._pending[ch]:
                    self._pending[ch] = db
                if db >= 0.0:
                    self._over_seen[ch] = True

    def read(self):
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        out = []
        with self._lock:
            for ch in range(self.channels):
                pk = self._pending[ch]
                self._pending[ch] = FLOOR
                if pk >= self._level[ch]:
                    self._level[ch] = pk                      # attack: instant
                else:
                    self._level[ch] = max(pk, self._level[ch] - self.release * dt)  # release
                lvl = self._level[ch]
                if lvl >= self._hold[ch]:
                    self._hold[ch] = lvl
                    self._hold_t[ch] = now
                elif now - self._hold_t[ch] > self.hold_s:
                    self._hold[ch] = max(lvl, self._hold[ch] - self.hold_decay * dt)
                if self._over_seen[ch]:
                    self._over_t[ch] = now
                    self._over_seen[ch] = False
                over = (now - self._over_t[ch]) < self.over_hold_s
                out.append({"peak_db": lvl, "hold_db": self._hold[ch], "over": over})
        return out

    def reset(self) -> None:
        with self._lock:
            self._pending = [FLOOR] * self.channels
            self._level = [FLOOR] * self.channels
            self._hold = [FLOOR] * self.channels
            self._over_seen = [False] * self.channels
