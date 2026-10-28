"""One-time setup: private venv + face model in the per-user tool folder.
Usage: python setup.py [--python <interpreter>] [--check]
Prints the interpreter to use for every other script (PY). Safe to re-run.
Python 3.10-3.12 is the safe range for mediapipe; if mediapipe can't install, face tracking falls
back to OpenCV (works, slightly less stable).
"""
import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import home, models_dir, venv_python  # noqa: E402

FACE_URL = ("https://storage.googleapis.com/mediapipe-models/face_detector/"
            "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite")

ap = argparse.ArgumentParser()
ap.add_argument("--python", default=sys.executable, help="interpreter used to create the venv")
ap.add_argument("--check", action="store_true", help="only report what is installed")
a = ap.parse_args()

ok = True
for tool in ("ffmpeg", "ffprobe"):
    if not shutil.which(tool):
        ok = False
        print(f"MISSING {tool}: Windows: winget install Gyan.FFmpeg | macOS: brew install ffmpeg | "
              "Linux: sudo apt install ffmpeg")
py = venv_python()
model = models_dir() / "blaze_face_short_range.tflite"
if a.check:
    print("home  ", home())
    print("venv  ", py, "OK" if py.exists() else "MISSING")
    print("model ", model, "OK" if model.exists() else "MISSING")
    sys.exit(0 if ok and py.exists() else 1)

home().mkdir(parents=True, exist_ok=True)
if not py.exists():
    print("creating venv in", home() / "venv")
    subprocess.run([a.python, "-m", "venv", str(home() / "venv")], check=True)


def pip(*pkgs):
    return subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", *pkgs]).returncode == 0


pip("--upgrade", "pip")
if not pip("numpy", "pillow", "faster-whisper"):
    sys.exit("pip install failed (numpy/pillow/faster-whisper)")
if pip("mediapipe"):  # brings its own OpenCV
    print("mediapipe OK")
else:
    print("WARNING: mediapipe did not install (try Python 3.12 via --python). Using OpenCV face detection.")
    pip("opencv-python-headless")
r = subprocess.run([str(py), "-c", "import cv2, numpy, PIL, faster_whisper; print('imports OK')"])
if r.returncode:
    sys.exit("import check failed")

models_dir().mkdir(parents=True, exist_ok=True)
if not model.exists():
    print("downloading face model")
    try:
        urllib.request.urlretrieve(FACE_URL, model)
    except Exception as e:
        print("WARNING: face model download failed:", e, "(OpenCV fallback will be used)")

print("\nPY =", py)
print("Whisper models download on first transcription (~1.5 GB, cached by Hugging Face).")
if not ok:
    sys.exit("install FFmpeg, then re-run")
