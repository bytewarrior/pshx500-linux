"""DSF writer (Sony DSD Stream File) for the PS-HX500.

The USB stream delivers raw 1-bit DSD in 16-bit containers, 2 channels interleaved
([L0 L1 R0 R1] per frame), bit order MSB first per byte. The DSF format instead
stores:
  * block by block per channel (default block size 4096 bytes): [block L][block R][block L]...
  * LSB first within a byte (so a per-byte bit reversal compared with the USB stream,
    as Sony's recorder does it too).

Header layout (little endian) according to the DSF specification:
  "DSD " chunk (28 B), "fmt " chunk (52 B), "data" chunk (12 B + payload).
"""
from __future__ import annotations

import struct

import numpy as np

from . import formats as F

# per-byte bit reversal (MSB first  ->  LSB first)
_BITREV = np.array(
    [int(f"{i:08b}"[::-1], 2) for i in range(256)], dtype=np.uint8
)

_BLOCK = 4096  # default block size per channel


class DSFWriter:
    def __init__(self, path: str, dsd_rate: int, channels: int = F.CHANNELS,
                 block_size: int = _BLOCK):
        self.path = path
        self.dsd_rate = dsd_rate
        self.channels = channels
        self.block = block_size
        self._f = open(path, "wb")
        self._chan_buf = [bytearray() for _ in range(channels)]
        self._data_bytes = 0            # data bytes actually written (including padding)
        self._sample_bytes = 0          # valid bytes per channel (without padding)
        self._f.write(b"\x00" * (28 + 52))  # header placeholder, patched at the end
        self._f.write(b"data")
        self._f.write(struct.pack("<Q", 0))  # data chunk size, patched at the end

    def write(self, raw: bytes) -> None:
        """raw = interleaved USB frames [L_lo,L_hi,R_lo,R_hi,...]."""
        step = F.DSD_CONTAINER_BYTES * self.channels
        n = (len(raw) // step) * step
        if n == 0:
            return
        frames = np.frombuffer(raw[:n], dtype=np.uint8).reshape(-1, step)
        cb = F.DSD_CONTAINER_BYTES
        for ch in range(self.channels):
            # this channel's bytes in time order (lo,hi as received), bits reversed
            chan = frames[:, ch * cb:(ch + 1) * cb].reshape(-1)
            self._chan_buf[ch] += _BITREV[chan].tobytes()
        self._sample_bytes += n // step * cb
        self._flush_blocks()

    def _flush_blocks(self) -> None:
        # As long as every channel has a full block: write block L, block R, ...
        while all(len(b) >= self.block for b in self._chan_buf):
            for ch in range(self.channels):
                self._f.write(bytes(self._chan_buf[ch][:self.block]))
                del self._chan_buf[ch][:self.block]
                self._data_bytes += self.block

    def close(self) -> None:
        if self._f is None:
            return
        # pad the last (partial) block of each channel with zeros to the block size
        if any(self._chan_buf):
            for ch in range(self.channels):
                pad = (-len(self._chan_buf[ch])) % self.block
                block = bytes(self._chan_buf[ch]) + b"\x00" * pad
                self._f.write(block)
                self._data_bytes += len(block)
                self._chan_buf[ch] = bytearray()

        data_chunk = 12 + self._data_bytes
        total = 28 + 52 + data_chunk
        sample_count = self._sample_bytes * 8  # valid 1-bit samples per channel

        self._f.seek(0)
        # "DSD " chunk
        self._f.write(b"DSD ")
        self._f.write(struct.pack("<Q", 28))       # chunk size
        self._f.write(struct.pack("<Q", total))     # total file size
        self._f.write(struct.pack("<Q", 0))         # no metadata chunk
        # "fmt " chunk
        self._f.write(b"fmt ")
        self._f.write(struct.pack("<Q", 52))        # chunk size
        self._f.write(struct.pack("<I", 1))         # format version
        self._f.write(struct.pack("<I", 0))         # format ID (0 = DSD raw)
        self._f.write(struct.pack("<I", 2))         # channel type (2 = stereo)
        self._f.write(struct.pack("<I", self.channels))
        self._f.write(struct.pack("<I", self.dsd_rate))
        self._f.write(struct.pack("<I", 1))         # bits per sample
        self._f.write(struct.pack("<Q", sample_count))
        self._f.write(struct.pack("<I", self.block))
        self._f.write(struct.pack("<I", 0))         # reserved
        # "data" chunk header
        self._f.write(b"data")
        self._f.write(struct.pack("<Q", data_chunk))
        self._f.close()
        self._f = None
