import sys
import types

import pytest

from src.call_analysis.transcription import transcribe_audio


def test_transcribe_audio_raises_clear_error_when_whisper_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", None)

    with pytest.raises(RuntimeError, match="openai-whisper"):
        transcribe_audio("call.mp3")


def test_transcribe_audio_uses_whisper_model(monkeypatch):
    fake_model = types.SimpleNamespace(
        transcribe=lambda path, language: {"text": "  transcrição de teste  "}
    )
    fake_whisper = types.SimpleNamespace(load_model=lambda size: fake_model)
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    result = transcribe_audio("call.mp3", model_size="tiny", language="pt")

    assert result == "transcrição de teste"
