#!/bin/sh
# Apply the udev rule to a PS-HX500 that is already plugged in.
set -e
if command -v udevadm >/dev/null 2>&1; then
	udevadm control --reload-rules || true
	udevadm trigger --subsystem-match=usb --attr-match=idVendor=054c || true
fi
