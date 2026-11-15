"""A scripted stand-in for an AI model.

It replays prepared replies in order. It exists so the reasoning engine can be
built and tested before any real model is installed. It is NOT a model, is not
selectable through configuration, and must never be presented as one.
"""

from __future__ import annotations

import json

from .base import AIProvider, ChatMessage, ProviderError, ProviderResponse, ProviderStatus


class ScriptedProvider(AIProvider):
    name = "scripted"

    def __init__(self, replies: list):
        """Each reply is text, a dict (sent as JSON), an Exception to raise,
        or a function `fn(messages) -> text | dict`."""
        self.replies = list(replies)
        self.prompts: list[list[ChatMessage]] = []

    def status(self) -> ProviderStatus:
        return ProviderStatus("scripted", "local", True, True, "scripted",
                              "Scripted stand-in used for testing. Not a real model.")

    def generate(self, messages: list[ChatMessage]) -> ProviderResponse:
        self.prompts.append(messages)
        if not self.replies:
            raise ProviderError("The scripted stand-in has no more replies.")
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(messages)
        if isinstance(reply, Exception):
            raise reply
        if not isinstance(reply, str):
            reply = json.dumps(reply)
        return ProviderResponse(reply, self.name, "scripted")
