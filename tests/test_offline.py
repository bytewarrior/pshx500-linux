"""Tests for the hardware-independent parts: DSF writer, DSD decoder, level
meter and the PCM conversion of the recorder. No device needed."""
from __future__ import annotations

import os
import struct
import tempfile
import unittest

import numpy as np

from pshx500 import formats as F
from pshx500.dsd import DsdPcmDecoder
from pshx500.dsf import DSFWriter
from pshx500.meter import FLOOR, LevelMeter
from pshx500.recorder import CaptureSession


def _dsd_frames(left: int, right: int, frames: int) -> bytes:
    """USB DSD frames with a constant byte per channel ([L L R R] per frame)."""
    return bytes([left, left, right, right]) * frames


class DSFWriterTest(unittest.TestCase):
    def test_header_and_bit_order(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.dsf")
            w = DSFWriter(path, F.DSD_MODES[64].dsd_rate, block_size=16)
            w.write(_dsd_frames(0x01, 0x80, 10))   # 20 bytes per channel
            w.close()
            with open(path, "rb") as f:
                data = f.read()

        self.assertEqual(data[0:4], b"DSD ")
        total, = struct.unpack_from("<Q", data, 12)
        self.assertEqual(total, len(data))
        self.assertEqual(data[28:32], b"fmt ")
        rate, bits, samples, block = struct.unpack_from("<IIQI", data, 28 + 28)
        self.assertEqual(rate, 2822400)
        self.assertEqual(bits, 1)
        self.assertEqual(samples, 20 * 8)
        self.assertEqual(block, 16)
        self.assertEqual(data[80:84], b"data")

        payload = data[92:]
        # two blocks per channel (20 bytes padded to 32), L/R interleaved by block,
        # each byte bit-reversed: 0x01 -> 0x80, 0x80 -> 0x01
        self.assertEqual(len(payload), 4 * 16)
        self.assertEqual(payload[0:16], b"\x80" * 16)
        self.assertEqual(payload[16:32], b"\x01" * 16)
        self.assertEqual(payload[32:48], b"\x80" * 4 + b"\x00" * 12)
        self.assertEqual(payload[48:64], b"\x01" * 4 + b"\x00" * 12)


class DsdDecoderTest(unittest.TestCase):
    def test_dc_levels(self):
        dec = DsdPcmDecoder(F.DSD_MODES[64].dsd_rate, out_rate=44100)
        # left all ones (+1), right alternating bits (0)
        pcm = np.concatenate([dec.feed(_dsd_frames(0xFF, 0x55, 4096)) for _ in range(8)])
        self.assertGreater(len(pcm), 100)
        tail = pcm[len(pcm) // 2:]
        self.assertTrue(np.allclose(tail[:, 0], 1.0, atol=0.01))
        self.assertTrue(np.allclose(tail[:, 1], 0.0, atol=0.01))

    def test_output_rate(self):
        dec = DsdPcmDecoder(F.DSD_MODES[128].dsd_rate, out_rate=44100)
        frames = F.DSD_MODES[128].carrier_rate // 10        # 0.1 s
        pcm = dec.feed(_dsd_frames(0x55, 0x55, frames))
        self.assertAlmostEqual(len(pcm), 4410, delta=2)


class LevelMeterTest(unittest.TestCase):
    def test_peak_and_over(self):
        m = LevelMeter(container_bytes=2)
        half = np.array([16384, -32768] * 100, dtype="<i2").tobytes()
        m.process(half)
        left, right = m.read()
        self.assertAlmostEqual(left["peak_db"], -6.02, places=2)
        self.assertFalse(left["over"])
        self.assertAlmostEqual(right["peak_db"], 0.0, places=2)
        self.assertTrue(right["over"])

    def test_silence(self):
        m = LevelMeter(container_bytes=4)
        m.process(bytes(8 * 100))
        self.assertEqual(m.read()[0]["peak_db"], FLOOR)


class PcmConversionTest(unittest.TestCase):
    def test_24bit_with_gain(self):
        s = CaptureSession(rate=96000, bits=24)
        s.set_gain(20 * np.log10(2))                      # x2
        raw = np.array([0x00123400, -0x00123400], dtype="<i4").tobytes()
        out = s._convert(raw)
        self.assertEqual(len(out), 6)
        left = int.from_bytes(out[0:3], "little", signed=True)
        right = int.from_bytes(out[3:6], "little", signed=True)
        self.assertEqual(left, 0x002468)
        self.assertEqual(right, -0x002468)

    def test_16bit_clips(self):
        s = CaptureSession(rate=48000, bits=16)
        s.set_gain(12.0)
        out = np.frombuffer(s._convert(np.array([20000, -20000], dtype="<i2").tobytes()), "<i2")
        self.assertEqual(out.tolist(), [32767, -32768])


if __name__ == "__main__":
    unittest.main()
