"""Voice lock: enrollment and checking."""
import io
import wave

import numpy as np
import pytest

from app.config import settings
from app.speech import voiceprint


def _wav(seconds: float, freq: float = 220.0) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    a = (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(a.tobytes())
    return buf.getvalue()


def test_lock_is_off_by_default_and_short_clips_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(voiceprint, "PRINT", tmp_path / "vp.json")
    assert voiceprint.check(_wav(2)) == (True, None)          # not enrolled / not enabled
    assert "too short" in voiceprint.enroll_add(_wav(0.5))["error"]


def _real_model():
    import os
    import pwd
    from pathlib import Path
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".jarvis" / "models" / "speaker" / "campplus_en.onnx"


@pytest.mark.skipif(not _real_model().exists(), reason="voice model not downloaded")
def test_enroll_then_check(monkeypatch, tmp_path):
    monkeypatch.setattr(voiceprint, "PRINT", tmp_path / "vp.json")
    monkeypatch.setattr(voiceprint, "MODEL", _real_model())
    voiceprint.enroll_reset()
    for _ in range(3):
        assert "phrases" in voiceprint.enroll_add(_wav(2.0))
    assert voiceprint.enroll_finish() == {"ok": True}
    settings.update({"voice": {"lock": {"enabled": True, "threshold": 0.45}}})
    try:
        allowed, score = voiceprint.check(_wav(2.0))
        assert allowed and score > 0.9                            # same "voice"
        assert voiceprint.check(_wav(0.5)) == (True, None)        # too short to judge
    finally:
        settings.update({"voice": {"lock": {"enabled": False}}})
