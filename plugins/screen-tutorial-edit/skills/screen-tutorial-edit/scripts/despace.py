"""Tighten EDL pieces by the audio itself (Whisper word boundaries are 0.1-0.5 s off).
Usage: PY despace.py <proj> [--write] [--max-gap 0.3] [--keep 0.2]
For every non-split piece:
- edges snap to the first/last voiced 10 ms bin (+-30 ms); a quiet >3.5 kHz tail (final s/sh/ts)
  up to 120 ms after the voice is kept, a breath after a gap is not;
- every internal pause longer than --max-gap is shortened to --keep by splitting the piece
  (later sub-pieces get "cont": true so the screen keeps running instead of jumping).
"lock_in"/"lock_out" edges are never moved. Dry run prints every change; --write saves
(a backup goes to check/edl_before_despace.json).
"""
import argparse
import shutil
from pathlib import Path

import numpy as np

import asr
from common import load_edl, save_edl

ap = argparse.ArgumentParser()
ap.add_argument("proj")
ap.add_argument("--write", action="store_true")
ap.add_argument("--max-gap", type=float, default=0.3)
ap.add_argument("--keep", type=float, default=0.2)
a = ap.parse_args()

proj = Path(a.proj)
edl = load_edl(proj)
cache = {}


def load(src):
    if src not in cache:
        db, hfdb = asr.energy(asr.read_wav16(proj / "audio" / f"{src}.wav"))
        floor, loud = np.percentile(db, 10), np.percentile(db, 95)
        voice = db > max(floor + 14, loud - 30)
        hiss = hfdb > np.percentile(hfdb, 10) + 12
        v = voice.copy()
        for k in range(1, len(v) - 2):  # close 1-2 bin holes inside words
            if not v[k] and v[k - 1] and (v[k + 1] or v[k + 2]):
                v[k] = True
        cache[src] = (v, hiss)
    return cache[src]


out, log = [], []
for k, p in enumerate(edl["pieces"]):
    if p["layout"] == "split":
        out.append(p)
        continue
    voice, hiss = load(p["src"])
    i0, i1 = int(round(p["in"] * 100)), min(int(round(p["out"] * 100)), len(voice))
    idx = [i for i in range(i0, i1) if voice[i]]
    if not idx:
        out.append(p)
        continue
    runs, s = [], idx[0]
    for u, v_ in zip(idx, idx[1:] + [None]):
        if v_ is None or v_ - u > 1:
            runs.append([s, u + 1])
            s = v_
    for r in runs:  # keep a contiguous fricative tail, max 120 ms
        e = r[1]
        while e < i1 and e - r[1] < 12 and hiss[e] and not voice[e]:
            e += 1
        r[1] = e
    groups = [list(runs[0])]
    for r in runs[1:]:
        if (r[0] - groups[-1][1]) / 100 > a.max_gap:
            groups.append(list(r))
        else:
            groups[-1][1] = r[1]
    half = a.keep / 2
    subs = []
    for g, (gs, ge) in enumerate(groups):
        q = dict(p)
        q["in"] = round(gs / 100 - (0.03 if g == 0 else min(half, 0.12)), 3)
        q["out"] = round(ge / 100 + (0.03 if g == len(groups) - 1 else half), 3)
        if g == 0 and p.get("lock_in"):
            q["in"] = p["in"]
        if g == len(groups) - 1 and p.get("lock_out"):
            q["out"] = p["out"]
        q["in"], q["out"] = max(q["in"], p["in"]), min(q["out"], p["out"])
        if g > 0:
            q.pop("screen_in", None)
            q.pop("lock_in", None)
            q.pop("zoom", None)  # zoom keys are relative to the piece start: re-add by hand if needed
            if p["layout"] in ("screen", "split"):
                q["cont"] = True
        if g < len(groups) - 1:
            q.pop("lock_out", None)
        subs.append(q)
    removed = (p["out"] - p["in"]) - sum(q["out"] - q["in"] for q in subs)
    if removed > 0.04:
        log.append(f"{k:3d} {p['src']} {p['in']:.2f}-{p['out']:.2f}: {len(subs)} part(s), -{removed:.2f}s  "
                   + " | ".join(f"{q['in']:.2f}-{q['out']:.2f}" for q in subs) + f"  {p.get('say', '')[:30]}")
        if len(subs) > 1 and p.get("zoom"):
            log.append("     ! piece had zoom keys: only the first part keeps them, check the others")
    out.extend(subs)

print("\n".join(log) or "no changes")
before = sum(p["out"] - p["in"] for p in edl["pieces"])
after = sum(p["out"] - p["in"] for p in out)
print(f"total {before:.1f}s -> {after:.1f}s")
if a.write:
    (proj / "check").mkdir(exist_ok=True)
    shutil.copy(proj / "edl.json", proj / "check" / "edl_before_despace.json")
    edl["pieces"] = out
    save_edl(proj, edl)
    print("written")
