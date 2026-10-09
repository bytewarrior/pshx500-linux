"""Command line for pshx500: recording with a live level display."""
from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from . import formats as F
from .recorder import CaptureSession


def _bar(db: float, width: int = 28, floor: float = -60.0) -> str:
    frac = max(0.0, min(1.0, (db - floor) / (0.0 - floor)))
    n = int(frac * width)
    return "#" * n + "-" * (width - n)


def cmd_record(args) -> int:
    if args.dsd:
        rec = CaptureSession(dsd=args.dsd)
    else:
        rec = CaptureSession(rate=args.rate, bits=args.bits)
    rec.start()
    if args.monitor:
        dev = args.monitor_device
        if dev is not None and dev.isdigit():
            dev = int(dev)
        rec.set_monitor(True, dev)
        if rec.monitor_error:
            print(f"Monitoring off: {rec.monitor_error}", file=sys.stderr)
    rec.start_recording(args.out, gain_db=args.gain)
    if rec.validity != 1:
        print(f"Warning: clock validity={rec.validity} (recording may be empty)", file=sys.stderr)
    if args.dsd:
        print(f"Recording -> {args.out}  @ {rec.dsd_mode.name} "
              f"({rec.dsd_mode.dsd_rate} bit/s, carrier {rec.rate} Hz)")
    else:
        print(f"Recording -> {args.out}  @ {args.rate} Hz / {args.bits} bit, "
              f"gain {args.gain:+.1f} dB")
    print("Ctrl+C to stop." if not args.seconds else f"Duration: {args.seconds:.0f}s")
    t0 = time.monotonic()
    try:
        while True:
            time.sleep(0.1)
            L, R = rec.meter.read()
            over = "OVER" if (L["over"] or R["over"]) else "    "
            sys.stdout.write("\rL %6.1f|%s|  R %6.1f|%s| %s"
                             % (L["peak_db"], _bar(L["peak_db"]),
                                R["peak_db"], _bar(R["peak_db"]), over))
            sys.stdout.flush()
            if args.seconds and (time.monotonic() - t0) >= args.seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        rec.stop()
    print(f"\nDone: {rec.frames_written} frames written, dropped={rec.dropped}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pshx500",
                                description="Sony PS-HX500 recording (Linux, libusb)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="record PCM into a WAV file (or DSD into a DSF file)")
    r.add_argument("out", help="target file (.wav, or .dsf with --dsd)")
    r.add_argument("--rate", type=int, default=96000, choices=F.RATES)
    r.add_argument("--bits", type=int, default=24, choices=sorted(F.FORMATS))
    r.add_argument("--dsd", type=int, default=0, choices=sorted(F.DSD_MODES),
                   help="DSD recording (64 or 128) into a .dsf file instead of PCM/WAV")
    r.add_argument("--gain", type=float, default=0.0, help="software gain in dB (WAV/PCM only)")
    r.add_argument("--seconds", type=float, default=0.0, help="0 = until Ctrl+C")
    r.add_argument("--monitor", action="store_true", help="monitor through an output device")
    r.add_argument("--monitor-device", default=None,
                   help="sounddevice output device (index or name); default = system")
    r.set_defaults(func=cmd_record)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
