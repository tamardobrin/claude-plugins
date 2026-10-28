"""Optional captions, bottom centre, from the rendered voice (output timeline). A separate layer:
the cut video is never changed, captions are burned into a NEW file and/or exported as SRT.
  make  <proj> [--max-chars 38]      transcribe layers/voice.wav (reuses check/voice_latest.json from
                                     verify.py when it is newer) -> layers/captions.json, printed for review
  files <proj>                       captions.json -> layers/captions.srt (YouTube upload) + captions.ass
  burn  <proj> <in.mp4> <out.mp4>    files + burn into a copy (audio copied untouched)
captions.json = [{"s": 1.23, "e": 2.80, "text": "..."}], edit text/timing by hand, then files/burn.
Style from edl["captions"]: {"style": "outline" | "box", "font": "Arial", "size": 54,
"fonts_dir": "<folder with .ttf/.otf>", "margin_v": 50, "max_chars": 38}.
Side margins keep the text clear of the face circle (bottom-right by default).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from common import W, H, expand, load_edl, need

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["make", "files", "burn"])
ap.add_argument("proj")
ap.add_argument("io", nargs="*")
ap.add_argument("--max-chars", type=int)
a = ap.parse_args()
proj = Path(a.proj)
layers = proj / "layers"
edl = load_edl(proj)
cfg = {"style": "outline", "font": "Arial", "size": 54, "margin_v": 50, "max_chars": 38, **edl.get("captions", {})}
lang = edl.get("language", "en")
cap_path = layers / "captions.json"

# a caption should not end on these (move the word to the next caption)
CONNECTIVES = {
    "he": {"של", "את", "עם", "על", "אל", "אם", "או", "כי", "גם", "אבל", "אז", "שאני", "זה", "לא", "יותר", "הכי", "כמו", "בין", "כל", "אותו", "אותה", "שבה", "איזה", "ממש", "הוא", "היא"},
    "en": {"the", "a", "an", "of", "to", "and", "or", "with", "for", "in", "on", "at", "but", "so", "if", "that", "my", "your", "is"},
}.get(lang, set())


CLAUSE = {"he": {"אז", "אם", "הוא", "היא", "כי", "אבל", "שאני", "וזה", "ואז"},
          "en": {"and", "but", "so", "because", "then", "which", "when", "if"}}.get(lang, set())


def STARTS(w):
    """Word that opens a new clause: a good place to start a new caption line."""
    n = w.strip(".,?!")
    return n in CLAUSE or (lang == "he" and n.startswith("ו") and len(n) > 3)


def clean(t):
    """Whisper spacing artifacts: ג 'נרט -> ג'נרט, 2 .5 -> 2.5, ב -AI -> ב-AI."""
    t = re.sub(r"\s+'", "'", t)
    t = re.sub(r"(\d) \.(\d)", r"\1.\2", t)
    t = re.sub(r"(\S) -(\w)", r"\1-\2", t)
    return re.sub(r"\s+", " ", t).strip()


def make():
    import asr
    voice = layers / "voice.wav"
    latest = proj / "check" / "voice_latest.json"
    if latest.exists() and latest.stat().st_mtime > voice.stat().st_mtime:
        segs = json.load(open(latest, encoding="utf-8"))
    else:
        vocab = proj / "vocab.txt"
        prompt = ", ".join(l.strip().lstrip("﻿") for l in open(vocab, encoding="utf-8") if l.strip()) if vocab.exists() else None
        segs = asr.transcribe(asr.read_wav16(voice), lang, edl.get("asr_model"), prompt)
    ws = []
    for w in asr.words(segs):  # Whisper splits ג'ינרט into "ג" + "'ינרט": glue such pieces back
        if ws and w["w"][:1] in "'\".," and len(w["w"]) > 1 and w["s"] - ws[-1]["e"] < 0.1:
            ws[-1] = {**ws[-1], "w": ws[-1]["w"] + w["w"], "e": w["e"]}
        elif w["w"]:
            ws.append(dict(w))
    cuts = [c["start"] for c in json.load(open(layers / "cuts.json", encoding="utf-8"))][1:]
    end_total = json.load(open(layers / "cuts.json", encoding="utf-8"))[-1]["end"]
    maxc = a.max_chars or cfg["max_chars"]

    # 1) phrases: break at sentence ends, commas, pauses > 0.35 s and every cut
    phrases, cur = [], []
    for w in ws:
        if cur:
            prev = cur[-1]
            if (any(prev["e"] - 0.02 <= c <= w["s"] + 0.02 for c in cuts) or prev["w"][-1] in ".?!:;,"
                    or w["s"] - prev["e"] > 0.35):
                phrases.append(cur)
                cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)

    # 2) long phrases -> balanced lines (DP): each <= maxc, prefer breaking before a clause starter,
    #    never end a line on a connective
    def length(g):
        return len(clean(" ".join(x["w"] for x in g)))

    groups = []
    for ph in phrases:
        if length(ph) <= maxc:
            groups.append(ph)
            continue
        n = len(ph)
        parts = -(-length(ph) // maxc)
        target = min(length(ph) / parts, maxc * 0.75)  # room to move breaks onto clause starts
        best = [(0.0, None)] + [(float("inf"), None)] * n
        for j in range(1, n + 1):
            for i in range(j):
                L = length(ph[i:j])
                if L > maxc and j - i > 1:
                    continue
                c = best[i][0] + (L - target) ** 2
                if j < n and asr.norm(ph[j - 1]["w"]) in CONNECTIVES:
                    c += 400
                if j < n and STARTS(ph[j]["w"]):
                    c -= 150
                if c < best[j][0]:
                    best[j] = (c, i)
        cut_at, j = [], n
        while j > 0:
            cut_at.append(j)
            j = best[j][1]
        prev_j = 0
        for j in reversed(cut_at):
            groups.append(ph[prev_j:j])
            prev_j = j

    caps = []
    for i, g in enumerate(groups):
        s, e = g[0]["s"], g[-1]["e"] + 0.12
        nxt = groups[i + 1][0]["s"] if i + 1 < len(groups) else end_total
        wall = min([c for c in cuts if c >= g[-1]["e"] - 0.02] + [end_total])  # never cross a cut
        if e - s < 0.7:
            e = s + 0.7
        if nxt - e < 0.3:
            e = nxt  # no flicker between captions that follow each other
        e = min(e, nxt, wall)
        if caps:
            s = max(s, caps[-1]["e"])
        caps.append({"s": round(s, 2), "e": round(e, 2), "text": clean(" ".join(w["w"] for w in g))})
    json.dump(caps, open(cap_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    for c in caps:
        print(f"{c['s']:7.2f}-{c['e']:7.2f}  {c['text']}")
    print(f"{len(caps)} captions -> {cap_path}\nRead them against the intended text and fix Whisper's spelling "
          "(tool names, numbers) in captions.json before burning.")


def ts(t, srt):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",") if srt else f"{int(h)}:{int(m):02d}:{s:05.2f}"


RTL = lang in {"he", "ar", "fa", "ur", "yi"}


def files():
    caps = json.load(open(cap_path, encoding="utf-8"))
    # libass lays lines out left-to-right: in Hebrew the comma lands on the wrong side and an English
    # word ("ב-Seedance") jumps to the far end. RLE ... PDF forces a right-to-left line.
    ass_t = (lambda t: "‫" + t + "‬") if RTL else (lambda t: t)
    srt_t = (lambda t: "‏" + t + "‏") if RTL else (lambda t: t)
    with open(layers / "captions.srt", "w", encoding="utf-8") as f:
        for i, c in enumerate(caps, 1):
            f.write(f"{i}\n{ts(c['s'], True)} --> {ts(c['e'], True)}\n{srt_t(c['text'])}\n\n")
    side = 340  # 1920 - 340 = 1580 = left edge of the default face circle
    if cfg["style"] == "box":   # opaque box: libass fills it with OutlineColour
        border, outline, shadow, oc = 3, 14, 0, "&H60000000"
    else:                       # white text, black outline, soft shadow
        border, outline, shadow, oc = 1, 3, 1.5, "&H00000000"
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,{cfg['font']},{cfg['size']},&H00FFFFFF,&H00FFFFFF,{oc},&H80000000,-1,0,0,0,100,100,0,0,"
            f"{border},{outline},{shadow},2,{side},{side},{cfg['margin_v']},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    with open(layers / "captions.ass", "w", encoding="utf-8") as f:
        f.write(head)
        for c in caps:
            f.write(f"Dialogue: 0,{ts(c['s'], False)},{ts(c['e'], False)},Cap,,0,0,0,,{ass_t(c['text'])}\n")
    print("wrote", layers / "captions.srt", "and", layers / "captions.ass")


def burn(src, out):
    need("ffmpeg")
    files()
    vf = "subtitles=captions.ass"
    if cfg.get("fonts_dir"):  # copied next to the .ass so the filter needs no escaped absolute paths
        fd = layers / "fonts"
        fd.mkdir(exist_ok=True)
        for f in expand(cfg["fonts_dir"], proj).glob("*.[ot]tf"):
            shutil.copy(f, fd)
        vf += ":fontsdir=fonts"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.abspath(src), "-vf", vf, "-c:v", "libx264",
                    "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
                    "-movflags", "+faststart", os.path.abspath(out)], check=True, cwd=layers)
    print("burned ->", out)


if a.mode == "make":
    make()
elif a.mode == "files":
    files()
else:
    burn(a.io[0], a.io[1])
