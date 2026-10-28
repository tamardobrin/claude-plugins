"""Audio + Whisper helpers shared by transcribe.py, cutcheck.py, verify.py."""
import os
import subprocess
import tempfile
import wave

import numpy as np

SR = 16000
DEFAULT_MODELS = {"he": "ivrit-ai/whisper-large-v3-turbo-ct2"}  # tuned Hebrew model; others use turbo


def model_for(lang, model=None):
    return model or DEFAULT_MODELS.get(lang, "large-v3-turbo")


def read_wav16(path):
    """16 kHz mono int16 WAV -> float32 array. Anything else is converted with ffmpeg first."""
    try:
        with wave.open(str(path), "rb") as wf:
            if wf.getframerate() == SR and wf.getnchannels() == 1 and wf.getsampwidth() == 2:
                return np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
    except (wave.Error, EOFError):
        pass
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                        "-c:a", "pcm_s16le", tmp], check=True)
        return read_wav16(tmp)
    finally:
        os.remove(tmp)


def write_wav16(path, x):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


_models = {}


def transcribe(x, lang, model=None, prompt=None, verbose=False):
    """faster-whisper with word timestamps. x = 16k float32 array.
    Returns [{"start","end","text","words":[{"w","s","e","p"}]}].
    Audio is passed as an array because faster-whisper 1.2.x's PyAV decoder breaks on av>=19."""
    from faster_whisper import WhisperModel
    name = model_for(lang, model)
    if name not in _models:
        _models[name] = WhisperModel(name, device="cpu", compute_type="int8")
    segs, _ = _models[name].transcribe(x, language=lang, word_timestamps=True, initial_prompt=prompt,
                                       vad_filter=False, condition_on_previous_text=False)
    out = []
    for s in segs:
        out.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(),
                    "words": [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3),
                               "p": round(w.probability, 3)} for w in s.words]})
        if verbose:
            print(f"[{s.start:7.2f}-{s.end:7.2f}] {s.text.strip()}", flush=True)
    return out


def words(segments):
    return [w for s in segments for w in s["words"]]


def suspicious(w):
    """Whisper word that probably hides a repeat, a pause or a stretched sound:
    longer than 0.6 s AND slow for its length (long words are naturally long)."""
    d = w["e"] - w["s"]
    return d > 0.6 and d / max(1, len(norm(w["w"]))) > 0.18


def norm(w):
    return "".join(c for c in w if c.isalnum()).lower()


def energy(x, bin_s=0.01):
    """Per-bin RMS dB and >3.5 kHz dB (final fricatives like s/sh look like noise in RMS alone)."""
    b = int(SR * bin_s)
    n = len(x) // b
    fr = x[: n * b].reshape(n, b)
    rms = np.sqrt((fr ** 2).mean(1)) + 1e-9
    spec = np.abs(np.fft.rfft(fr * np.hanning(b), axis=1))
    f = np.fft.rfftfreq(b, 1 / SR)
    hf = np.sqrt((spec[:, f > 3500] ** 2).mean(1)) + 1e-9
    return 20 * np.log10(rms), 20 * np.log10(hf)
