"""Boost: borrow computing power from online platforms that run OPEN-SOURCE models.

The Mac's own model (Ollama) stays the default and the fallback. When the owner sets a key for one of
these platforms AND allows external AI, JARVIS sends its thinking there for far bigger, faster models,
and falls back to the Mac on any error, timeout or rate limit:

  platform     address                                  example open models (picked from what it offers)
  groq         https://api.groq.com/openai/v1           gpt-oss-120b, qwen3-32b, llama-3.3-70b
  cerebras     https://api.cerebras.ai/v1               gpt-oss-120b, qwen-3-235b, llama-3.3-70b
  openrouter   https://openrouter.ai/api/v1             many open models, some ":free"
  together     https://api.together.xyz/v1              qwen, llama, deepseek

Settings (in .env, set by the owner):  JARVIS_ALLOW_EXTERNAL_AI=true, JARVIS_BOOST=groq (or another
name above), JARVIS_BOOST_KEY=<the platform's API key>, optional JARVIS_BOOST_MODEL to pin a model.
Privacy: with boost on, what JARVIS thinks about (the conversation, page text) goes to that platform.
Photos stay on the Mac (vision is always local), and nothing is sent when boost is off.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from .base import AIProvider, ChatMessage, ProviderError, ProviderResponse, ProviderStatus

PLATFORMS = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
}
# Preferred open models, best first; the first one the platform actually offers is used.
PREFERRED = ("gpt-oss-120b", "qwen3-235b", "qwen-3-235b", "qwen3-32b", "qwen-3-32b", "llama-3.3-70b",
             "deepseek-r1-distill-llama-70b", "llama-4-maverick", "llama-4-scout", "gpt-oss-20b")


def boost_settings() -> tuple[str, str, str] | None:
    """(base_url, key, pinned model) when boost is switched on, else None."""
    name = os.environ.get("JARVIS_BOOST", "").strip().lower()
    key = os.environ.get("JARVIS_BOOST_KEY", "").strip()
    allowed = os.environ.get("JARVIS_ALLOW_EXTERNAL_AI", "false").strip().lower() in ("1", "true", "yes", "on")
    if not (name and key and allowed and name not in ("off", "0", "none")):
        return None
    base = PLATFORMS.get(name) or (name if name.startswith("https://") else None)
    return (base.rstrip("/"), key, os.environ.get("JARVIS_BOOST_MODEL", "").strip()) if base else None


class OpenAICompatible(AIProvider):
    """Any OpenAI-style chat API (Groq, Cerebras, OpenRouter, Together...)."""
    name = "boost"
    is_local = False
    streams = True

    def __init__(self, base_url: str, key: str, model: str = "", timeout: int = 60):
        self.base_url, self.key, self.pinned, self.timeout = base_url, key, model, timeout
        self.model = model
        self._picked_at = 0.0

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                "User-Agent": "JARVIS-assistant"}

    def _call(self, path: str, payload: dict | None = None, timeout: float | None = None):
        request = urllib.request.Request(self.base_url + path, headers=self._headers(),
                                         data=json.dumps(payload).encode() if payload is not None else None,
                                         method="POST" if payload is not None else "GET")
        try:
            return urllib.request.urlopen(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            wait = (exc.headers.get("retry-after") or "").strip() if exc.headers else ""
            after = f" (retry after {wait}s)" if re.fullmatch(r"\d+(\.\d+)?", wait) else ""
            raise ProviderError(f"boost platform answered HTTP {exc.code}{after}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"cannot reach the boost platform: {exc}") from exc

    def pick_model(self) -> str:
        """The pinned model, or the best open model this platform offers (checked once an hour)."""
        if self.pinned:
            return self.pinned
        if self.model and time.time() - self._picked_at < 3600:
            return self.model
        with self._call("/models", timeout=15) as response:
            ids = [m.get("id", "") for m in json.loads(response.read()).get("data", [])]
        for wanted in PREFERRED:
            match = next((i for i in ids if wanted in i.lower() and not i.lower().endswith(("-guard", "guard"))), None)
            if match:
                self.model, self._picked_at = match, time.time()
                return match
        if not ids:
            raise ProviderError("the boost platform lists no models")
        self.model, self._picked_at = ids[0], time.time()
        return self.model

    def status(self) -> ProviderStatus:
        try:
            model = self.pick_model()
            return ProviderStatus(name=self.name, kind="external", configured=True, available=True, model=model,
                                  detail=f"Boost on: {self.base_url} ({model}).")
        except ProviderError as exc:
            return ProviderStatus(name=self.name, kind="external", configured=True, available=False,
                                  model=self.model, detail=str(exc))

    def generate(self, messages: list[ChatMessage], json_output: bool = False, on_token=None) -> ProviderResponse:
        payload = {"model": self.pick_model(), "temperature": 0.2 if json_output else 0.6,
                   "messages": [{"role": m.role, "content": m.content} for m in messages]}
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        if on_token and not json_output:
            payload["stream"] = True
            text, last = "", 0.0
            with self._call("/chat/completions", payload) as response:
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    try:
                        delta = json.loads(line[5:])["choices"][0].get("delta", {}).get("content") or ""
                    except (ValueError, KeyError, IndexError):
                        continue
                    text += delta
                    if time.monotonic() - last > 0.15:
                        last = time.monotonic()
                        try:
                            on_token(text)
                        except Exception:  # noqa: BLE001
                            pass
            content = text
        else:
            with self._call("/chat/completions", payload) as response:
                data = json.loads(response.read())
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        content = __import__("re").sub(r"\s*【[^】]{0,40}】", "", content)      # gpt-oss citation marks
        if not content.strip():
            raise ProviderError("the boost platform returned an empty answer")
        return ProviderResponse(text=content.strip(), provider=self.name, model=self.model)


def back_off(error: str) -> float:
    """Seconds to stay on the Mac's model after a boost failure: what a rate limit asks for (its Retry-After,
    or "try again in 1m2.5s"), 5 s to 2 minutes; 2 minutes when the platform is unreachable or broken."""
    found = re.search(r"retry after (\d+(?:\.\d+)?)s", error) or None
    if found:
        seconds = float(found.group(1))
    else:
        spoken = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)(ms|s)", error)
        if not spoken:
            return 120.0
        if spoken.group(3) == "ms":
            return 5.0
        seconds = int(spoken.group(1) or 0) * 60 + float(spoken.group(2))
    return max(5.0, min(seconds + 1, 120.0))


class Boosted(AIProvider):
    """The boost platform first, the Mac's own model whenever it fails. Vision always stays local."""
    is_local = False
    streams = True

    def __init__(self, local: AIProvider, remote: OpenAICompatible):
        self.local, self.remote = local, remote
        self.name, self.model = "ollama", getattr(local, "model", "")      # the local identity, for the router
        self.base_url = getattr(local, "base_url", "")
        self._down_until = 0.0

    def status(self) -> ProviderStatus:
        local = self.local.status()
        remote = self.remote.status()
        if remote.available:
            return ProviderStatus(name="boost", kind="external", configured=True, available=True, model=remote.model,
                                  detail=f"{remote.detail} Falls back to {local.model} on this Mac.")
        return local

    def generate(self, messages, json_output: bool = False, on_token=None) -> ProviderResponse:
        if time.time() >= self._down_until:
            try:
                return self.remote.generate(messages, json_output=json_output, on_token=on_token)
            except ProviderError as exc:
                pause = back_off(str(exc))                # rate-limited: only as long as the platform asks
                self._down_until = time.time() + pause
                from ..logging_setup import get_logger
                get_logger("boost").warning("Boost failed, using the Mac's model for %d s: %s", pause, str(exc)[:300])
        if getattr(self.local, "streams", False):
            return self.local.generate(messages, json_output=json_output, on_token=on_token)
        return self.local.generate(messages, json_output=json_output)

    def see(self, *args, **kwargs):
        return self.local.see(*args, **kwargs)

    def context(self):
        return self.local.context() if hasattr(self.local, "context") else 16384
