"""USB and format constants of the PS-HX500 (from the descriptors, see docs/usb_protocol.md)."""
from __future__ import annotations
from dataclasses import dataclass

VID = 0x054C
PID = 0x0BAA

CTRL_IFACE = 0        # AudioControl (clock entities)
STREAM_IFACE = 1      # AudioStreaming
EP_IN = 0x83          # isochronous IN endpoint
HID_IFACE = 2         # device identification only, unused here

CLOCK_SELECTOR_ID = 40
CLOCK_SOURCE_ID = 41
MAX_PACKET = 392      # wMaxPacketSize of EP 0x83

CHANNELS = 2

# UAC2 class request constants
RT_OUT = 0x21         # host->device | class | interface
RT_IN = 0xA1          # device->host | class | interface
CUR = 0x01
CS_SAM_FREQ = 0x0100  # control selector SAM_FREQ, channel 0
CS_CLK_VALID = 0x0200 # control selector CLOCK_VALID, channel 0

# PCM rates as in Sony's "Hi-Res Audio Recorder": 44.1/48/96/192 kHz.
# The hardware also reports 88200/176400/352800 through GET_RANGE; 176400/352800
# are the DSD carriers (see DSD_MODES) and are NOT offered as PCM.
RATES = (44100, 48000, 96000, 192000)

# all frequencies the device reports (GET RANGE, 7 subranges), for reference only
HW_RATES = (44100, 48000, 88200, 96000, 176400, 192000, 352800)


@dataclass(frozen=True)
class StreamFormat:
    alt: int             # alternate setting of the streaming interface
    bits: int            # valid bits per sample
    container_bytes: int # bytes per sample in the USB stream
    name: str


# Alternate settings according to the descriptors: 1=S16, 2=S24 (in 32), 3=S32.
# S32 (alt 3) is deliberately NOT offered: Sony's "Hi-Res Audio Recorder"
# only supports 16/24 bit.
FORMATS = {
    16: StreamFormat(alt=1, bits=16, container_bytes=2, name="S16LE"),
    24: StreamFormat(alt=2, bits=24, container_bytes=4, name="S24_in_S32LE"),
}

# ---- DSD -----------------------------------------------------------------
# Confirmed on the device (docs/usb_protocol.md, section DSD): DSD runs over alt 1
# (16-bit container), raw 1-bit DSD, 2 channels interleaved, MSB first per byte.
# DSD is switched on by a Sony vendor control request that must be sent BEFORE the
# SET_INTERFACE alt 0->1 (DSD starts on the alt transition).
RT_VENDOR_OUT = 0x41       # vendor | host->device | interface
VENDOR_DSD_REQUEST = 0x00  # bRequest
VENDOR_DSD_WINDEX = 0x0001 # wIndex (streaming interface)
DSD_ON = 0x0001            # wValue: DSD on
DSD_OFF = 0x0000           # wValue: DSD off / PCM
DSD_ALT = 1                # DSD uses alternate setting 1 (16-bit container)
DSD_CONTAINER_BYTES = 2    # bytes per channel and USB frame


@dataclass(frozen=True)
class DSDMode:
    carrier_rate: int  # USB clock rate (frames/s)
    dsd_rate: int      # DSD bit rate per channel (= carrier_rate * 16)
    name: str


# DSD64/DSD128 (Sony's recorder does not use DSD256). carrier_rate = dsd_rate / 16.
DSD_MODES = {
    64: DSDMode(carrier_rate=176400, dsd_rate=2822400, name="DSD64"),
    128: DSDMode(carrier_rate=352800, dsd_rate=5644800, name="DSD128"),
}


def windex_selector() -> int:
    return (CLOCK_SELECTOR_ID << 8) | CTRL_IFACE   # 0x2800


def windex_source() -> int:
    return (CLOCK_SOURCE_ID << 8) | CTRL_IFACE     # 0x2900
