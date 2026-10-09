"""CaptureSession: one running libusb capture on which the level meter, monitoring
(audio playback) and recording can be switched on and off INDEPENDENTLY. So
monitoring runs separately from the record button; recording can start and stop
without interrupting monitoring.

The software gain is (as in the Windows app) applied only to the WAV file; the
meter and monitoring show/play the input signal.
"""
from __future__ import annotations

import queue
import threading
import wave

import numpy as np

from . import formats as F
from .device import PSHX500Capture
from .dsd import DsdPcmDecoder
from .dsf import DSFWriter
from .meter import LevelMeter

# Decoder output rate for the DSD meter/monitoring (divides DSD64 and DSD128 evenly).
DSD_MONITOR_RATE = 44100


class _MeterDelay:
    """Delays the meter measurement by the monitoring latency, so the display
    matches the audio actually heard. Without active monitoring (delay_frames<=0)
    the buffer is flushed and measured at once -- there is no listening reference
    then."""

    def __init__(self, framesize: int):
        self._framesize = framesize
        self._buf = bytearray()

    def feed(self, data: bytes, delay_frames: float, meter) -> None:
        if delay_frames <= 0:
            if self._buf:
                meter.process(bytes(self._buf))
                self._buf.clear()
            meter.process(data)
            return
        self._buf += data
        keep = int(delay_frames) * self._framesize
        release = len(self._buf) - keep
        release -= release % self._framesize
        if release > 0:
            meter.process(bytes(self._buf[:release]))
            del self._buf[:release]


class CaptureSession:
    def __init__(self, rate: int = 96000, bits: int = 24, dsd: int | None = None):
        self.is_dsd = dsd is not None
        self.monitor = None
        self.monitor_error = None
        self.gain = 1.0
        self._wav = None
        self._dsf = None
        self._q: "queue.Queue[bytes]" = queue.Queue(maxsize=512)
        self._writer = None
        self._writing = False
        self.frames_written = 0
        self.dropped = 0

        if self.is_dsd:
            self.dsd = dsd
            self.dsd_mode = F.DSD_MODES[dsd]
            self.cap = PSHX500Capture(dsd=dsd)
            self.rate = self.cap.rate       # carrier rate
            self.bits = 1
            self.fmt = self.cap.fmt
            self._decoder = DsdPcmDecoder(self.dsd_mode.dsd_rate, out_rate=DSD_MONITOR_RATE)
            self.meter = LevelMeter(4)      # int32 container from the decoder
            self._mon_rate = DSD_MONITOR_RATE
            self._mon_container = 4
        else:
            self.rate = rate
            self.bits = bits
            self.fmt = F.FORMATS[bits]
            self.cap = PSHX500Capture(rate=rate, bits=bits)
            self._decoder = None
            self.meter = LevelMeter(self.fmt.container_bytes)
            self._mon_rate = self.rate
            self._mon_container = self.fmt.container_bytes
        self._meter_delay = _MeterDelay(self._mon_container * F.CHANNELS)

    @property
    def validity(self):
        return self.cap.validity

    @property
    def recording(self) -> bool:
        return self._writing

    # ---- Life cycle ---------------------------------------------------------
    def start(self) -> None:
        self.cap.open()
        self.cap.start(self._on_data)

    def stop(self) -> None:
        self.stop_recording()
        self.set_monitor(False)
        self.cap.stop()
        self.cap.close()

    def _on_data(self, raw: bytes) -> None:
        if self.is_dsd:
            # Decode DSD once (filter state!), use the result for meter and monitoring.
            pcm = self._decoder.feed_int32_bytes(raw)
            if pcm:
                mon = self.monitor
                if mon is not None:
                    mon.feed(pcm)
                self._meter_delay.feed(
                    pcm, mon.latency_frames() if mon is not None else 0, self.meter)
            if self._writing:
                try:
                    self._q.put_nowait(raw)   # raw DSD into the .dsf
                except queue.Full:
                    self.dropped += 1
            return
        mon = self.monitor
        if mon is not None:
            mon.feed(raw)
        self._meter_delay.feed(
            raw, mon.latency_frames() if mon is not None else 0, self.meter)
        if self._writing:
            try:
                self._q.put_nowait(raw)
            except queue.Full:
                self.dropped += 1

    # ---- Monitoring (audio playback) -----------------------------------------
    def set_monitor(self, enable: bool, device=None) -> None:
        self.monitor_error = None
        if enable:
            if self.monitor is not None:
                return
            try:
                from .monitor import MonitorPlayer
                m = MonitorPlayer(self._mon_rate, self._mon_container, device=device)
                m.start()
                self.monitor = m
            except Exception as e:      # sounddevice missing / rate not supported
                self.monitor = None
                self.monitor_error = str(e)
        else:
            m, self.monitor = self.monitor, None
            if m is not None:
                m.stop()

    # ---- Recording ----------------------------------------------------------
    def start_recording(self, path: str, gain_db: float = 0.0) -> None:
        if self._writing:
            return
        self.gain = 10.0 ** (gain_db / 20.0)
        self.frames_written = 0
        self.dropped = 0
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        if self.is_dsd:
            # Gain would need a remodulation in the DSD domain -> not applied here.
            self._dsf = DSFWriter(path, self.dsd_mode.dsd_rate)
        else:
            self._wav = wave.open(path, "wb")
            self._wav.setnchannels(F.CHANNELS)
            self._wav.setframerate(self.rate)
            self._wav.setsampwidth(3 if self.bits == 24 else self.fmt.container_bytes)
        self._writing = True
        self._writer = threading.Thread(target=self._write_loop, name="pshx500-write", daemon=True)
        self._writer.start()

    def stop_recording(self) -> None:
        if not self._writing:
            return
        self._writing = False
        if self._writer is not None:
            self._writer.join(timeout=3.0)
            self._writer = None
        if self._wav is not None:
            self._wav.close()
            self._wav = None
        if self._dsf is not None:
            self._dsf.close()
            self._dsf = None

    def set_gain(self, gain_db: float) -> None:
        self.gain = 10.0 ** (gain_db / 20.0)

    # ---- File writing -------------------------------------------------------
    def _write_loop(self) -> None:
        step = F.DSD_CONTAINER_BYTES * F.CHANNELS
        while self._writing or not self._q.empty():
            try:
                raw = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.is_dsd:
                self._dsf.write(raw)
                self.frames_written += len(raw) // step
            else:
                self._wav.writeframes(self._convert(raw))

    def _convert(self, raw: bytes) -> bytes:
        step = self.fmt.container_bytes * F.CHANNELS
        n = (len(raw) // step) * step
        if n == 0:
            return b""
        raw = raw[:n]
        if self.bits == 16:
            a = np.frombuffer(raw, dtype="<i2")
            if self.gain != 1.0:
                a = np.clip(a.astype(np.float32) * self.gain, -32768, 32767).astype("<i2")
            self.frames_written += len(a) // F.CHANNELS
            return a.tobytes()
        a = np.frombuffer(raw, dtype="<i4")
        if self.gain != 1.0:
            a = np.clip(a.astype(np.float64) * self.gain, -(2 ** 31), 2 ** 31 - 1).astype("<i4")
        self.frames_written += len(a) // F.CHANNELS
        # 24 bit: the upper 3 bytes of each LE int32 = 24-bit LE sample
        b = np.frombuffer(a.astype("<i4").tobytes(), dtype=np.uint8).reshape(-1, 4)[:, 1:4]
        return b.tobytes()
