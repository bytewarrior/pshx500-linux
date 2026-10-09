"""libusb capture core for the PS-HX500.

Claims the interfaces, sets the clock selector and the sampling frequency (which
makes the clock valid), activates the streaming alternate setting and reads
EP 0x83 asynchronously and isochronously. Raw data (interleaved L/R in the
respective container format) goes to a callback. The libusb event loop runs in a
background thread.
"""
from __future__ import annotations

import struct
import threading
import time
from typing import Callable, Optional

import usb1

from . import formats as F


class DeviceError(RuntimeError):
    pass


class PSHX500Capture:
    def __init__(self, rate: int = 96000, bits: int = 24, dsd: int | None = None,
                 num_transfers: int = 8, packets_per_transfer: int = 32):
        self.is_dsd = dsd is not None
        if self.is_dsd:
            if dsd not in F.DSD_MODES:
                raise ValueError(f"DSD mode {dsd} not supported: {sorted(F.DSD_MODES)}")
            self.dsd_mode = F.DSD_MODES[dsd]
            # DSD uses alt 1 (16-bit container); clock = carrier rate.
            self.rate = self.dsd_mode.carrier_rate
            self.fmt = F.StreamFormat(alt=F.DSD_ALT, bits=1,
                                      container_bytes=F.DSD_CONTAINER_BYTES,
                                      name=self.dsd_mode.name)
        else:
            if rate not in F.RATES:
                raise ValueError(f"Rate {rate} not supported: {F.RATES}")
            if bits not in F.FORMATS:
                raise ValueError(f"Bit depth {bits} not supported: {sorted(F.FORMATS)}")
            self.dsd_mode = None
            self.rate = rate
            self.fmt = F.FORMATS[bits]
        self.frame_bytes = self.fmt.container_bytes * F.CHANNELS
        self._num_transfers = num_transfers
        self._packets = packets_per_transfer

        self._ctx: Optional[usb1.USBContext] = None
        self._handle = None
        self._transfers: list = []
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._on_data: Optional[Callable[[bytes], None]] = None
        self.validity: Optional[int] = None

    # ---- Setup -------------------------------------------------------------
    def open(self) -> None:
        self._ctx = usb1.USBContext()
        self._ctx.open()
        self._handle = self._ctx.openByVendorIDAndProductID(F.VID, F.PID)
        if self._handle is None:
            raise DeviceError("PS-HX500 (054c:0baa) not found.")
        try:
            self._handle.setAutoDetachKernelDriver(True)
        except usb1.USBError:
            pass
        self._handle.claimInterface(F.CTRL_IFACE)
        self._handle.claimInterface(F.STREAM_IFACE)

        # UAC2: select the clock selector input + set the sampling frequency -> clock becomes valid
        self._handle.controlWrite(F.RT_OUT, F.CUR, F.CS_SAM_FREQ, F.windex_selector(), b"\x01")
        self._handle.controlWrite(F.RT_OUT, F.CUR, F.CS_SAM_FREQ, F.windex_source(),
                                  struct.pack("<I", self.rate))
        # The clock/PLL needs a few ms to lock after the rate is set -> retry.
        self.validity = None
        for _ in range(12):
            data = self._handle.controlRead(F.RT_IN, F.CUR, F.CS_CLK_VALID, F.windex_source(), 1)
            self.validity = data[0] if len(data) else None
            if self.validity == 1:
                break
            time.sleep(0.03)

        # Activate the streaming endpoint
        if self.is_dsd:
            # DSD enable MUST come before the alt 0->1 transition (DSD starts on the transition).
            try:
                self._handle.setInterfaceAltSetting(F.STREAM_IFACE, 0)
            except usb1.USBError:
                pass
            self._handle.controlWrite(F.RT_VENDOR_OUT, F.VENDOR_DSD_REQUEST,
                                      F.DSD_ON, F.VENDOR_DSD_WINDEX, b"")
            self._handle.setInterfaceAltSetting(F.STREAM_IFACE, self.fmt.alt)
        else:
            self._handle.setInterfaceAltSetting(F.STREAM_IFACE, self.fmt.alt)

    # ---- Streaming ---------------------------------------------------------
    def start(self, on_data: Callable[[bytes], None]) -> None:
        if self._handle is None:
            raise DeviceError("Call open() first.")
        self._on_data = on_data
        self._running = True
        for _ in range(self._num_transfers):
            t = self._handle.getTransfer(iso_packets=self._packets)
            t.setIsochronous(F.EP_IN, F.MAX_PACKET * self._packets, callback=self._cb)
            t.submit()
            self._transfers.append(t)
        self._thread = threading.Thread(target=self._loop, name="pshx500-iso", daemon=True)
        self._thread.start()

    def _cb(self, transfer) -> None:
        # bundle all packets of a transfer into ONE chunk (per packet would be too fine-grained)
        buf = bytearray()
        for _status, data in transfer.iterISO():
            if data:
                buf += data
        if buf:
            self._on_data(bytes(buf))
        if self._running:
            try:
                transfer.submit()
            except usb1.USBError:
                pass

    def _loop(self) -> None:
        while self._running:
            try:
                self._ctx.handleEventsTimeout(0.1)
            except usb1.USBError:
                break

    # ---- Teardown ----------------------------------------------------------
    def stop(self) -> None:
        self._running = False
        for t in self._transfers:
            try:
                t.cancel()
            except usb1.USBError:
                pass
        if self._ctx is not None:
            for _ in range(10):
                try:
                    self._ctx.handleEventsTimeout(0.05)
                except usb1.USBError:
                    break
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._transfers.clear()

    def close(self) -> None:
        if self._handle is not None:
            if self.is_dsd:
                try:  # switch DSD off again
                    self._handle.controlWrite(F.RT_VENDOR_OUT, F.VENDOR_DSD_REQUEST,
                                              F.DSD_OFF, F.VENDOR_DSD_WINDEX, b"")
                except usb1.USBError:
                    pass
            try:
                self._handle.setInterfaceAltSetting(F.STREAM_IFACE, 0)
            except usb1.USBError:
                pass
            for iface in (F.STREAM_IFACE, F.CTRL_IFACE):
                try:
                    self._handle.releaseInterface(iface)
                except usb1.USBError:
                    pass
            self._handle.close()
            self._handle = None
        if self._ctx is not None:
            self._ctx.close()
            self._ctx = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.stop()
        self.close()
