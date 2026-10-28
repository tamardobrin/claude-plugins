"""Inspect and verify individual cut points in a camera source (<proj>/audio/<src>.wav).
  words   <proj> <src> <t0> <t1>          transcript words in a range; flags suspiciously long words
                                          (they often hide a repetition, a pause or a stretched sound)
  profile <proj> <src> <t> [--before 0.3] [--after 0.35]
                                          20 ms RMS dB and >3.5 kHz dB around t, to place a cut by eye
  hear    <proj> <src> <a-b> [<c-d> ...] [--lang he]
                                          joins the ranges (15 ms fades, 0.4 s silence pads) and
                                          transcribes: is the last word whole? did the next word leak in?
  Example: hear proj cam 41.0-45.72 52.30-53.9  (= what the cut 45.72 -> 52.30 will sound like)
"""
import argparse
import json
from pathlib import Path

import numpy as np

import asr
from common import load_edl

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["words", "profile", "hear"])
ap.add_argument("proj")
ap.add_argument("src")
ap.add_argument("rest", nargs="+")
ap.add_argument("--before", type=float, default=0.3)
ap.add_argument("--after", type=float, default=0.35)
ap.add_argument("--lang")
a = ap.parse_args()
proj = Path(a.proj)
wav = proj / "audio" / f"{a.src}.wav"

if a.mode == "words":
    t0, t1 = float(a.rest[0]), float(a.rest[1])
    segs = json.load(open(proj / "audio" / f"{a.src}.json", encoding="utf-8"))
    for w in asr.words(segs):
        if w["e"] >= t0 and w["s"] <= t1:
            flag = "  <-- long, re-check" if asr.suspicious(w) else ""
            print(f"{w['s']:8.2f} {w['e']:8.2f}  {w['w']}{flag}")

elif a.mode == "profile":
    t = float(a.rest[0])
    x = asr.read_wav16(wav)
    db, hf = asr.energy(x, 0.02)
    floor, hfloor = np.percentile(db, 10), np.percentile(hf, 10)
    print(f"noise floor {floor:.0f} dB, HF floor {hfloor:.0f} dB.  # = level, + = >3.5 kHz above floor+12")
    for i in range(max(0, int((t - a.before) / 0.02)), min(len(db), int((t + a.after) / 0.02) + 1)):
        tt = i * 0.02
        bar = "#" * max(0, int((db[i] - floor) / 2))
        mark = "<-- t" if abs(tt - t) < 0.01 else ""
        print(f"{tt:8.2f} {db[i]:6.1f} {hf[i]:6.1f} {'+' if hf[i] > hfloor + 12 else ' '} {bar:30s} {mark}")

else:
    x = asr.read_wav16(wav)
    pad = np.zeros(int(0.4 * asr.SR), np.float32)
    parts, f = [pad], int(0.015 * asr.SR)
    for r in a.rest:
        s, e = (float(v) for v in r.split("-"))
        seg = x[int(s * asr.SR): int(e * asr.SR)].copy()
        seg[:f] *= np.linspace(0, 1, f)
        seg[-f:] *= np.linspace(1, 0, f)
        parts += [seg, pad]
    lang = a.lang or load_edl(proj).get("language")
    if not lang:
        raise SystemExit("give --lang or set edl.json \"language\"")
    joined = np.concatenate(parts)
    (proj / "check").mkdir(exist_ok=True)
    asr.write_wav16(proj / "check" / "hear.wav", joined)
    segs = asr.transcribe(joined, lang, load_edl(proj).get("asr_model"))
    print(" ".join(w["w"] for w in asr.words(segs)))
    print("(audio saved to check/hear.wav)")
