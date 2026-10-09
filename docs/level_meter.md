# The level meter

This document describes the level meter of Sony's "Hi-Res Audio Recorder", as
far as it could be worked out from the program, and how `pshx500` implements
its own meter ([`pshx500/meter.py`](../pshx500/meter.py)).

## Sony's meter

Per channel, the recorder takes the **peak** of the samples in a block and
converts it to **dBFS**:

```
peak = max(|sample|) over the block      # linear amplitude, 0..fullscale
dBFS = 20 * log10(peak / fullscale)      # <= 0 dB; -inf for silence
```

- The factor 20 means amplitude dB, not power dB.
- The value is stored as a scaled integer; "no data" is `INT_MIN` (−∞ dB).
- Each channel keeps the current level, a peak that follows new maxima at
  once, a peak-hold value with a hold timer, and an **OVER** flag that is set
  when the level reaches 0 dBFS.

A separate code path computes the **headroom** for a gain assistant:

```
peak = max(|L|, |R|)
if peak < fullscale:
    headroom_dB = min(20 * log10(fullscale / peak), 6.0)
else:
    headroom_dB = 0
```

It is meant to help set the gain so that the peak comes close to 0 dBFS but
stays below it.

## The meter in pshx500

The core formula and the OVER condition are the same. The ballistics are
`pshx500`'s own, modelled on the look of Sony's display:

- `fullscale` is the full scale of the integer container (2^15 or 2^31);
  silence shows as −120 dB.
- A block is one USB transfer (32 isochronous packets). The display shows the
  maximum since it was last read.
- Bar: instant attack, release 26 dB/s.
- Peak hold: held for 1.5 s, then falls at 12 dB/s, never below the bar.
- OVER: stays lit for 1.2 s.
- The meter measures the input signal before the software gain, as Sony's
  recorder does. For DSD it measures the PCM decoded at 44.1 kHz.
- While monitoring is on, the measurement is delayed by the monitoring latency,
  so that the display matches what you hear.
- The headroom assistant is not implemented.
