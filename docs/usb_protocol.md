# The PS-HX500 USB protocol

This document describes how the Sony PS-HX500 talks over USB, as far as a
recording application needs it, and how `pshx500` uses it. It was worked out
from the device's USB descriptors, USB captures of Sony's Windows software
("Hi-Res Audio Recorder" with its driver) and probing the device under Linux.
The implementation is in [`pshx500/device.py`](../pshx500/device.py) and the
constants in [`pshx500/formats.py`](../pshx500/formats.py).

## Device overview

| Property | Value |
| -------- | ----- |
| VID:PID | `054c:0baa` (Sony Corporation, PS-HX500) |
| Speed | High speed (480 Mbit/s) |
| Class | Composite device, class defined per interface |
| IF0 | Audio Control (USB Audio Class 2.0) |
| IF1 | Audio Streaming, isochronous IN endpoint `0x83` |
| IF2 | Vendor-defined HID, used for device identification only |

Sony's Windows driver is a customized USB Audio Class 2.0 driver with an ASIO
layer on top. It also contains code for explicit feedback endpoints and volume
controls, but that is generic driver code: the device has neither (see below).

## Audio topology and gain

The input terminal (type *Phonograph*) is connected directly to the USB
streaming output terminal. There is **no feature unit**, so there is no volume
or gain control on the device and no mixer control under Linux.

The "gain" in Sony's recorder is applied in software. Changing it causes no USB
traffic at all, and the recorder only enables the gain setting after a
recording, as an export amplification. `pshx500` does the same: the gain is
applied digitally when the WAV file is written. The level meter and monitoring
show the signal before the gain.

## HID interface

Sony's recorder opens the HID interface only to find the device (vendor and
product ID, product string) and closes it again. It never reads or writes a
report. The interface plays no part in recording, and `pshx500` ignores it.

## Streaming formats

- Interface 1, endpoint **`0x83` IN, isochronous, asynchronous**, interval
  125 µs (`bInterval` 1), `wMaxPacketSize` 392. There is no feedback endpoint.
- Alternate settings, each stereo (left, right):

  | Alt | Format | Container |
  | --- | ------ | --------- |
  | 1 | S16_LE | 2 bytes |
  | 2 | S24 in a 32-bit slot (S32_LE, low byte zero) | 4 bytes |
  | 3 | S32_LE | 4 bytes |

- Sample rates (all alternate settings): 44100, 48000, 88200, 96000, 176400,
  192000 and 352800 Hz.

Sony's recorder, and `pshx500` with it, offers PCM at **44.1, 48, 96 and
192 kHz with 16 or 24 bit**. 176.4 and 352.8 kHz serve as carrier rates for
DSD (see below). 88.2 kHz and alternate setting 3 (S32) are not used.

## Start-up sequence

All class requests go to interface 0 (Audio Control). The clock selector has
ID 40, the clock source ID 41.

| Step | Request | Setup bytes | Data |
| ---- | ------- | ----------- | ---- |
| 1 | SET_CUR clock selector | `21 01 0100 2800`, length 1 | `01` (input = clock 41) |
| 2 | SET_CUR sampling frequency | `21 01 0100 2900`, length 4 | rate as 32-bit LE, e.g. `00 77 01 00` = 96000 |
| 3 | GET_CUR clock valid | `A1 01 0200 2900`, length 1 | answer `01` = valid |
| 4 | SET_INTERFACE on IF1 | `00 0B <alt> 0001` | – |

Then the host reads endpoint `0x83` isochronously. On stop, `pshx500` sets IF1
back to alternate setting 0 and releases the interfaces.

The clock needs a few milliseconds to lock after the rate is set, so
`pshx500` polls step 3 up to 12 times at 30 ms intervals.

Sony's software reads the supported rates first (GET RANGE on the clock
source, 7 subranges) and sends a UAC1-style endpoint sampling-frequency
request (`22 01 0100 01xx`, 3-byte rate) after SET_INTERFACE. Neither is
needed; `pshx500` sends neither.

### Why the Linux kernel driver cannot use the device

The device reports its clock as **valid only after** a sampling frequency has
been set once. `snd-usb-audio` checks the clock validity *before* it sets the
rate, finds the clock invalid ("clock source 41 is not valid, cannot use") and
gives up. No module parameter avoids that. A kernel quirk could, but `pshx500`
works around it entirely in user space: it drives the device through libusb
and only needs a udev rule for access
([`packaging/udev/70-pshx500.rules`](../packaging/udev/70-pshx500.rules)).

## DSD

DSD is a Sony vendor extension on top of the standard streaming interface.
Selecting a carrier rate alone (standard UAC2) only yields zero bytes; DSD has
to be switched on with a vendor request:

| Field | Value |
| ----- | ----- |
| `bmRequestType` | `0x41` (vendor, host to device, interface) |
| `bRequest` | `0x00` |
| `wValue` | `0x0001` = DSD on, `0x0000` = DSD off (PCM) |
| `wIndex` | `0x0001` (streaming interface) |
| `wLength` | 0 |

The request must come **before** the switch from alternate setting 0 to 1;
DSD starts on that transition. The sequence for DSD is therefore steps 1 to 3
above with the carrier rate, SET_INTERFACE alt 0, the vendor request, then
SET_INTERFACE alt 1. On stop, `pshx500` switches DSD off again.

Stream format:

- Alternate setting 1 (16-bit container), raw 1-bit DSD, two channels
  interleaved: `[L0 L1 R0 R1]` per USB frame, **MSB first** within each byte.
- Carrier rate = DSD bit rate / 16:

  | Mode | DSD rate per channel | Clock rate (SET_CUR) |
  | ---- | -------------------- | -------------------- |
  | DSD64 | 2 822 400 bit/s | 176 400 Hz |
  | DSD128 | 5 644 800 bit/s | 352 800 Hz |

  Sony's recorder does not offer DSD256, and neither does `pshx500`.

`pshx500` writes DSD recordings as **DSF** files
([`pshx500/dsf.py`](../pshx500/dsf.py)): one block of 4096 bytes per channel
in turn, bits **LSB first** within each byte, so every byte from the USB
stream is bit-reversed. For the level meter and monitoring, the DSD stream is
decoded to 44.1 kHz PCM with a multi-stage windowed-sinc decimation
([`pshx500/dsd.py`](../pshx500/dsd.py)). A gain cannot be applied to DSD
without remodulating it, so DSD recordings are stored as they come.
