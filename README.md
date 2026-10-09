<img src="pshx500/app_icon.png" align="right" width="20%" alt="pshx500 logo">

# pshx500-linux

Recording software for the **Sony PS-HX500** USB turntable on Linux: a
command line tool and a graphical recorder that capture the turntable's
digital output as **PCM (WAV)** or **DSD (DSF)**.

Sony's recording software for the PS-HX500 never ran on Linux and is no
longer maintained. On Linux the turntable shows up as a USB audio device,
but the kernel's USB audio driver cannot use it (see
[How it works](#how-it-works)). `pshx500` talks to the turntable directly
through libusb instead, with no kernel patch or driver needed.

<div style="clear: both;"></div>

## Status

**Version 1.0.0.** PCM recording works end to end with a phono signal; DSD64
and DSD128 recordings have been checked by decoding them. Tested on Linux
Mint 22 (Ubuntu 24.04 base) with Python 3.12.

## Features

- **PCM** at 44.1, 48, 96 and 192 kHz with 16 or 24 bit, into WAV files
- **DSD64** (2.8 MHz) and **DSD128** (5.6 MHz), into DSF files, bit-exact as
  the turntable delivers them
- **Stereo level meter** with peak hold and OVER indicator, also for DSD
  (decoded to PCM for display)
- **Monitoring** through any other audio output, with drift compensation: the
  turntable's clock and the sound card's clock drift apart, so `pshx500`
  resamples continuously instead of dropping samples, without clicks
- **Software gain** for PCM, applied to the file only, as in Sony's recorder
  (the turntable has no hardware gain)
- **Command line tool** `pshx500` and **GUI** `pshx500-gui` (Qt/PySide6)
- Monitoring and recording can be started and stopped independently

## How it works

The PS-HX500 is a USB Audio Class 2.0 device. It reports its sample clock as
valid only after a sampling rate has been set once, while the kernel driver
`snd-usb-audio` checks the clock *before* it sets a rate, finds it invalid and
gives up. `pshx500` therefore does the set-up itself:

```
PS-HX500 ──USB──▶ libusb (pshx500/device.py)
                    │  set clock + rate, select format, [DSD on]
                    │  isochronous endpoint 0x83
                    ▼
              CaptureSession (recorder.py)
               ├─▶ WAV writer + gain      (PCM)
               ├─▶ DSF writer             (DSD)
               ├─▶ level meter            (meter.py, DSD via dsd.py)
               └─▶ monitoring with ASRC   (monitor.py → sounddevice/PortAudio)
```

DSD is a Sony vendor extension, switched on by a vendor request before the
streaming interface is enabled. The details are in
[docs/usb_protocol.md](docs/usb_protocol.md); the level meter is described in
[docs/level_meter.md](docs/level_meter.md).

## Requirements

- Linux with libusb 1.0
- Python 3.10 or later with NumPy and `libusb1`
- For monitoring: `sounddevice` and PortAudio
- For the GUI: PySide6 (Qt 6) and `sounddevice`
- A udev rule for USB access without root (included)

## Installation

### From the release packages

The [releases](https://github.com/bytewarrior/pshx500-linux/releases) contain
a Debian package and a Python wheel.

**Debian 13, Ubuntu 25.04 and later** have all dependencies as packages:

```bash
sudo apt install ./pshx500_1.0.0_all.deb
```

This installs `pshx500`, `pshx500-gui` with a menu entry, and the udev rule.
Monitoring and the GUI come with the recommended packages
`python3-sounddevice` and `python3-pyside6.qtwidgets`. Plug the turntable in
again after the installation.

**Ubuntu 24.04, Linux Mint 22 and other distributions** lack some of these
packages. Install the wheel with [pipx](https://pipx.pypa.io) and the udev
rule by hand:

```bash
pipx install "./pshx500-1.0.0-py3-none-any.whl[gui]"
sudo curl -o /etc/udev/rules.d/70-pshx500.rules \
  https://raw.githubusercontent.com/bytewarrior/pshx500-linux/main/packaging/udev/70-pshx500.rules
sudo udevadm control --reload && sudo udevadm trigger
```

Use `[monitor]` instead of `[gui]` for the command line tool with monitoring,
or no extra for recording only. PortAudio comes from the distribution
(`libportaudio2` on Debian and Ubuntu).

### From source

```bash
git clone https://github.com/bytewarrior/pshx500-linux.git
cd pshx500-linux
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[gui]"
sudo cp packaging/udev/70-pshx500.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
python3 -m unittest discover -s tests       # tests, no turntable needed
```

To build the release artifacts locally (needs [nfpm](https://nfpm.goreleaser.com)):

```bash
packaging/build-packages.sh 1.0.0
```

## Usage

### GUI

```bash
pshx500-gui
```

Choose the format (PCM or DSD), sample rate, bit depth, gain and target file.
**Monitor** starts the level meter (and listening, if ticked) without
recording, so you can check the level first. **Record** writes the file;
monitoring keeps running when you stop the recording.

### Command line

```bash
pshx500 record album.wav --rate 96000 --bits 24 --gain 0   # PCM, live level display
pshx500 record album.wav --monitor                          # listen while recording
pshx500 record album.dsf --dsd 128                          # DSD128 into a DSF file
pshx500 record side-a.wav --seconds 1500                    # fixed duration instead of Ctrl+C
```

`--monitor-device` selects the output device (sounddevice index or name).
`--rate`, `--bits` and `--gain` do not apply to DSD.

## Contributing

Bug reports and pull requests are welcome. Please include your distribution,
the output of `lsusb -v -d 054c:0baa`, and the full output of the command
that failed.

## Acknowledgements

- [libusb](https://libusb.info) and Vincent Pelletier's Python binding
  [python-libusb1](https://github.com/vpelletier/python-libusb1), which do the
  USB work
- [NumPy](https://numpy.org) for the sample processing and DSD decoding
- [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) and
  [PortAudio](https://www.portaudio.com) for monitoring
- [Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/) for the GUI
- Sony's DSF file format specification, for the DSF writer
- [nfpm](https://nfpm.goreleaser.com) for the Debian package

## Disclaimer

This project is not affiliated with, endorsed by or connected to Sony. All
product names and trademarks belong to their owners and are used only to
describe compatibility. The USB protocol was worked out by observing Sony's
software and the device, for the sole purpose of interoperability. Use this
software at your own risk.

## License

MIT, see [LICENSE](LICENSE).

## Part of the save old hardware collection

<img src="saveOldHardware.png" align="left" hspace="10">

This project is part of a larger idea: I own a lot of old hardware that would be unusable if I hadn't written drivers and tools to bring it back to life. From the early nineties and, even more so, the early 2000s up to today, a lot of Windows-only or use-once-then-throw-away hardware was developed and sold, only to become electronic waste a few years later. And it kept happening, because the manufacturers kept moving on to newer products and dropping support for older devices entirely. Expensive audio equipment, lab gear, other specialized kit that's hard to find, you name it.

As a tinkerer, electrical design engineer and software developer (I do the latter two for a living), I decided to stop accepting this and do something about it. Hence, I've created this logo, and I attach it to every project where saving a device from becoming waste is a central goal.

Feel free to use this logo as well, and spread the word! Thanks for reading this. People like you make a difference in this world. Become a part of us — try to write software for the stuff you own, and consider publishing it as open source.

<div style="clear: both;"></div>
