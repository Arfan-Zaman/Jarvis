"""Boost: open-model platforms add power; the Mac's model is the fallback; off unless the owner opts in."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from support import JarvisTestCase

from jarvis.providers import ChatMessage, ProviderError
from jarvis.providers.base import ProviderResponse
from jarvis.providers.boost import Boosted, OpenAICompatible, boost_settings


class Local:
    name, model, streams = "ollama", "qwen3.5:9b", False
    def generate(self, messages, json_output=False):
        return ProviderResponse(text="local answer", provider="ollama", model=self.model)


class BoostTests(JarvisTestCase):
    def test_off_unless_key_platform_and_external_ai_are_all_set(self):
        with mock.patch.dict(os.environ, {"JARVIS_BOOST": "groq", "JARVIS_BOOST_KEY": "k", "JARVIS_ALLOW_EXTERNAL_AI": "false"}):
            self.assertIsNone(boost_settings())
        with mock.patch.dict(os.environ, {"JARVIS_BOOST": "groq", "JARVIS_BOOST_KEY": "", "JARVIS_ALLOW_EXTERNAL_AI": "true"}):
            self.assertIsNone(boost_settings())
        with mock.patch.dict(os.environ, {"JARVIS_BOOST": "groq", "JARVIS_BOOST_KEY": "k", "JARVIS_ALLOW_EXTERNAL_AI": "true",
                                          "JARVIS_BOOST_MODEL": ""}):
            self.assertEqual(boost_settings(), ("https://api.groq.com/openai/v1", "k", ""))

    def test_picks_the_best_open_model_offered(self):
        remote = OpenAICompatible("https://x.example/v1", "k")
        listing = mock.MagicMock()
        listing.__enter__.return_value.read.return_value = b'{"data":[{"id":"llama-3.1-8b"},{"id":"qwen/qwen3-32b"},{"id":"openai/gpt-oss-120b"}]}'
        with mock.patch.object(remote, "_call", return_value=listing):
            self.assertEqual(remote.pick_model(), "openai/gpt-oss-120b")

    def test_falls_back_to_the_mac_when_the_platform_fails(self):
        remote = OpenAICompatible("https://x.example/v1", "k", "m")
        boosted = Boosted(Local(), remote)
        with mock.patch.object(remote, "generate", side_effect=ProviderError("HTTP 429")):
            self.assertEqual(boosted.generate([ChatMessage("user", "hi")]).text, "local answer")
            self.assertEqual(boosted.generate([ChatMessage("user", "hi")]).text, "local answer")   # stays local a while
        with mock.patch.object(remote, "generate", return_value=ProviderResponse("fast", "boost", "m")):
            self.assertEqual(boosted.generate([ChatMessage("user", "hi")]).text, "local answer")   # still cooling down


if __name__ == "__main__":
    unittest.main()


class BoostRouteTests(JarvisTestCase):
    def test_bad_keys_and_platforms_are_refused_before_anything_is_saved(self):
        from jarvis.web import server
        app = self.make_app()
        for body in ({"platform": "groq", "key": "short"}, {"platform": "evil.example", "key": "x" * 30},
                     {"platform": "groq", "key": "a" * 25 + "\nJARVIS_HOST=0.0.0.0"}):
            with self.assertRaises(Exception):
                server._boost_set(app, server.Request((), {}, body, b"", "application/json"))
