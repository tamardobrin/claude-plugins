"""Timestamped contact sheets to LOOK at footage (use the Read tool on the JPG).
  range <video> <t0> <t1> [--every 2]          a frame every N s (map a screen recording, find private info)
  times <video> <t> [<t> ...]                  specific moments (zooms, synced actions)
  cuts  <proj> <video>                         rendered video: last frame before / first after every cut
  options: --out sheet.jpg  --cols 5  --width 400  --circle (outline where the face circle lands)
           --zoom x,y,w (outline a zoom rect)
Frames are grabbed one by one with ffmpeg -ss, labels drawn with Pillow (no font paths needed).
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from common import W, H, load_edl, video_info

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["range", "times", "cuts"])
ap.add_argument("args", nargs="+")
ap.add_argument("--every", type=float, default=2.0)
ap.add_argument("--out", default="sheet.jpg")
ap.add_argument("--cols", type=int, default=5)
ap.add_argument("--width", type=int, default=400)
ap.add_argument("--circle", action="store_true")
ap.add_argument("--zoom")
a = ap.parse_args()

labels = []
if a.mode == "range":
    video, t0, t1 = a.args[0], float(a.args[1]), float(a.args[2])
    ts = list(np.arange(t0, t1 + 1e-6, a.every))
    labels = [f"{t:.1f}" for t in ts]
elif a.mode == "times":
    video, ts = a.args[0], [float(t) for t in a.args[1:]]
    labels = [f"{t:.2f}" for t in ts]
else:
    proj, video = Path(a.args[0]), a.args[1]
    cuts = json.load(open(proj / "layers" / "cuts.json", encoding="utf-8"))
    ts = []
    for c in cuts[1:]:
        ts += [max(0, c["start"] - 0.07), c["start"] + 0.04]
        labels += [f"{c['start']:.2f} <", f"> p{c['piece']} {c['layout']}"]

vw, vh, _, _ = video_info(video)
tw = a.width
th = round(vh * tw / vw / 2) * 2
font = ImageFont.load_default(size=max(12, tw // 18))
tiles = []
for t, lab in zip(ts, labels):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale={tw}:{th}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    if len(r.stdout) < tw * th * 3:
        continue
    im = Image.fromarray(np.frombuffer(r.stdout[: tw * th * 3], np.uint8).reshape(th, tw, 3))
    d = ImageDraw.Draw(im)
    s = tw / W
    if a.circle:
        c = load_edl(a.args[0]).get("circle", {}) if a.mode == "cuts" else {}
        dd, m = c.get("d", 300), c.get("margin", 40)
        x0 = W - m - dd if c.get("corner", "br") == "br" else m
        d.ellipse([x0 * s, (H - m - dd) * s, (x0 + dd) * s, (H - m) * s], outline=(255, 0, 255), width=2)
    if a.zoom:
        zx, zy, zw = (float(v) for v in a.zoom.split(","))
        d.rectangle([zx * s, zy * s, (zx + zw) * s, (zy + zw * 9 / 16) * s], outline=(0, 255, 255), width=2)
    d.rectangle([0, 0, tw, font.size + 6], fill=(0, 0, 0))
    d.text((4, 2), lab, fill=(255, 220, 0), font=font)
    tiles.append(im)
if not tiles:
    raise SystemExit("no frames grabbed")
cols = min(a.cols, len(tiles))
rows = -(-len(tiles) // cols)
sheet = Image.new("RGB", (cols * tw + (cols - 1) * 4, rows * th + (rows - 1) * 4), (40, 40, 40))
for i, im in enumerate(tiles):
    sheet.paste(im, ((i % cols) * (tw + 4), (i // cols) * (th + 4)))
sheet.save(a.out, quality=88)
print(a.out, len(tiles), "frames")
