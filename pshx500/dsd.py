"""DSD->PCM decoding (streaming) for the level meter and monitoring.

Raw 1-bit DSD cannot be turned into PCM by block averaging; that folds the steep
DSD noise shaping into the audio band (noise). It needs a multi-stage decimation
with windowed sinc low-pass filters. For continuous streaming each stage keeps its
filter and phase state across chunk boundaries (overlap-save), so there are no
clicks.

The USB stream is MSB first per byte, 2 channels interleaved (16-bit container per
channel).
"""
from __future__ import annotations

import numpy as np

from . import formats as F


def _lowpass(cutoff_norm: float, ntaps: int) -> np.ndarray:
    n = np.arange(ntaps) - (ntaps - 1) / 2
    h = 2 * cutoff_norm * np.sinc(2 * cutoff_norm * n) * np.hamming(ntaps)
    return (h / h.sum()).astype(np.float32)


def _factorize(total: int) -> list[int]:
    """Split the total decimation into stages <= 8 (for manageable filter lengths)."""
    stages, f = [], total
    for d in (8, 7, 5, 4, 3, 2):
        while f % d == 0 and f > 1:
            stages.append(d)
            f //= d
    if f != 1:
        stages.append(f)
    return stages


class _Stage:
    def __init__(self, factor: int):
        self.factor = factor
        self.h = _lowpass(0.45 / factor, 8 * factor + 1)
        self._prev = np.zeros(len(self.h) - 1, dtype=np.float32)
        self._count = 0  # number of input samples processed so far (for the phase)

    def process(self, x: np.ndarray) -> np.ndarray:
        full = np.concatenate((self._prev, x))
        # 'valid' convolution: y[i] is the filtered input at position i
        y = np.convolve(full, self.h, mode="valid")  # len == len(x)
        if len(y) == 0:
            return y
        start = (-self._count) % self.factor
        out = y[start::self.factor]
        self._count += len(x)
        self._prev = full[-(len(self.h) - 1):]
        return out


class DsdPcmDecoder:
    """Converts DSD USB chunks continuously into PCM (float32, stereo)."""

    def __init__(self, dsd_rate: int, out_rate: int = 44100, channels: int = F.CHANNELS):
        if dsd_rate % out_rate != 0:
            raise ValueError("out_rate must divide dsd_rate evenly")
        self.channels = channels
        self.out_rate = out_rate
        factors = _factorize(dsd_rate // out_rate)
        self._stages = [[_Stage(f) for f in factors] for _ in range(channels)]

    def feed(self, raw: bytes) -> np.ndarray:
        """Returns (M, channels) float32 in [-1, 1] (may be empty)."""
        step = F.DSD_CONTAINER_BYTES * self.channels
        n = (len(raw) // step) * step
        if n == 0:
            return np.empty((0, self.channels), dtype=np.float32)
        frames = np.frombuffer(raw[:n], dtype=np.uint8).reshape(-1, step)
        cb = F.DSD_CONTAINER_BYTES
        cols = []
        for ch in range(self.channels):
            chan = frames[:, ch * cb:(ch + 1) * cb].reshape(-1)
            bits = np.unpackbits(chan, bitorder="big")           # MSB first
            sig = bits.astype(np.float32) * 2.0 - 1.0            # +-1
            for st in self._stages[ch]:
                sig = st.process(sig)
            cols.append(sig)
        m = min(len(c) for c in cols)
        if m == 0:
            return np.empty((0, self.channels), dtype=np.float32)
        return np.stack([c[:m] for c in cols], axis=1)

    def feed_int32_bytes(self, raw: bytes) -> bytes:
        """Like feed(), but as interleaved int32 LE bytes (for a LevelMeter with 4-byte container)."""
        pcm = self.feed(raw)
        if pcm.size == 0:
            return b""
        i32 = np.clip(pcm * (2 ** 31 - 1), -(2 ** 31), 2 ** 31 - 1).astype("<i4")
        return i32.tobytes()
