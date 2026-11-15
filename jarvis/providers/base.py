"""AI provider abstraction.

To add a provider: subclass `AIProvider`, implement `status()` and
`generate()`, and register a factory with `registry.register_provider`.
The orchestrator only ever talks to this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

from ..common import JarvisError


class ProviderError(JarvisError):
    """A provider could not produce a response."""


@dataclass(frozen=True)
class ChatMessage:
    role: str      # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    provider: str
    model: str


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    kind: str          # "none" | "local" | "external"
    configured: bool   # a provider has been selected and set up
    available: bool    # it answered a health check just now
    model: str
    detail: str        # human-readable explanation, shown in the interface

    def to_dict(self) -> dict:
        return asdict(self)


class AIProvider(ABC):
    name = "base"
    is_local = True

    @abstractmethod
    def status(self) -> ProviderStatus:
        """Report honestly whether this provider can answer right now."""

    @abstractmethod
    def generate(self, messages: list[ChatMessage]) -> ProviderResponse:
        """Return a completion for the conversation, or raise ProviderError."""


class NullProvider(AIProvider):
    """Stands in when no model is connected. It never fabricates a reply."""

    name = "none"

    def __init__(self, detail: str = ""):
        self.detail = detail or (
            "No AI provider is configured. Set JARVIS_AI_PROVIDER in .env to connect one."
        )

    def status(self) -> ProviderStatus:
        return ProviderStatus(name="none", kind="none", configured=False, available=False,
                              model="", detail=self.detail)

    def generate(self, messages: list[ChatMessage]) -> ProviderResponse:
        raise ProviderError(self.detail)
