"""Checks to run on every version before showing it.
Usage: PY verify.py <proj> [--video out.mp4] [--gap 0.3]
1. Re-transcribes layers/voice.wav and prints it per piece with output timestamps (read it against
   the intended text: catches swallowed words and leftover repeats).
2. Word diff against the previous run (check/voice_prev.json): every removed/added word.
3. Flags adjacent repeated words and words longer than 0.6 s (stutters, stretched words, hidden repeats).
4. Silence scan: every pause longer than --gap s, mapped to the piece (inside a piece or at a cut).
5. With --video: ffprobe summary, and if edl has blur_templates, scans the output for leaks.
"""
import argparse
import difflib
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

import asr
from common import expand, load_edl, video_info

ap = argparse.ArgumentParser()
ap.add_argument("proj")
ap.add_argument("--video")
ap.add_argument("--gap", type=float, default=0.3)
a = ap.parse_args()
proj = Path(a.proj)
edl = load_edl(proj)
chk = proj / "check"
chk.mkdir(exist_ok=True)
cuts = json.load(open(proj / "layers" / "cuts.json", encoding="utf-8"))


def piece_at(t):
    for c in cuts:
        if c["start"] <= t < c["end"]:
            return c
    return cuts[-1]


x = asr.read_wav16(proj / "layers" / "voice.wav")
vocab = proj / "vocab.txt"
prompt = ", ".join(l.strip().lstrip("﻿") for l in open(vocab, encoding="utf-8") if l.strip()) if vocab.exists() else None
lang = edl.get("language")
if not lang:
    raise SystemExit('set edl.json "language" (e.g. "he", "en")')
segs = asr.transcribe(x, lang, edl.get("asr_model"), prompt)
ws = asr.words(segs)
latest, prev = chk / "voice_latest.json", chk / "voice_prev.json"
if latest.exists():
    shutil.copy(latest, prev)
json.dump(segs, open(latest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("== transcript per piece (output time) ==")
by = {}
for w in ws:
    by.setdefault(piece_at((w["s"] + w["e"]) / 2)["piece"], []).append(w)  # word starts run early
for c in cuts:
    txt = " ".join(w["w"] for w in by.get(c["piece"], []))
    print(f"{c['start']:7.2f} [{c['piece']:3d} {c['layout']:6s}] {txt}")

if prev.exists():
    print("\n== word diff vs previous version ==")
    old = asr.words(json.load(open(prev, encoding="utf-8")))
    sm = difflib.SequenceMatcher(a=[asr.norm(w["w"]) for w in old], b=[asr.norm(w["w"]) for w in ws], autojunk=False)
    n = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        n += 1
        t = ws[j1]["s"] if j1 < len(ws) else ws[-1]["e"]
        print(f"{t:7.2f} {op:7s} - {' '.join(w['w'] for w in old[i1:i2])} | + {' '.join(w['w'] for w in ws[j1:j2])}")
    print("no changes" if not n else f"{n} change(s): every one must be intended")

print("\n== possible stutters / hidden repeats ==")
for i, w in enumerate(ws):
    if i and asr.norm(w["w"]) and asr.norm(w["w"]) == asr.norm(ws[i - 1]["w"]):
        print(f"{w['s']:7.2f} repeated word: {ws[i - 1]['w']} {w['w']}")
    if asr.suspicious(w):
        print(f"{w['s']:7.2f} long word ({w['e'] - w['s']:.2f}s): {w['w']}  (check with cutcheck.py hear)")

print(f"\n== pauses > {a.gap}s ==")
db, _ = asr.energy(x, 0.04)
quiet = db < -36  # voice.wav is loudness-normalised, its noise floor sits around -42..-45 dB
i, found = 0, 0
while i < len(quiet):
    if quiet[i]:
        j = i
        while j < len(quiet) and quiet[j]:
            j += 1
        t0, t1 = i * 0.04, j * 0.04
        if t1 - t0 > a.gap and t0 > 0.05 and t1 < len(quiet) * 0.04 - 0.05:
            found += 1
            near = [c for c in cuts if t0 - 0.05 <= c["start"] <= t1 + 0.05]
            where = f"at cut into piece {near[0]['piece']}" if near else f"inside piece {piece_at(t0)['piece']}"
            print(f"{t0:7.2f}-{t1:7.2f} ({t1 - t0:.2f}s) {where}")
        i = j
    else:
        i += 1
print("none" if not found else f"{found} pause(s)")

if a.video:
    w, h, dur, au = video_info(a.video)
    print(f"\n== {a.video}: {w}x{h} {dur and round(dur, 2)}s audio={au}; cuts.json ends {cuts[-1]['end']}s ==")
    if edl.get("blur_templates"):
        import cv2
        tpl = [cv2.imread(str(expand(t, proj)), cv2.IMREAD_GRAYSCALE) for t in edl["blur_templates"]]
        x0, y0, x1, y1 = edl.get("blur_region", [1500, 0, 1920, 160])
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.video, "-vf", f"fps=10,crop={x1 - x0}:{y1 - y0}:{x0}:{y0},format=gray",
                              "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
        sz, k, leaks = (x1 - x0) * (y1 - y0), 0, []
        while True:
            b = p.stdout.read(sz)
            if len(b) < sz:
                break
            g = np.frombuffer(b, np.uint8).reshape(y1 - y0, x1 - x0)
            sc = max(cv2.minMaxLoc(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED))[1] for t in tpl)
            if sc > 0.6:
                leaks.append((k / 10, round(sc, 2)))
            k += 1
        print("private text visible at:", leaks[:30] if leaks else "nowhere (no template match > 0.6)")
