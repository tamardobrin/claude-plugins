"""Render a 16:9 tutorial from <proj>/edl.json.
Usage: PY render_tutorial.py <proj> <out.mp4> [--pieces 5-9] [--audio-only]
Layouts per piece: full (camera full frame), screen (screen recording + face circle),
split (screen left half | camera right half).
- Face circle: face tracked per piece (MediaPipe, OpenCV fallback), smoothed, square crop around it.
- full -> screen: the camera frame shrinks into the circle (edl "transition" s); screen -> full: reverse.
- Screen time per piece: "screen_in" > "cont" (continue previous screen piece) > in + screen_offset[src].
- "zoom": [[t, "name" | x, y, w], ...] keyframes from piece start (screen coords, h = w*9/16),
  smoothstep between keys; names come from edl["zooms"].
- "blur": [[x, y, w, h], ...] per piece, screen coords, pixelated before zoom.
- edl["blur_templates"]: grayscale PNG crops of private text (account name...) searched in
  edl["blur_region"] [x0, y0, x1, y1] of every screen frame and pixelated wherever found.
- Circle position: edl["circle"] {"d", "margin", "corner": "br"|"bl", "alt_x"}; per piece
  "circle_x": "alt" or a number; edl["dodge"] slides it to alt_x while a UI element sits under it.
Writes <proj>/layers/voice.wav (camera audio only, loudness-normalised) and layers/cuts.json.
"""
import json
import subprocess
import sys
from pathlib import Path

from common import W, H, cache_dir, expand, load_edl, models_dir, need, quiet_mediapipe

quiet_mediapipe()
import cv2  # noqa: E402
import numpy as np  # noqa: E402

need("ffmpeg")
proj, out = Path(sys.argv[1]), sys.argv[2]
edl = load_edl(proj)
FPS = edl.get("fps", 30)
cache = cache_dir(proj, edl)
pieces = edl["pieces"]
sel = range(len(pieces))
if "--pieces" in sys.argv:
    a, b = sys.argv[sys.argv.index("--pieces") + 1].split("-")
    sel = range(int(a), int(b) + 1)
layers = proj / "layers"
layers.mkdir(exist_ok=True)

C = {"d": 300, "margin": 40, "corner": "br", "alt_x": None, **edl.get("circle", {})}
D, MARGIN = int(C["d"]), int(C["margin"])
CX = W - MARGIN - D // 2 if C["corner"] == "br" else MARGIN + D // 2
CY = H - MARGIN - D // 2
ALT_X = C["alt_x"] if C["alt_x"] is not None else (CX - D - 2 * MARGIN if C["corner"] == "br" else CX + D + 2 * MARGIN)
SW, SH = 480, 270  # analysis size
LOUD = {"i": -14, "tp": -1.5, **edl.get("loudness", {})}


def cam_file(src):
    return cache / edl.get("sources", {}).get(src, {}).get("proxy", f"{src}.mov")


# ---- face detection -------------------------------------------------------------------
_fd = None


def detect_face(f):
    """Largest face in an RGB 480x270 frame -> (cx, cy, h) in analysis pixels, or None."""
    global _fd
    if _fd is None:
        model = models_dir() / "blaze_face_short_range.tflite"
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core.base_options import BaseOptions
            if not model.exists():
                raise FileNotFoundError(model)
            det = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(model)), min_detection_confidence=0.5))

            def run_mp(img):
                r = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img))).detections
                return [(d.bounding_box.origin_x, d.bounding_box.origin_y, d.bounding_box.width,
                         d.bounding_box.height) for d in r]
            _fd = run_mp
        except Exception as e:
            print("face: OpenCV fallback (", e, ")", flush=True)
            casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

            def run_cv(img):
                g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                return list(casc.detectMultiScale(g, 1.1, 5, minSize=(24, 24)))
            _fd = run_cv
    boxes = _fd(f)
    if not len(boxes):
        return None
    x, y, w, h = max(boxes, key=lambda b: b[2])
    return x + w / 2, y + h / 2, h


