"""Live monitoring with drift compensation.

The USB capture clock (the PS-HX500's ADC) and the clock of the output device run
independently and drift by a few ppm. Instead of dropping whole sample blocks
(audible clicks), we use an asynchronous sample rate converter (ASRC): a phase
accumulator reads the input buffer with a variable step and interpolates
linearly. A P controller varies the step (resampling ratio) by tiny amounts to
hold the buffer fill level at a target value (latency). The correction is spread
continuously over many samples and is inaudible.

sounddevice is optional; if it is missing, the constructor raises and the caller
disables monitoring.
"""
from __future__ import annotations

import threading

import numpy as np

from . import formats as F

_MAX_ADJUST = 0.005    # max. +/-0.5 % rate correction (actually needed: ppm)
_KP = 0.10             # controller gain (relative to the target fill level)
_SMOOTH = 0.05         # smoothing of the step per callback


class MonitorPlayer:
    def __init__(self, rate: int, container_bytes: int, device=None, latency_ms: int = 120,
                 blocksize: int = 2048):
        import sounddevice as sd  # lazy: only when monitoring is active
        self._sd = sd
        self.rate = rate
        self.channels = F.CHANNELS
        self.device = device
        self._blocksize = blocksize
        self._scale = 32768.0 if container_bytes == 2 else 2147483648.0
        self._indtype = "<i2" if container_bytes == 2 else "<i4"
        self._framesize = container_bytes * self.channels

        self._lock = threading.Lock()
        self._in = np.zeros((0, self.channels), dtype=np.float32)
        self._pos = 0.0
        self._step = 1.0
        self._primed = False
        self.target = rate * latency_ms / 1000.0
        self.maxbuf = rate * 1.0
        self._stream = None
        # Statistics (for diagnosis)
        self.underruns = 0        # our ring buffer was empty
        self.out_underflow = 0    # PortAudio reported an output underflow (callback too late)
        self.fill_min = 1e18
        self.fill_max = 0.0

    def start(self) -> None:
        # Larger device buffer + larger blocks -> tolerant of GIL/scheduling jitter.
        self._stream = self._sd.OutputStream(
            samplerate=self.rate, channels=self.channels, dtype="float32",
            device=self.device, blocksize=self._blocksize, latency="high",
            callback=self._cb)
        self._stream.start()

    def feed(self, raw: bytes) -> None:
        n = (len(raw) // self._framesize) * self._framesize
        if n == 0:
            return
        a = (np.frombuffer(raw[:n], dtype=self._indtype)
             .astype(np.float32).reshape(-1, self.channels) / self._scale)
        with self._lock:
            self._in = a if self._in.size == 0 else np.concatenate((self._in, a))
            if len(self._in) > self.maxbuf:                 # hard emergency brake (rare)
                self._in = self._in[len(self._in) - int(self.maxbuf):]

    def _cb(self, outdata, frames, _time, status) -> None:
        if status:
            self.out_underflow += 1
        with self._lock:
            avail = len(self._in)
            if not self._primed:
                if avail < self.target:
                    outdata[:] = 0.0
                    return
                self._primed = True
            self.fill_min = min(self.fill_min, avail)
            self.fill_max = max(self.fill_max, avail)

            # P controller: vary the step (= input per output) around 1.0
            err = (avail - self.target) / self.target
            target_step = 1.0 + max(-_MAX_ADJUST, min(_MAX_ADJUST, _KP * err))
            self._step += _SMOOTH * (target_step - self._step)
            step = self._step

            idx = self._pos + step * np.arange(frames, dtype=np.float64)
            need = int(np.floor(idx[-1])) + 2
            if need > avail:                                # underrun
                self.underruns += 1
                if avail < 2:
                    outdata[:] = 0.0
                    self._primed = False
                    return
                idx = np.clip(idx, 0.0, avail - 1.0000001)

            i0 = np.floor(idx).astype(np.int64)
            frac = (idx - i0).astype(np.float32).reshape(-1, 1)
            buf = self._in
            out = buf[i0] * (1.0 - frac) + buf[i0 + 1] * frac
            outdata[:] = out

            newpos = self._pos + step * frames
            consume = int(np.floor(newpos))
            if consume > 0:
                self._in = self._in[consume:]
                self._pos = newpos - consume
            else:
                self._pos = newpos

    def latency_frames(self) -> float:
        """Effective input-to-ear latency in frames: mean ring buffer fill level
        (== target, held by the controller) + PortAudio's device buffer. Used to
        delay the meter measurement to match."""
        dev = 0.0
        if self._stream is not None:
            try:
                dev = float(self._stream.latency) * self.rate
            except Exception:
                dev = 0.0
        return self.target + dev

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None


def list_output_devices():
    """List of (index, name) of devices with >=2 output channels. [] if sounddevice is missing."""
    try:
        import sounddevice as sd
    except Exception:
        return []
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_output_channels", 0) >= 2:
                out.append((i, d["name"]))
    except Exception:
        return []
    return out
