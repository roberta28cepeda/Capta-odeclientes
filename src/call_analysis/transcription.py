"""Local audio transcription via openai-whisper (optional dependency)."""

from __future__ import annotations


def transcribe_audio(audio_path: str, model_size: str = "base", language: str = "pt") -> str:
    """Transcribe an audio file to text using a local Whisper model.

    Requires the optional `openai-whisper` package and the `ffmpeg` binary —
    see requirements-whisper.txt. Import is lazy so the rest of the CLI works
    without pulling in torch for users who only pass --transcript.
    """
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "openai-whisper não está instalado. Rode: "
            "pip install -r requirements-whisper.txt "
            "(requer também o binário `ffmpeg` instalado no sistema)."
        ) from exc

    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, language=language)
    return result["text"].strip()
