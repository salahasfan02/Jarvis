"""The wake word is passed to Whisper as a hint (hotwords on newer
faster-whisper, an initial prompt on older ones)."""
from app.speech import stt


class NewWhisper:
    def transcribe(self, audio, language=None, hotwords=None, initial_prompt=None):
        pass


class OldWhisper:
    def transcribe(self, audio, language=None, initial_prompt=None):
        pass


def test_hint_uses_hotwords_when_available():
    assert stt._bias_kwargs(NewWhisper(), "Jarvis") == {"hotwords": "Jarvis"}
    assert stt._bias_kwargs(OldWhisper(), "Jarvis") == {"initial_prompt": "Jarvis"}
    assert stt._bias_kwargs(NewWhisper(), "") == {}
