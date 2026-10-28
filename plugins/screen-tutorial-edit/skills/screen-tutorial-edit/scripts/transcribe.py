"""Word-level transcription.
Usage: PY transcribe.py <proj> <src> [--lang he] [--model NAME]
   or: PY transcribe.py --file <audio/video> <out.json> [--lang he] [--vocab vocab.txt] [--clip t0 t1]
Project mode reads <proj>/audio/<src>.wav, writes <proj>/audio/<src>.json, uses <proj>/vocab.txt
and edl["language"] / edl["asr_model"] when present.
Language defaults: he -> ivrit-ai/whisper-large-v3-turbo-ct2, anything else -> large-v3-turbo.
"""
import argparse
import json
from pathlib import Path

from common import load_edl
import asr

ap = argparse.ArgumentParser()
ap.add_argument("args", nargs="*")
ap.add_argument("--file", action="store_true")
ap.add_argument("--lang")
ap.add_argument("--model")
ap.add_argument("--vocab")
ap.add_argument("--clip", nargs=2, type=float)
a = ap.parse_args()

if a.file:
    src, out = Path(a.args[0]), Path(a.args[1])
    edl, vocab = {}, a.vocab
else:
    proj, name = Path(a.args[0]), a.args[1]
    src, out = proj / "audio" / f"{name}.wav", proj / "audio" / f"{name}.json"
    edl = load_edl(proj)
    vocab = a.vocab or (proj / "vocab.txt" if (proj / "vocab.txt").exists() else None)
lang = a.lang or edl.get("language")
if not lang:
    raise SystemExit("give --lang (e.g. he, en) or set edl.json \"language\"")
prompt = ", ".join(l.strip().lstrip("﻿") for l in open(vocab, encoding="utf-8") if l.strip()) if vocab else None

x = asr.read_wav16(src)
off = 0.0
if a.clip:
    off = a.clip[0]
    x = x[int(a.clip[0] * asr.SR): int(a.clip[1] * asr.SR)]
segs = asr.transcribe(x, lang, a.model or edl.get("asr_model"), prompt, verbose=True)
if off:
    for s in segs:
        s["start"] += off
        s["end"] += off
        for w in s["words"]:
            w["s"] = round(w["s"] + off, 3)
            w["e"] = round(w["e"] + off, 3)
json.dump(segs, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", out)
