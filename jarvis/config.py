"""Configuration manager.

Static configuration comes from, in order of precedence:

1. real environment variables
2. the `.env` file in the project root
3. built-in defaults

Runtime preferences that the user changes while JARVIS is running live in the
`settings` database table instead (see `jarvis.stores.settings`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path

from .common import JarvisError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

DEFAULTS = {
    "JARVIS_ENV": "development",
    "JARVIS_DATA_DIR": "data",
    "JARVIS_HOST": "127.0.0.1",
    "JARVIS_PORT": "8765",
    "JARVIS_LOG_LEVEL": "INFO",
    "JARVIS_AI_PROVIDER": "none",
    "JARVIS_AI_MODEL": "",
    "JARVIS_OLLAMA_URL": "http://127.0.0.1:11434",
    "JARVIS_AI_TIMEOUT_SECONDS": "120",
    "JARVIS_ALLOW_EXTERNAL_AI": "false",
    "JARVIS_ALLOW_WRITES": "true",
    "JARVIS_APPROVAL_TTL_MINUTES": "15",
    "JARVIS_BACKUP_ON_START": "true",
    "JARVIS_BACKUP_KEEP": "14",
    "JARVIS_ENGINE_MAX_STEPS": "12",
    "JARVIS_ENGINE_MAX_FAILURES": "3",
    "JARVIS_ENGINE_MAX_MODEL_CALLS": "40",
    "JARVIS_BRAVE_API_KEY": "",
    "JARVIS_WHISPER_MODEL": "data/models/ggml-small.en.bin",
    "JARVIS_VOICE": "Daniel",
    "JARVIS_VOICE_RATE": "185",
}


class ConfigError(JarvisError):
    """The configuration is invalid."""


@dataclass(frozen=True)
class Config:
    root: Path
    env: str
    data_dir: Path
    host: str
    port: int
    log_level: str
    ai_provider: str
    ai_model: str
    ollama_url: str
    ai_timeout_seconds: int
    allow_external_ai: bool
    allow_writes: bool
    approval_ttl_minutes: int
    backup_on_start: bool
    backup_keep: int
    engine_max_steps: int = 12
    engine_max_failures: int = 3
    engine_max_model_calls: int = 40
    brave_api_key: str = ""
    whisper_model: Path = Path("data/models/ggml-small.en.bin")
    voice_name: str = "Daniel"
    voice_rate: int = 185

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jarvis.db"

    @property
    def workspace_dir(self) -> Path:
        """Where JARVIS may freely create and run things (Phase 3 autonomy)."""
        return self.root / "workspace"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def pid_file(self) -> Path:
        return self.data_dir / "jarvis.pid"

    def public_dict(self) -> dict:
        """Configuration safe to show in the interface (no secrets exist yet)."""
        data = {key: str(value) if isinstance(value, Path) else value for key, value in asdict(self).items()}
        data["db_path"] = str(self.db_path)
        data["brave_api_key"] = "set" if self.brave_api_key else ""     # never reveal secrets
        return data


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE file. Missing file means no values."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            raise ConfigError(f"{path.name} line {number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def _boolean(name: str, value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false, got {value!r}")


def _integer(name: str, value: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number, got {value!r}") from exc
    if not minimum <= number <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {number}")
    return number


def _path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _voice(value: str) -> str:
    value = value.strip()
    if not value or not all(ch.isalnum() or ch in " ()-_" for ch in value):
        raise ConfigError("JARVIS_VOICE must be a voice name such as Daniel")
    return value


def load_config(
    root: Path | str | None = None,
    env_file: Path | str | None = None,
    environ: dict[str, str] | None = None,
) -> Config:
    """Build a validated Config. Arguments exist so tests can inject values."""
    root = Path(root).resolve() if root else PROJECT_ROOT
    environ = dict(os.environ if environ is None else environ)
    file_values = parse_env_file(Path(env_file) if env_file else root / ".env")

    def get(name: str) -> str:
        if environ.get(name, "") != "":
            return environ[name]
        if file_values.get(name, "") != "":
            return file_values[name]
        return DEFAULTS[name]

    host = get("JARVIS_HOST")
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(
            f"JARVIS_HOST must be a loopback address ({', '.join(LOOPBACK_HOSTS)}); "
            "JARVIS has no login and must not be exposed to a network"
        )

    log_level = get("JARVIS_LOG_LEVEL").upper()
    if log_level not in LOG_LEVELS:
        raise ConfigError(f"JARVIS_LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")

    data_dir = Path(get("JARVIS_DATA_DIR")).expanduser()
    if not data_dir.is_absolute():
        data_dir = root / data_dir

    return Config(
        root=root,
        env=get("JARVIS_ENV"),
        data_dir=data_dir.resolve(),
        host=host,
        port=_integer("JARVIS_PORT", get("JARVIS_PORT"), 1024, 65535),
        log_level=log_level,
        ai_provider=get("JARVIS_AI_PROVIDER").strip().lower() or "none",
        ai_model=get("JARVIS_AI_MODEL").strip(),
        ollama_url=get("JARVIS_OLLAMA_URL").strip().rstrip("/"),
        ai_timeout_seconds=_integer("JARVIS_AI_TIMEOUT_SECONDS", get("JARVIS_AI_TIMEOUT_SECONDS"), 1, 3600),
        allow_external_ai=_boolean("JARVIS_ALLOW_EXTERNAL_AI", get("JARVIS_ALLOW_EXTERNAL_AI")),
        allow_writes=_boolean("JARVIS_ALLOW_WRITES", get("JARVIS_ALLOW_WRITES")),
        approval_ttl_minutes=_integer("JARVIS_APPROVAL_TTL_MINUTES", get("JARVIS_APPROVAL_TTL_MINUTES"), 1, 1440),
        backup_on_start=_boolean("JARVIS_BACKUP_ON_START", get("JARVIS_BACKUP_ON_START")),
        backup_keep=_integer("JARVIS_BACKUP_KEEP", get("JARVIS_BACKUP_KEEP"), 1, 1000),
        engine_max_steps=_integer("JARVIS_ENGINE_MAX_STEPS", get("JARVIS_ENGINE_MAX_STEPS"), 1, 50),
        engine_max_failures=_integer("JARVIS_ENGINE_MAX_FAILURES", get("JARVIS_ENGINE_MAX_FAILURES"), 1, 20),
        engine_max_model_calls=_integer("JARVIS_ENGINE_MAX_MODEL_CALLS", get("JARVIS_ENGINE_MAX_MODEL_CALLS"), 1, 500),
        brave_api_key=get("JARVIS_BRAVE_API_KEY").strip(),
        whisper_model=_path(root, get("JARVIS_WHISPER_MODEL")),
        voice_name=_voice(get("JARVIS_VOICE")),
        voice_rate=_integer("JARVIS_VOICE_RATE", get("JARVIS_VOICE_RATE"), 90, 360),
    )
