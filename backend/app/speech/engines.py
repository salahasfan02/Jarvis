"""Pluggable text-to-speech engines.

The frontend asks /api/tts/speak; if the configured engine can synthesize
server-side it returns a WAV, otherwise {"engine": "browser"} tells the UI
to use the built-in browser voices. New engines (XTTS-v2, Kokoro, OpenVoice,
F5-TTS, voice clones...) implement synthesize() and register themselves —
no other code changes needed, and the Settings dropdown picks them up from
/api/tts/engines.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import settings


class TTSEngine:
    id = "base"
    name = "Base"

    def available(self) -> bool:
        raise NotImplementedError

    def unavailable_reason(self) -> str:
        return ""

    async def synthesize(self, text: str) -> bytes | None:
        """Return WAV bytes, or None to fall back to the browser."""
        raise NotImplementedError


class BrowserEngine(TTSEngine):
    """The default: synthesis happens in the frontend (Web Speech API)."""
    id = "browser"
    name = "Browser voices (built-in)"

    def available(self) -> bool:
        return True

    async def synthesize(self, text: str) -> bytes | None:
        return None


class PiperEngine(TTSEngine):
    """Local neural TTS via the `piper` CLI. Install:  brew install piper-tts
    (or pipx install piper-tts), then download a voice .onnx model and set
    its path in Settings -> Voice."""
    id = "piper"
    name = "Piper (local neural TTS)"

    def _binary(self) -> str | None:
        return shutil.which("piper")

    def _voice(self) -> str:
        return settings.get("voice.piper_voice_path", "")

    def available(self) -> bool:
        return bool(self._binary() and self._voice() and Path(self._voice()).exists())

    def unavailable_reason(self) -> str:
        if not self._binary():
            return "piper binary not found (brew install piper-tts)"
        if not self._voice():
            return "no voice model set (Settings > Voice > Piper voice path)"
        if not Path(self._voice()).exists():
            return f"voice model not found at {self._voice()}"
        return ""

    async def synthesize(self, text: str) -> bytes | None:
        if not self.available():
            return None
        out = Path(tempfile.mkstemp(suffix=".wav")[1])
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary(), "--model", self._voice(), "--output_file", str(out),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.communicate(text.encode()), timeout=60)
            return out.read_bytes() if out.exists() and out.stat().st_size > 0 else None
        except (asyncio.TimeoutError, OSError):
            return None
        finally:
            out.unlink(missing_ok=True)


class KokoroEngine(TTSEngine):
    """Kokoro — local neural TTS with genuinely human-sounding voices.
    Uses the kokoro-onnx runtime; the model (~340 MB total) is downloaded
    once from Settings > Voice and stored in ~/.jarvis/models/kokoro."""
    id = "kokoro"
    name = "Kokoro (human, local)"

    MODELS_DIR = None  # set below
    MODEL_URL = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
                 "model-files-v1.0/kokoro-v1.0.onnx")
    VOICES_URL = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
                  "model-files-v1.0/voices-v1.0.bin")

    def __init__(self) -> None:
        from ..config import JARVIS_HOME
        self.models_dir = JARVIS_HOME / "models" / "kokoro"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._kokoro = None

    @property
    def model_path(self) -> Path:
        return self.models_dir / "kokoro-v1.0.onnx"

    @property
    def voices_path(self) -> Path:
        return self.models_dir / "voices-v1.0.bin"

    def files_present(self) -> bool:
        return (self.model_path.exists() and self.model_path.stat().st_size > 100e6
                and self.voices_path.exists() and self.voices_path.stat().st_size > 1e6)

    def available(self) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return False
        return self.files_present()

    def unavailable_reason(self) -> str:
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return "pip install kokoro-onnx in the backend environment"
        if not self.files_present():
            return "voice model not downloaded yet (~340 MB, one time)"
        return ""

    def _load(self):
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(str(self.model_path), str(self.voices_path))
        return self._kokoro

    async def synthesize(self, text: str) -> bytes | None:
        if not self.available():
            return None
        voice = settings.get("voice.kokoro_voice", "bm_george")

        def run() -> bytes:
            import io
            import wave

            import numpy as np
            kokoro = self._load()
            samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0,
                                                 lang="en-us")
            pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(pcm.tobytes())
            return buf.getvalue()

        try:
            return await asyncio.wait_for(asyncio.to_thread(run), timeout=120)
        except (asyncio.TimeoutError, Exception):
            return None

    async def download(self):
        """Stream-download the model files, yielding progress events."""
        import httpx
        for url, dest in ((self.MODEL_URL, self.model_path),
                          (self.VOICES_URL, self.voices_path)):
            if dest.exists() and dest.stat().st_size > 1e6:
                yield {"file": dest.name, "status": "already downloaded"}
                continue
            tmp = dest.with_suffix(".part")
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    done = 0
                    last_pct = -5
                    with tmp.open("wb") as f:
                        async for chunk in r.aiter_bytes(1024 * 512):
                            f.write(chunk)
                            done += len(chunk)
                            pct = int(done * 100 / total) if total else 0
                            if pct >= last_pct + 5:
                                last_pct = pct
                                yield {"file": dest.name, "percent": pct,
                                       "mb": round(done / 1e6)}
            tmp.rename(dest)
            yield {"file": dest.name, "status": "done"}
        self._kokoro = None  # force reload with fresh files


ENGINES: dict[str, TTSEngine] = {}


def register(engine: TTSEngine) -> None:
    ENGINES[engine.id] = engine


register(KokoroEngine())
register(PiperEngine())
register(BrowserEngine())

KOKORO_VOICES = [
    {"id": "bm_george", "name": "George — British male (JARVIS-like)"},
    {"id": "bm_fable", "name": "Fable — British male"},
    {"id": "bm_lewis", "name": "Lewis — British male"},
    {"id": "bm_daniel", "name": "Daniel — British male"},
    {"id": "bf_emma", "name": "Emma — British female"},
    {"id": "bf_isabella", "name": "Isabella — British female"},
    {"id": "am_michael", "name": "Michael — American male"},
    {"id": "am_adam", "name": "Adam — American male"},
    {"id": "af_heart", "name": "Heart — American female (highest quality)"},
    {"id": "af_bella", "name": "Bella — American female"},
    {"id": "af_sky", "name": "Sky — American female"},
]


def list_engines() -> list[dict]:
    return [{"id": e.id, "name": e.name, "available": e.available(),
             "reason": e.unavailable_reason()} for e in ENGINES.values()]


_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


def is_arabic(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(bool(_ARABIC.match(c)) for c in letters) / len(letters) > 0.4


async def _say_wav(text: str, voice: str) -> bytes | None:
    """macOS's own voices (e.g. Majed for Arabic, which Kokoro doesn't speak)."""
    def run() -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "say.wav"
            r = subprocess.run(["say", "-v", voice, "--file-format=WAVE",
                                "--data-format=LEI16@22050", "-o", str(out), text],
                               capture_output=True, timeout=60)
            return out.read_bytes() if r.returncode == 0 and out.exists() else None
    return await asyncio.to_thread(run)


async def synthesize(text: str) -> bytes | None:
    if is_arabic(text):
        voice = settings.get("voice.arabic_voice", "Majed")
        if wav := await _say_wav(text, voice):
            return wav
    engine = ENGINES.get(settings.get("voice.tts_engine", "browser"))
    if engine is None:
        return None
    try:
        return await engine.synthesize(text)
    except Exception:
        return None
