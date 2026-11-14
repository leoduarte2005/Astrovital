"""Ring buffer for CSI_WINDOW frames ordered by cycle_seq_first."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..ipc.protocol import CSILink, CSIWindowPayload, MissionMode


@dataclass(frozen=True)
class BufferedWindow:
    """Single CSI_WINDOW snapshot stored in chronological cycle order."""

    cycle_seq_first: int
    ts_us: int
    mode: MissionMode
    active_link_mask: int
    links: list[CSILink]
    quality_per_link: Optional[list[float]]
    decoded_cache: dict[tuple[int, int], np.ndarray] = field(default_factory=dict, repr=False, compare=False)


class WindowBuffer:
    """Fixed-capacity ring buffer keeping CSI windows sorted by ``cycle_seq_first``."""

    def __init__(self, maxlen: int = 32) -> None:
        if maxlen < 1:
            raise ValueError("maxlen must be >= 1")
        self.maxlen = maxlen
        self._keys: list[int] = []
        self._windows: list[BufferedWindow] = []

    def __len__(self) -> int:
        return len(self._windows)

    def clear(self) -> None:
        self._keys.clear()
        self._windows.clear()

    def push(self, payload: CSIWindowPayload, ts_us: int) -> None:
        """Insert or update a CSI window in ascending ``cycle_seq_first`` order."""
        item = BufferedWindow(
            cycle_seq_first=payload.cycle_seq_first,
            ts_us=ts_us,
            mode=payload.mode,
            active_link_mask=payload.active_link_mask,
            links=list(payload.links),
            quality_per_link=list(payload.quality_per_link) if payload.quality_per_link is not None else None,
        )
        seq = item.cycle_seq_first
        idx = bisect_left(self._keys, seq)

        if idx < len(self._keys) and self._keys[idx] == seq:
            self._windows[idx] = item
            return

        if len(self._windows) >= self.maxlen and idx == 0:
            # Older than everything currently retained when buffer is full.
            return

        self._keys.insert(idx, seq)
        self._windows.insert(idx, item)

        while len(self._windows) > self.maxlen:
            self._keys.pop(0)
            self._windows.pop(0)

    def latest(self, n: int = 10) -> list[BufferedWindow]:
        """Return up to ``n`` most recent windows in ascending ``cycle_seq_first`` order."""
        if n <= 0 or not self._windows:
            return []
        return list(self._windows[-n:])

    def estimate_sample_rate_hz(self, cycles_per_window: float = 5.0, default_fs_hz: float = 10.0) -> float:
        """Estimate effective cycle sampling rate (Hz) from buffered window timestamps."""
        if len(self._windows) < 2:
            return default_fs_hz

        span_us = self._windows[-1].ts_us - self._windows[0].ts_us
        if span_us <= 0:
            return default_fs_hz

        total_cycles = cycles_per_window * (len(self._windows) - 1)
        fs_hz = total_cycles / (span_us / 1_000_000.0)
        if fs_hz < 2.0 or fs_hz > 100.0:
            return default_fs_hz
        return float(fs_hz)
