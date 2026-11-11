"""Text-to-speech for the daily audio briefing, using Kokoro (open source), same voice everywhere.

- Mac: Kokoro on Apple Silicon (mlx-audio) in its own venv (.venv-tts), so its heavy dependencies can't disturb
  the main pipeline's.
- Cloud (GitHub Actions, Linux CPU): the same Kokoro model as ONNX (pip install kokoro-onnx), with the model files
  in KOKORO_DIR (kokoro-v1.0.onnx + voices-v1.0.bin from the kokoro-onnx releases).
Neither available: the briefing is skipped (run.py checks available()).
"""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TTS_PYTHON = ROOT / ".venv-tts" / "bin" / "python"
MODEL = os.environ.get("TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
VOICE = os.environ.get("TTS_VOICE", "af_heart")
KOKORO_DIR = Path(os.environ.get("KOKORO_DIR", Path.home() / ".cache" / "kokoro"))
ONNX_FILES = (KOKORO_DIR / "kokoro-v1.0.onnx", KOKORO_DIR / "voices-v1.0.bin")


def backend() -> str | None:
    if TTS_PYTHON.exists():
        return "mlx"
    if all(f.exists() for f in ONNX_FILES):
        try:
            import kokoro_onnx  # noqa: F401
            return "onnx"
        except ImportError:
            pass
    return None


def available() -> bool:
    return backend() is not None


def _mp3(src_args: list[str], dest: Path, stdin: bytes | None = None):
    # 64 kbps mono MP3 keeps a 3-minute briefing around 1.5 MB.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src_args, "-ac", "1", "-b:a", "64k", str(dest)],
                   input=stdin, check=True)


def speak(text: str, dest: Path) -> Path:
    if backend() == "onnx":
        from kokoro_onnx import Kokoro
        samples, rate = Kokoro(*map(str, ONNX_FILES)).create(text, voice=VOICE, speed=1.0, lang="en-us")
        _mp3(["-f", "f32le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0"], dest, samples.astype("<f4").tobytes())
        return dest
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run(
            [str(TTS_PYTHON), "-m", "mlx_audio.tts.generate", "--model", MODEL, "--voice", VOICE, "--lang_code", "a",
             "--text", text, "--file_prefix", str(Path(tmp) / "brief"), "--audio_format", "wav", "--join_audio"],
            capture_output=True, text=True, timeout=900,
        )
        wavs = sorted(Path(tmp).glob("brief*.wav"))
        if out.returncode != 0 or not wavs:
            raise RuntimeError(f"TTS failed: {out.stderr.strip()[-300:]}")
        _mp3(["-i", str(wavs[0])], dest)
    return dest


def prune(audio_dir: Path, keep: int = 30):
    """Audio is the only heavy file we publish; keep the last month."""
    files = sorted(audio_dir.glob("*.mp3"))
    for f in files[:-keep]:
        f.unlink()
