"""Local speech-to-text on Apple Silicon (used when summarizing podcasts with a text-only model)."""
import os
from pathlib import Path

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")


def transcribe(audio: Path) -> str:
    import mlx_whisper
    result = mlx_whisper.transcribe(str(audio), path_or_hf_repo=WHISPER_MODEL, language="en")
    return result["text"].strip()
