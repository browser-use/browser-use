"""Helpers for capturing audio and transcribing it with Whisper."""

from __future__ import annotations

# pyright: reportMissingImports=false

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

try:
	import sounddevice as sd
	import soundfile as sf
except Exception:  # pragma: no cover - optional deps
	sd = None
	sf = None

try:
	import whisper
except Exception:  # pragma: no cover - optional deps
	whisper = None

logger = logging.getLogger(__name__)


async def record_audio(duration: int = 5, fs: int = 16000) -> Path:
	"""Record audio from the microphone and return a temporary ``.wav`` file."""
	if sd is None or sf is None:
		raise RuntimeError("sounddevice and soundfile are required for voice input")

	audio = sd.rec(int(duration * fs), samplerate=fs, channels=1)
	sd.wait()

	with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
		path = Path(tmp.name)
		sf.write(tmp.name, audio, fs)
	return path


def _transcribe(path: Path, model_name: str = "base") -> str:
	"""Transcribe an audio file using ``openai-whisper``."""
	if whisper is None:
		raise RuntimeError("openai-whisper is required for voice input")

	model = whisper.load_model(model_name)
	result: dict[str, Any] = model.transcribe(str(path))
	return str(result.get("text", "")).strip()


async def capture_voice_command(duration: int = 5, model_name: str = "base") -> str:
	"""Capture audio from the microphone and return the transcribed text."""
	path = await record_audio(duration)
	try:
		text = await asyncio.to_thread(_transcribe, path, model_name)
	finally:
		path.unlink(missing_ok=True)
	return text
