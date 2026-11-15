"""Voice: JARVIS's ears and mouth. Entirely local and offline.

- Listening: audio recorded in the browser is converted with ffmpeg and
  transcribed by whisper.cpp (`whisper-cli`) with a model in `data/models`.
- Speaking: the macOS `say` command renders the reply in a chosen voice
  (British "Daniel" by default) to an AAC file the browser plays.

Audio is processed in a temporary folder inside the data directory and deleted
straight away; only the transcript is kept, as an ordinary chat message.
Programs are run with argument lists (never a shell), and text to be spoken is
passed in a file, not on the command line.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import JarvisError, ValidationError
from .config import Config
from .logging_setup import get_logger

log = get_logger("voice")

EXTRA_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")
MAX_AUDIO_BYTES = 15_000_000
MAX_SPOKEN_CHARS = 1500
TRANSCRIBE_TIMEOUT = 120
AUDIO_TYPES = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
               "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/aac": ".aac", "application/octet-stream": ".bin"}


class VoiceError(JarvisError):
    """Voice processing failed or is not available."""


def find_program(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for folder in EXTRA_PATHS:
        candidate = Path(folder) / name
        if candidate.is_file():
            return str(candidate)
    return None


def speakable(text: str) -> str:
    """Turn a chat reply into something pleasant to hear."""
    text = re.sub(r"\n+\s*Sources?:.*$", "", text or "", flags=re.S | re.I)    # sources stay on screen
    text = re.sub(r"https?://\S+", "a link on screen", text)
    text = re.sub(r"\[memory:[^\]]*\]", "", text, flags=re.I)
    text = re.sub(r"[*_`#>|]+", "", text)                                       # markdown symbols
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_SPOKEN_CHARS:
        cut = text[:MAX_SPOKEN_CHARS]
        text = cut[:max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! ")) + 1] or cut
        text += " The rest is on screen."
    return text


class Voice:
    def __init__(self, config: Config):
        self.config = config

    @property
    def model_path(self) -> Path:
        return self.config.whisper_model

    def status(self) -> dict:
        programs = {name: find_program(name) for name in ("ffmpeg", "whisper-cli", "say")}
        missing = [name for name, path in programs.items() if not path]
        if not self.model_path.is_file():
            missing.append(f"speech model ({self.model_path.name})")
        return {
            "listening": bool(programs["ffmpeg"] and programs["whisper-cli"] and self.model_path.is_file()),
            "speaking": bool(programs["say"]),
            "voice": self.config.voice_name,
            "missing": missing,
        }

    def _workdir(self) -> tempfile.TemporaryDirectory:
        base = self.config.data_dir / "voice"
        base.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=base)

    @staticmethod
    def _run(args: list[str], timeout: int, what: str) -> subprocess.CompletedProcess:
        try:
            done = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise VoiceError(f"{what} took longer than {timeout} seconds") from exc
        except OSError as exc:
            raise VoiceError(f"{what} could not start: {exc}") from exc
        if done.returncode != 0:
            detail = done.stderr.decode("utf-8", "replace").strip()[-300:]
            raise VoiceError(f"{what} failed: {detail or f'exit code {done.returncode}'}")
        return done

    def transcribe(self, audio: bytes, content_type: str = "application/octet-stream", hint: str = "") -> str:
        """Speech to text. Returns the words heard (may be empty for silence)."""
        status = self.status()
        if not status["listening"]:
            raise VoiceError("Listening is not available: missing " + ", ".join(status["missing"]))
        if not audio:
            raise ValidationError("no audio was received")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValidationError("that recording is too long; keep it under a few minutes")
        suffix = AUDIO_TYPES.get(content_type.split(";")[0].strip().lower())
        if suffix is None:
            raise ValidationError(f"unsupported audio type: {content_type}")
        with self._workdir() as folder:
            source, wav, out = Path(folder) / f"input{suffix}", Path(folder) / "speech.wav", Path(folder) / "text"
            source.write_bytes(audio)
            self._run([find_program("ffmpeg"), "-loglevel", "error", "-y", "-i", str(source),
                       "-ar", "16000", "-ac", "1", str(wav)], 60, "Audio conversion")
            prompt = ["--prompt", hint[:600]] if hint else []        # names it should expect: far fewer mishearings
            self._run([find_program("whisper-cli"), "-m", str(self.model_path), "-f", str(wav),
                       "-nt", "-np", *prompt, "-otxt", "-of", str(out)], TRANSCRIBE_TIMEOUT, "Speech recognition")
            text_file = out.with_suffix(".txt")
            heard = text_file.read_text(encoding="utf-8", errors="replace") if text_file.exists() else ""
        heard = " ".join(heard.split())
        # whisper writes markers like [BLANK_AUDIO] or (music) for non-speech
        heard = re.sub(r"[\[(][^\])]*[\])]", "", heard).strip()
        return heard

    def speak(self, text: str) -> bytes:
        """Text to speech. Returns AAC audio in an M4A container."""
        if not find_program("say"):
            raise VoiceError("Speaking is not available: the macOS 'say' command was not found")
        words = speakable(text)
        if not words:
            raise ValidationError("there is nothing to say")
        with self._workdir() as folder:
            script, audio = Path(folder) / "speech.txt", Path(folder) / "speech.m4a"
            script.write_text(words, encoding="utf-8")
            self._run([find_program("say"), "-v", self.config.voice_name, "-r", str(self.config.voice_rate),
                       "--file-format=m4af", "--data-format=aac", "-o", str(audio), "-f", str(script)],
                      60, "Speech")
            return audio.read_bytes()


BASE_WORDS = "Jarvis, Ultron, Ultraman, Vision, Claude, Claude Code, Higgsfield, nanobots, approve, hands-free"


def vocabulary(app) -> str:
    """Words the owner is likely to say: project names, names from memory, JARVIS's own terms."""
    words = [p["name"] for p in app.projects.list()[:20]]
    for memory in app.memory.list(limit=200):
        if memory["category"] in ("personal", "preference"):
            words += re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", memory["content"])
    seen, unique = set(), []
    for word in words:
        if word.lower() not in seen:
            seen.add(word.lower()); unique.append(word)
    return f"{BASE_WORDS}, {', '.join(unique[:40])}." if unique else f"{BASE_WORDS}."
