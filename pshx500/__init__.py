"""pshx500 - Linux recording software for the Sony PS-HX500 USB turntable.

The device is a USB Audio Class 2.0 device (VID:PID 054c:0baa) with a phono
input. The Linux kernel driver snd-usb-audio cannot drive it (clock validity
deadlock), so this software talks to the device directly through libusb: set
the sampling rate, then read the isochronous endpoint 0x83.
See docs/usb_protocol.md.
"""
__version__ = "1.0.0"
