"""Shared paths and helpers. Standard library only at import time (setup.py uses it too)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP = "tutorial-editor"
W, H = 1920, 1080


def home():
    """Per-user tool folder (venv, models, proxy cache). Override with TUTORIAL_EDITOR_HOME.
    Kept out of synced folders (OneDrive/Dropbox/iCloud) on purpose: proxies are big."""
    env = os.environ.get("TUTORIAL_EDITOR_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / APP


def models_dir():
    return home() / "models"


def venv_python():
    v = home() / "venv"
    return v / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def edl_path(proj):
    return Path(proj) / "edl.json"


def load_edl(proj):
    p = edl_path(proj)
    return json.load(open(p, encoding="utf-8")) if p.exists() else {}


def save_edl(proj, edl):
    json.dump(edl, open(edl_path(proj), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def expand(p, base):
    p = Path(os.path.expandvars(os.path.expanduser(str(p))))
    return p if p.is_absolute() else Path(base) / p


def cache_dir(proj, edl=None):
    """edl["cache"] (absolute, ~, $VARS or relative to the project) or <home>/cache/<project name>."""
    edl = load_edl(proj) if edl is None else edl
    c = edl.get("cache")
    p = expand(c, proj) if c else home() / "cache" / Path(proj).resolve().name
    p.mkdir(parents=True, exist_ok=True)
    return p


def need(tool):
    if not shutil.which(tool):
        sys.exit(f"{tool} not found on PATH. Install FFmpeg (Windows: winget install Gyan.FFmpeg, "
                 f"macOS: brew install ffmpeg, Linux: apt install ffmpeg) and open a new terminal.")


def ffprobe(path):
    need("ffprobe")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def video_info(path):
    """(width, height as displayed, duration or None, has_audio)."""
    d = ffprobe(path)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        sys.exit(f"no video stream in {path}")
    w, h = int(v["width"]), int(v["height"])
    rot = int(v.get("tags", {}).get("rotate", 0) or 0)
    for sd in v.get("side_data_list", []):
        rot = int(sd.get("rotation", rot) or rot)
    if abs(rot) % 180 == 90:
        w, h = h, w
    dur = d["format"].get("duration")
    has_audio = any(s["codec_type"] == "audio" for s in d["streams"])
    return w, h, float(dur) if dur not in (None, "N/A") else None, has_audio


def run(cmd):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def quiet_mediapipe():
    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")


if hasattr(sys.stdout, "reconfigure"):  # Hebrew/RTL text on Windows consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
