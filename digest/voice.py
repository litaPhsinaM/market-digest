"""Text-to-speech for the daily audio briefing, using Kokoro (open source) on Apple Silicon.

Kokoro lives in its own venv (.venv-tts) so its heavy dependencies can't disturb the main pipeline's.
"""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TTS_PYTHON = ROOT / ".venv-tts" / "bin" / "python"
MODEL = os.environ.get("TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
VOICE = os.environ.get("TTS_VOICE", "af_heart")


def available() -> bool:
    return TTS_PYTHON.exists()


def speak(text: str, dest: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run(
            [str(TTS_PYTHON), "-m", "mlx_audio.tts.generate", "--model", MODEL, "--voice", VOICE, "--lang_code", "a",
             "--text", text, "--file_prefix", str(Path(tmp) / "brief"), "--audio_format", "wav", "--join_audio"],
            capture_output=True, text=True, timeout=900,
        )
        wavs = sorted(Path(tmp).glob("brief*.wav"))
        if out.returncode != 0 or not wavs:
            raise RuntimeError(f"TTS failed: {out.stderr.strip()[-300:]}")
        # 64 kbps mono MP3 keeps a 3-minute briefing around 1.5 MB.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wavs[0]), "-ac", "1", "-b:a", "64k", str(dest)], check=True)
    return dest


def prune(audio_dir: Path, keep: int = 30):
    """Audio is the only heavy file we publish; keep the last month."""
    files = sorted(audio_dir.glob("*.mp3"))
    for f in files[:-keep]:
        f.unlink()