def reader(path, t0, n, size=(W, H)):
    w, h = size
    vf = [] if size == (W, H) else ["-vf", f"scale={w}:{h}"]
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", str(path), "-frames:v", str(n),
                          *vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    last = None
    for _ in range(n):
        buf = p.stdout.read(w * h * 3)
        if len(buf) == w * h * 3:
            last = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        yield last  # repeat the last frame if the source runs short
    p.stdout.close()
    p.wait()


def smooth(x, win):
    k = np.ones(win) / win
    pad = np.pad(x, (win // 2, win - 1 - win // 2), mode="edge")
    return np.convolve(pad, k, mode="valid")


def face_track(path, t0, n):
    """Per-frame face centre (output coords) and one crop side for the piece."""
    cx, cy, hs = np.full(n, np.nan), np.full(n, np.nan), []
    s = W / SW
    for i, f in enumerate(reader(path, t0, n, (SW, SH))):
        if i % 3 or f is None:
            continue
        r = detect_face(f)
        if r:
            cx[i], cy[i] = r[0] * s, r[1] * s
            hs.append(r[2] * s)
    ok = ~np.isnan(cx)
    if not ok.any():
        print("  no face found, centring", flush=True)
        return np.full(n, W / 2), np.full(n, H * 0.4), 700
    idx = np.arange(n)
    cx = np.interp(idx, idx[ok], cx[ok])
    cy = np.interp(idx, idx[ok], cy[ok])
    side = float(np.clip(np.median(hs) * 2.3, 520, 1000))  # 2.0 cut foreheads
    return smooth(cx, 21), smooth(cy, 21), side


# ---- circle dodge ---------------------------------------------------------------------
PRESETS = {
    # Higgsfield image page: yellow "Turn to video" / Download buttons in the bottom-right corner
    "higgsfield": {"rect": [1608, 872, 296, 148], "rgb_min": [171, 191, 0], "rgb_max": [255, 255, 119],
                   "min_frac": 0.022, "alt_x": 1443},
}


def dodge_x(path, t0, n, base_x):
    """edl["dodge"]: preset name or {"rect":[x,y,w,h], "rgb_min":[r,g,b], "rgb_max":[r,g,b], "min_frac"}.
    Where enough pixels in rect match the colour range, the circle glides to alt_x."""
    cfg = edl.get("dodge")
    if not cfg:
        return np.full(n, float(base_x))
    cfg = PRESETS[cfg] if isinstance(cfg, str) else cfg
    s = SW / W
    x, y, w, h = [int(round(v * s)) for v in cfg["rect"]]
    lo, hi = np.array(cfg["rgb_min"]), np.array(cfg["rgb_max"])
    fl = np.zeros(n)
    for i, f in enumerate(reader(path, t0, n, (SW, SH))):
        if f is None:
            continue
        r = f[y:y + h, x:x + w].astype(int)
        m = np.all((r >= lo) & (r <= hi), axis=-1)
        fl[i] = m.mean() > cfg.get("min_frac", 0.02)
    fl = smooth(fl, 15) > 0.5
    return smooth(np.where(fl, cfg.get("alt_x", ALT_X), base_x).astype(float), 11)


# ---- privacy blur ---------------------------------------------------------------------
TEMPL = [cv2.imread(str(expand(t, proj)), cv2.IMREAD_GRAYSCALE) for t in edl.get("blur_templates", [])]
for t, im in zip(edl.get("blur_templates", []), TEMPL):
    if im is None:
        sys.exit(f"blur template not found: {t}")
BX0, BY0, BX1, BY1 = edl.get("blur_region", [W - 420, 0, W, 160])


def pixelate(frame, x, y, w, h):
    x, y = max(0, int(x)), max(0, int(y))
    w, h = min(int(w), W - x), min(int(h), H - y)
    if w < 2 or h < 2:
        return
    reg = frame[y:y + h, x:x + w]
    small = cv2.resize(reg, (max(1, w // 10), max(1, h // 10)), interpolation=cv2.INTER_AREA)
    frame[y:y + h, x:x + w] = cv2.GaussianBlur(cv2.resize(small, (w, h)), (0, 0), 3)


def hide_private(frame, st, rects):
    for r in rects:
        pixelate(frame, *r)
    if TEMPL:
        g = cv2.cvtColor(np.ascontiguousarray(frame[BY0:BY1, BX0:BX1]), cv2.COLOR_RGB2GRAY)
        best = (0.0, None, None)
        for t in TEMPL:
            _, mx, _, ml = cv2.minMaxLoc(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED))
            if mx > best[0]:
                best = (mx, ml, t.shape)
        if best[0] > edl.get("blur_threshold", 0.6):
            (x, y), (h, w) = best[1], best[2]
            st["box"], st["ttl"] = (BX0 + x - 8, BY0 + y - 5, w + 16, h + 10), 10  # hold through fades
    if st.get("ttl", 0) > 0:
        st["ttl"] -= 1
        pixelate(frame, *st["box"])


# ---- zoom -----------------------------------------------------------------------------
def zoom_rects(keys, n):
    if not keys:
        return None
    zs = edl.get("zooms", {})
    keys = [[k[0], *zs[k[1]]] if isinstance(k[1], str) else k for k in keys]
    res = []
    for i in range(n):
        t = i / FPS
        if t <= keys[0][0]:
            r = keys[0][1:]
        elif t >= keys[-1][0]:
            r = keys[-1][1:]
        else:
            j = max(j for j in range(len(keys)) if keys[j][0] <= t)
            a_, b_ = keys[j], keys[j + 1]
            u = (t - a_[0]) / (b_[0] - a_[0])
            u = u * u * (3 - 2 * u)
            r = [a_[c] + u * (b_[c] - a_[c]) for c in (1, 2, 3)]
        res.append(r)
    return res


def apply_zoom(frame, r):
    x, y, w = r
    h = w * H / W
    x, y = float(np.clip(x, 0, W - w)), float(np.clip(y, 0, H - h))
    if w >= W - 0.5:
        return frame
    m = np.array([[W / w, 0, -x * W / w], [0, H / h, -y * H / h]], np.float32)
    return cv2.warpAffine(frame, m, (W, H), flags=cv2.INTER_CUBIC)


# ---- circle + morph -------------------------------------------------------------------
yy, xx = np.mgrid[0:D, 0:D]
rr = np.sqrt((xx - (D - 1) / 2) ** 2 + (yy - (D - 1) / 2) ** 2)
CIRCLE = np.clip(D / 2 - rr, 0, 1)[..., None]
RING = np.clip(1 - np.abs(rr - (D / 2 - 2.5)) / 2.5, 0, 1)[..., None]
PAD = 30
sh = np.zeros((D + 2 * PAD, D + 2 * PAD), np.float32)
cv2.circle(sh, (D // 2 + PAD, D // 2 + PAD + 6), D // 2, 1.0, -1, cv2.LINE_AA)
SHADOW = (cv2.GaussianBlur(sh, (0, 0), 12) * 0.45)[..., None]


def blend(dst, x0, y0, img, alpha):
    h, w = alpha.shape[:2]
    ax0, ay0 = max(0, -x0), max(0, -y0)
    bx0, by0 = max(0, x0), max(0, y0)
    bx1, by1 = min(W, x0 + w), min(H, y0 + h)
    if bx1 <= bx0 or by1 <= by0:
        return
    a_ = alpha[ay0:ay0 + by1 - by0, ax0:ax0 + bx1 - bx0]
    reg = dst[by0:by1, bx0:bx1].astype(np.float32)
    src = img if np.isscalar(img) else img[ay0:ay0 + by1 - by0, ax0:ax0 + bx1 - bx0]
    dst[by0:by1, bx0:bx1] = (reg * (1 - a_) + src * a_).astype(np.uint8)


def cam_square(cam, cx, cy, side):
    s = int(side)
    x0 = int(np.clip(cx - s / 2, 0, W - s))
    y0 = int(np.clip(cy - s / 2, 0, H - s))
    return cv2.resize(cam[y0:y0 + s, x0:x0 + s], (D, D), interpolation=cv2.INTER_AREA)


def put_circle(frame, cam, cx, cy, side, pos_x):
    x0, y0 = int(pos_x - D / 2), CY - D // 2
    blend(frame, x0 - PAD, y0 - PAD, 0.0, SHADOW)
    blend(frame, x0, y0, cam_square(cam, cx, cy, side), CIRCLE)
    blend(frame, x0, y0, 255.0, RING * CIRCLE)


def morph(frame, cam, cx, cy, side, pos_x, p):
    """p=0: camera fills the frame; p=1: camera is the circle (rounded-rect SDF mask)."""
    e = p * p * (3 - 2 * p)
    tx, ty = pos_x - D / 2, CY - D / 2
    dx, dy = e * tx, e * ty
    dw, dh = W + e * (D - W), H + e * (D - H)
    sh_ = H + e * (side - H)
    sw_ = sh_ * dw / dh
    scx = W / 2 + e * (cx - W / 2)
    scy = H / 2 + e * (cy - H / 2)
    sx0 = float(np.clip(scx - sw_ / 2, 0, W - sw_))
    sy0 = float(np.clip(scy - sh_ / 2, 0, H - sh_))
    iw, ih = max(2, int(round(dw))), max(2, int(round(dh)))
    m = np.array([[iw / sw_, 0, -sx0 * iw / sw_], [0, ih / sh_, -sy0 * ih / sh_]], np.float32)
    img = cv2.warpAffine(cam, m, (iw, ih), flags=cv2.INTER_AREA if e > 0.5 else cv2.INTER_LINEAR)
    r = e * D / 2
    gy, gx = np.mgrid[0:ih, 0:iw].astype(np.float32)
    qx = np.abs(gx - (iw - 1) / 2) - (iw / 2 - r)
    qy = np.abs(gy - (ih - 1) / 2) - (ih / 2 - r)
    sdf = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0) - r
    a_ = np.clip(0.5 - sdf, 0, 1)[..., None]
    blend(frame, int(round(dx)), int(round(dy)), img, a_)
    if e > 0.02:
        ring = np.clip(1 - np.abs(sdf + 2.5) / 2.5, 0, 1)[..., None] * a_ * e
        blend(frame, int(round(dx)), int(round(dy)), 255.0, ring)


# ---- timeline (screen sync is resolved over ALL pieces so --pieces previews stay in sync) --
plan, t, prev_screen_end, prev_layout = [], 0.0, None, None
t_all = 0.0  # frame counts are rounded cumulatively so the total length stays exact
for k, p in enumerate(pieces):
    n = round((t_all + p["out"] - p["in"]) * FPS) - round(t_all * FPS)
    t_all += p["out"] - p["in"]
    s_in = None
    if p["layout"] in ("screen", "split"):
        if "screen_in" in p:
            s_in = p["screen_in"]
        elif p.get("cont") and prev_screen_end is not None:
            s_in = prev_screen_end
        else:
            s_in = p["in"] + edl.get("screen_offset", {}).get(p["src"], 0.0)
        prev_screen_end = s_in + n / FPS
    if k in sel:
        plan.append(dict(k=k, p=p, n=n, start=t, s_in=s_in,
                         trans_in=p["layout"] == "screen" and prev_layout == "full",
                         trans_out=p["layout"] == "full" and prev_layout == "screen"))
        prev_layout = p["layout"]
        t += n / FPS
total = t
json.dump([dict(piece=q["k"], start=round(q["start"], 3), end=round(q["start"] + q["n"] / FPS, 3),
                layout=q["p"]["layout"], src=q["p"]["src"], src_in=q["p"]["in"], say=q["p"].get("say", ""))
           for q in plan],
          open(layers / "cuts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)

# ---- audio: camera only, per-piece length = video frame count (no A/V drift) ------------
srcs = sorted({q["p"]["src"] for q in plan})
inputs = sum([["-i", str(cam_file(s))] for s in srcs], [])
fc, labels = "", ""
for i, q in enumerate(plan):
    p = q["p"]
    d = q["n"] / FPS
    fo = p.get("fade_out", 0.015)
    fc += (f"[{srcs.index(p['src'])}:a]atrim={p['in']:.3f}:{p['in'] + d:.3f},asetpts=PTS-STARTPTS,"
           f"afade=t=in:d=0.015,afade=t=out:st={max(0.0, d - fo):.3f}:d={fo}[a{i}];")
    labels += f"[a{i}]"
fc += f"{labels}concat=n={len(plan)}:v=0:a=1,aformat=channel_layouts=mono[a]"
raw = layers / "voice_raw.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", fc, "-map", "[a]",
                "-c:a", "pcm_s24le", str(raw)], check=True)
# loudness: level to -20 LUFS, gentle 3:1 compression, gain to target, peak limiter.
# (single-pass loudnorm landed at -16.3 for a -14 target; phone voice has a ~22 dB crest factor)
def lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    return float(json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])["input_i"])


comp = layers / "voice_comp.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
                f"volume={-20 - lufs(raw):.2f}dB,acompressor=threshold=0.05:ratio=3:attack=5:release=100",
                "-c:a", "pcm_s24le", str(comp)], check=True)
gain = LOUD["i"] - lufs(comp) + 0.3  # the limiter takes back a little
lim = 10 ** ((LOUD["tp"] - 0.5) / 20)  # sample-peak ceiling, 0.5 dB under the true-peak target
voice = layers / "voice.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(comp), "-af",
                f"volume={gain:.2f}dB,aresample=192000,alimiter=limit={lim:.4f}:attack=2:release=50:level=false,"
                f"aresample=48000", "-c:a", "pcm_s16le", str(voice)], check=True)
