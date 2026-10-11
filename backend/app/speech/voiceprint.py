"""Voice lock (experimental): only the enrolled voice can command Jarvis.

A speaker-recognition model (3D-Speaker CAM++, via sherpa-onnx, fully local)
turns speech into a 512-number voiceprint. Enrollment averages a few phrases
of the user's voice; afterwards, utterances of at least a second are compared
with it (cosine similarity) and ignored when they don't match. Shorter ones
("Jarvis" alone) are too short to judge and pass — the command that follows
is checked.

Experimental: on synthetic test voices (Kokoro) the scores of different
speakers overlapped, so the threshold must be calibrated on the user's real
voice — Settings shows the live score for that.
"""
from __future__ import annotations

import io
import json
import threading
import time
import wave

import numpy as np

from ..config import JARVIS_HOME, settings

MODEL = JARVIS_HOME / "models" / "speaker" / "campplus_en.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "speaker-recongition-models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx")
PRINT = JARVIS_HOME / "voiceprint.json"
MIN_SECONDS = 1.0
DEFAULT_THRESHOLD = 0.45

_lock = threading.Lock()
_extractor = None
_pending: list[np.ndarray] = []


def available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return MODEL.exists()


def _ex():
    global _extractor
    with _lock:
        if _extractor is None:
            import sherpa_onnx
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL), num_threads=2)
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        return _extractor


def pcm(wav_bytes: bytes) -> np.ndarray:
    """16-bit mono WAV (what the Jarvis window sends) -> float samples at 16 kHz."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("expected 16-bit audio")
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
        if w.getframerate() != 16000:
            n = int(len(data) * 16000 / w.getframerate())
            data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    return _trim(data.astype(np.float32))


def _trim(a: np.ndarray) -> np.ndarray:
    loud = np.where(np.abs(a) > max(0.01, np.abs(a).max() * 0.05))[0] if len(a) else []
    return a[loud[0]:loud[-1] + 1] if len(loud) else a


def embed(samples: np.ndarray) -> np.ndarray:
    ex = _ex()
    stream = ex.create_stream()
    stream.accept_waveform(16000, samples)
    stream.input_finished()
    v = np.array(ex.compute(stream), dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def enrolled() -> dict | None:
    try:
        return json.loads(PRINT.read_text())
    except (OSError, ValueError):
        return None


def enroll_add(wav_bytes: bytes) -> dict:
    """One enrollment phrase; returns progress."""
    a = pcm(wav_bytes)
    if len(a) < 16000 * MIN_SECONDS:
        return {"error": "That was too short — say the whole sentence."}
    _pending.append(a)
    return {"phrases": len(_pending), "seconds": round(sum(len(x) for x in _pending) / 16000, 1)}


def enroll_finish() -> dict:
    if sum(len(x) for x in _pending) < 16000 * 4:
        return {"error": "Need at least 4 seconds of speech — record another phrase."}
    vec = embed(np.concatenate(_pending))
    PRINT.write_text(json.dumps({"embedding": vec.tolist(), "created": time.time(),
                                 "seconds": round(sum(len(x) for x in _pending) / 16000, 1)}))
    _pending.clear()
    return {"ok": True}


def enroll_reset() -> None:
    _pending.clear()


def score(wav_bytes: bytes) -> float | None:
    """Similarity to the enrolled voice, or None when it can't be judged."""
    vp = enrolled()
    if not vp or not available():
        return None
    a = pcm(wav_bytes)
    if len(a) < 16000 * MIN_SECONDS:
        return None
    return float(np.dot(np.array(vp["embedding"], dtype=np.float32), embed(a)))


def locked() -> bool:
    return bool(settings.get("voice.lock.enabled", False)) and enrolled() is not None


def threshold() -> float:
    return float(settings.get("voice.lock.threshold", DEFAULT_THRESHOLD))


def check(wav_bytes: bytes) -> tuple[bool, float | None]:
    """(allowed, score). Allowed when the lock is off, the clip is too short to
    judge, or the voice matches."""
    if not locked():
        return True, None
    try:
        s = score(wav_bytes)
    except Exception:
        return True, None
    return (s is None or s >= threshold()), s
