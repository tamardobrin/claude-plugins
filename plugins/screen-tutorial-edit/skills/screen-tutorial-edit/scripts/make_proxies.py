"""Constant-frame-rate 1920x1080 proxies + 16 kHz analysis audio. Raw files are only read.
Usage: PY make_proxies.py <proj> --cam cam=<file> [--cam vid2=<file> ...]
                                 [--screen screen=<file> ...] [--crop-y N] [--fps 30]
Camera  -> <cache>/<name>.mov (H.264 + PCM audio) and <proj>/audio/<name>.wav (16k mono).
Screen  -> <cache>/<name>.mp4, scaled uniformly to 1920 wide (never squashed), then:
           taller than 1080 (16:10 etc.): crop 1080 rows starting at --crop-y
           (default: the bottom 1080 rows = drop the OS bar / tabs / URL bar on top);
           shorter: padded black top and bottom.
           Always look at a frame of the result: the crop must not cut UI the viewer needs.
Updates edl.json: cache, fps, sources, screen (first screen), pieces kept.
Why proxies: phone video and webm screen recordings are variable frame rate and seek badly;
frame index = time * fps only holds on a CFR proxy.
"""
import argparse
import sys
from pathlib import Path

from common import W, H, cache_dir, load_edl, need, run, save_edl, video_info

ap = argparse.ArgumentParser()
ap.add_argument("proj")
ap.add_argument("--cam", action="append", default=[])
ap.add_argument("--screen", action="append", default=[])
ap.add_argument("--crop-y", type=int)
ap.add_argument("--fps", type=int)
ap.add_argument("--force", action="store_true", help="rebuild proxies that already exist")
a = ap.parse_args()
need("ffmpeg")

proj = Path(a.proj)
(proj / "audio").mkdir(parents=True, exist_ok=True)
(proj / "layers").mkdir(exist_ok=True)
(proj / "check").mkdir(exist_ok=True)
edl = load_edl(proj)
fps = a.fps or edl.get("fps", 30)
cache = cache_dir(proj, edl)
edl.setdefault("sources", {})


def parse(spec):
    if "=" not in spec:
        sys.exit(f"use name=path, got {spec}")
    n, p = spec.split("=", 1)
    p = Path(p)
    if not p.exists():
        sys.exit(f"missing {p}")
    return n, p


for spec in a.cam:
    name, path = parse(spec)
    w, h, dur, has_audio = video_info(path)
    print(f"cam {name}: {w}x{h} {round(dur, 1) if dur else '?'}s audio={has_audio}")
    if h > w:
        sys.exit(f"{name} is portrait ({w}x{h}). A 16:9 tutorial needs landscape camera footage: "
                 "ask the user how to handle it before doing anything (never stretch).")
    if not has_audio:
        sys.exit(f"{name} has no audio; the camera audio is the voice track")
    if abs(w / h - 16 / 9) > 0.02:
        print(f"WARNING {name} is not 16:9; it will be pillar/letterboxed. Ask the user if that is OK.")
    out = cache / f"{name}.mov"
    if a.force or not out.exists():
        run(["ffmpeg", "-v", "error", "-stats", "-y", "-i", path, "-map", "0:v:0", "-map", "0:a:0",
             "-vf", f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p",
             "-c:a", "pcm_s16le", out])
    run(["ffmpeg", "-v", "error", "-y", "-i", path, "-map", "0:a:0", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", proj / "audio" / f"{name}.wav"])
    edl["sources"][name] = {"kind": "cam", "raw": str(path.resolve()), "proxy": out.name}

for spec in a.screen:
    name, path = parse(spec)
    w, h, dur, _ = video_info(path)
    sh = round(h * W / w / 2) * 2
    if sh > H:
        y = sh - H if a.crop_y is None else a.crop_y
        fit = f"crop={W}:{H}:0:{y}"
        note = f"scaled to {W}x{sh}, cropped rows {y}-{y + H}"
    else:
        fit = f"pad={W}:{H}:0:(oh-ih)/2"
        note = f"scaled to {W}x{sh}, padded"
    print(f"screen {name}: {w}x{h} {round(dur, 1) if dur else '?'}s -> {note}")
    out = cache / f"{name}.mp4"
    if a.force or not out.exists():
        run(["ffmpeg", "-v", "error", "-stats", "-y", "-i", path, "-an",
             "-vf", f"fps={fps},scale={W}:{sh}:flags=lanczos,{fit},setsar=1",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", out])
    edl["sources"][name] = {"kind": "screen", "raw": str(path.resolve()), "proxy": out.name, "fit": note}
    edl.setdefault("screen", out.name)

edl["fps"] = fps
edl.setdefault("cache", str(cache))
edl.setdefault("pieces", [])
save_edl(proj, edl)
print("cache:", cache)
print("edl.json updated")
