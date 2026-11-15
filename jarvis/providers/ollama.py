"""Adapter for a local Ollama server (https://ollama.com).

JARVIS does not install or start Ollama. This adapter only talks to a server
that is already running, over its HTTP API, using the standard library.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import AIProvider, ChatMessage, ProviderError, ProviderResponse, ProviderStatus


class OllamaProvider(AIProvider):
    name = "ollama"
    is_local = True

    def __init__(self, base_url: str, model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            raise ProviderError(f"Ollama returned HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("Ollama returned a response that is not valid JSON") from exc

    def status(self) -> ProviderStatus:
        def result(available: bool, detail: str) -> ProviderStatus:
            return ProviderStatus(name=self.name, kind="local", configured=bool(self.model),
                                  available=available, model=self.model, detail=detail)

        if not self.model:
            return result(False, "Ollama is selected but JARVIS_AI_MODEL is not set.")
        try:
            tags = self._request("/api/tags", timeout=3)
        except ProviderError as exc:
            return result(False, str(exc))
        installed = [item.get("name", "") for item in tags.get("models", [])]
        if self.model not in installed and f"{self.model}:latest" not in installed:
            return result(False, f"Ollama is running but the model '{self.model}' is not installed there.")
        return result(True, f"Connected to Ollama at {self.base_url}.")

    def generate(self, messages: list[ChatMessage], json_output: bool = False) -> ProviderResponse:
        if not self.model:
            raise ProviderError("JARVIS_AI_MODEL is not set.")
        payload = {
            "model": self.model,
            "stream": False,
            # No hidden step-by-step "thinking": JARVIS needs a direct answer, quickly.
            "think": False,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "options": {"temperature": 0.2 if json_output else 0.6},
        }
        if json_output:
            payload["format"] = "json"   # Ollama constrains the reply to valid JSON
        reply = self._request("/api/chat", payload)
        content = (reply.get("message") or {}).get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Ollama returned an empty response.")
        return ProviderResponse(text=content.strip(), provider=self.name, model=self.model)
