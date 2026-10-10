"""Offline speech-to-text via faster-whisper.

The Whisper model runs fully locally (CPU, int8). Models are stored in
~/.jarvis/models/whisper and downloaded once from Settings > Voice. The
frontend records audio with MediaRecorder and posts it to /api/stt/transcribe,
which makes speech recognition work in any browser — no cloud, no Chrome
dependency.
"""
from __future__ import annotations

import asyncio
import io
import threading
import time

from ..config import JARVIS_HOME, settings

MODELS_DIR = JARVIS_HOME / "models" / "whisper"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_SIZES = {"tiny": 75, "base": 145, "small": 484}  # approx MB

_lock = threading.Lock()
_model = None
_model_size: str | None = None
_downloading: str | None = None


def configured_size() -> str:
    size = settings.get("voice.whisper_model", "base")
    return size if size in MODEL_SIZES else "base"


def model_present(size: str | None = None) -> bool:
    size = size or configured_size()
    # faster-whisper stores snapshots as models--Systran--faster-whisper-<size>
    snap = MODELS_DIR / f"models--Systran--faster-whisper-{size}"
    return snap.exists() and any(snap.rglob("model.bin"))


def status() -> dict:
    size = configured_size()
    return {
        "engine": "whisper",
        "model": size,
        "available": model_present(size),
        "downloading": _downloading,
        "reason": "" if model_present(size)
                  else f"model '{size}' not downloaded yet (~{MODEL_SIZES[size]} MB, one time)",
    }


def _load(size: str):
    """Load (and if needed download) the model. Blocking; call in a thread."""
    global _model, _model_size
    with _lock:
        if _model is None or _model_size != size:
            from faster_whisper import WhisperModel
            _model = WhisperModel(size, device="cpu", compute_type="int8",
                                  download_root=str(MODELS_DIR))
            _model_size = size
        return _model


async def download(size: str):
    """Download the model, yielding progress events (dir-size polling)."""
    global _downloading
    if size not in MODEL_SIZES:
        yield {"error": f"unknown model size '{size}'"}
        return
    if model_present(size):
        yield {"status": "already downloaded", "done": True}
        return

    _downloading = size
    total_mb = MODEL_SIZES[size]
    task = asyncio.create_task(asyncio.to_thread(_load, size))
    try:
        while not task.done():
            done_mb = sum(f.stat().st_size for f in MODELS_DIR.rglob("*")
                          if f.is_file()) / 1e6
            yield {"model": size, "mb": round(done_mb),
                   "percent": min(99, round(done_mb * 100 / total_mb))}
            await asyncio.sleep(1.0)
        await task  # surface exceptions
        yield {"status": "done", "done": True}
    except Exception as e:
        yield {"error": str(e)}
    finally:
        _downloading = None


def _bias_kwargs(model, hint: str) -> dict:
    """Nudge Whisper towards words it should expect — above all the wake word,
    which it otherwise often writes as "Jervis", "Javis" or "Gervais".
    `hotwords` (faster-whisper >= 1.0.2) biases without the hallucination risk
    of a prompt; older versions get the same hint as an initial prompt."""
    if not hint:
        return {}
    import inspect
    try:
        if "hotwords" in inspect.signature(model.transcribe).parameters:
            return {"hotwords": hint}
    except (TypeError, ValueError):
        pass
    return {"initial_prompt": hint}


async def transcribe(audio: bytes, hint: str = "") -> dict:
    """Transcribe an audio blob (webm/ogg/wav/m4a — PyAV decodes them all).
    `hint`: words to expect, e.g. the wake words."""
    size = configured_size()
    if not model_present(size):
        return {"error": f"whisper model '{size}' is not downloaded"}
    lang = (settings.get("voice.language", "en-US") or "en").split("-")[0].lower()

    def run() -> dict:
        started = time.time()
        model = _load(size)
        segments, info = model.transcribe(
            io.BytesIO(audio),
            language=lang if lang != "auto" else None,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            **_bias_kwargs(model, hint),
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {"text": text, "language": info.language,
                "seconds": round(time.time() - started, 2)}

    try:
        return await asyncio.wait_for(asyncio.to_thread(run), timeout=60)
    except asyncio.TimeoutError:
        return {"error": "transcription timed out"}
    except Exception as e:
        return {"error": str(e)}
