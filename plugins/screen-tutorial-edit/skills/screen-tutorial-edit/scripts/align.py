"""Find where one recording sits inside another by audio cross-correlation.
Usage: PY align.py <a.wav> <b.wav> [--search 120]
Prints: b starts at <offset> s on a's timeline. Use it for camera clips that are one take split
into overlapping files (offset = where b begins in a). It matches the waveform, so both must
contain the SAME recorded audio (not two different microphones).
Inputs: any audio/video (converted to 16 kHz mono). Peak ratio = best match / best other match;
tested: real overlaps 8-13, unrelated clips 1.1-1.3.
"""
import argparse

import numpy as np

import asr

ap = argparse.ArgumentParser()
ap.add_argument("a")
ap.add_argument("b")
ap.add_argument("--search", type=float, default=120, help="seconds of b's head to match")
args = ap.parse_args()

R = 8000  # correlate the waveform at 8 kHz: identical audio gives a sharp peak
xa, xb = asr.read_wav16(args.a), asr.read_wav16(args.b)


def env(x):
    k = asr.SR // R
    x = x[: len(x) // k * k].reshape(-1, k).mean(1)
    return (x - x.mean()) / (x.std() + 1e-9)


ea, eb = env(xa), env(xb)[: int(args.search * R)]
n = 1 << int(np.ceil(np.log2(len(ea) + len(eb))))
c = np.fft.irfft(np.fft.rfft(ea, n) * np.conj(np.fft.rfft(eb, n)), n)
lag = int(np.argmax(c))
if lag > n // 2:
    lag -= n
pk = int(np.argmax(c))
rest = c.copy()
rest[max(0, pk - R): pk + R] = -np.inf  # best other match at least 1 s away
conf = c[pk] / max(rest.max(), 1e-9)
print(f"b starts at {lag / R:.3f} s on a's timeline (peak ratio {conf:.2f}; "
      f"{'clear match' if conf > 1.5 else 'NO clear match: check by ear/transcript'})")