raw.unlink()
comp.unlink()
print(f"voice {voice}  {total:.2f}s", flush=True)
if "--audio-only" in sys.argv:
    sys.exit(0)

# ---- video ----------------------------------------------------------------------------
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(voice),
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out],
                       stdin=subprocess.PIPE)
TN = round(edl.get("transition", 0.7) * FPS)
last_screen, ustate = None, {}
trans_left = 0  # screen -> full morph frames still to play (may span several short pieces)
for q in plan:
    p, n = q["p"], q["n"]
    cam_path = cam_file(p["src"])
    print(f"piece {q['k']:3d} {p['layout']:6s} {q['start']:7.2f}s  {p.get('say', '')[:50]}", flush=True)
    screen_path = cache / p.get("screen_src", edl.get("screen", "screen.mp4"))
    if q["trans_out"]:
        trans_left = TN
    if p["layout"] == "screen" or trans_left > 0:
        fcx, fcy, side = face_track(cam_path, p["in"], n)
    base_x = p.get("circle_x", CX)
    base_x = ALT_X if base_x == "alt" else base_x
    posx = dodge_x(screen_path, q["s_in"], n, base_x) if p["layout"] == "screen" and "circle_x" not in p \
        else np.full(n, float(base_x))
    zr = zoom_rects(p.get("zoom"), n)
    rects = p.get("blur", [])
    cams = reader(cam_path, p["in"], n)
    scr = reader(screen_path, q["s_in"], n) if q["s_in"] is not None else None
    for i in range(n):
        cam = next(cams)
        if cam is None:
            sys.exit(f"piece {q['k']}: camera {cam_path} has no frames at {p['in']}")
        if p["layout"] == "full":
            frame = cam.copy()
            if trans_left > 0 and last_screen is not None:
                frame = last_screen.copy()
                morph(frame, cam, fcx[i], fcy[i], side, CX, trans_left / TN)
                trans_left -= 1
        elif p["layout"] == "screen":
            frame = next(scr).copy()
            hide_private(frame, ustate, rects)
            if zr:
                frame = apply_zoom(frame, zr[i])
            last_screen = frame.copy()
            if q["trans_in"] and i < TN:
                morph(frame, cam, fcx[i], fcy[i], side, posx[i], i / TN)
            else:
                put_circle(frame, cam, fcx[i], fcy[i], side, posx[i])
        else:  # split: screen left, camera right
            s = next(scr).copy()
            hide_private(s, ustate, rects)
            sx = int(np.clip(p.get("screen_x", 351), 0, W // 2))
            cx = int(np.clip(p.get("cam_x", W / 2) - W / 4, 0, W / 2))
            frame = np.empty((H, W, 3), np.uint8)
            frame[:, : W // 2] = s[:, sx:sx + W // 2]
            frame[:, W // 2:] = cam[:, cx:cx + W // 2]
            frame[:, W // 2 - 3: W // 2 + 3] = 20
        enc.stdin.write(frame.tobytes())
enc.stdin.close()
enc.wait()
print("duration", round(total, 2), "->", out)
