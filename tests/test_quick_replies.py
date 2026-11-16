import os
import unittest
from unittest import mock

from jarvis.engine.conversation import ROUTER, SMALL_TALK
from jarvis.providers.base import ProviderError, ProviderResponse, ProviderStatus
from jarvis.providers.boost import Boosted, back_off
from jarvis.providers.ollama import keep_alive
from jarvis.providers.scripted import ScriptedProvider
from support import JarvisTestCase


class SmallTalkTests(JarvisTestCase):
    def chat(self, replies, *texts):
        self.model = ScriptedProvider(replies)
        self.app = self.make_app(provider=self.model)
        conversation = None
        for text in texts:
            result = self.app.chat(text, conversation)
            conversation = result["conversation"]["id"]
        return result["reply"]

    def test_greetings_and_thanks_skip_the_routing_step(self):
        reply = self.chat(["Morning. What's up?"], "Hey Jarvis, how are you today?")
        self.assertEqual(reply["content"], "Morning. What's up?")
        self.assertEqual(len(self.model.prompts), 1)                  # one model call, no router
        system = self.model.prompts[0][0].content
        self.assertNotIn(ROUTER[:60], system)
        self.assertIn("This is small talk", system)

    def test_a_request_inside_a_greeting_is_still_routed(self):
        self.chat([{"mode": "answer"}, "Paris."], "hi jarvis, what's the capital of France?")
        self.assertEqual(len(self.model.prompts), 2)
        self.assertIn(ROUTER[:60], self.model.prompts[0][0].content)
        self.assertNotIn("This is small talk", self.model.prompts[1][0].content)

    def test_what_counts_as_small_talk(self):
        for text in ("hi", "Hello Jarvis!", "thanks mate", "thank you so much", "good morning", "ok cool",
                     "Jarvis?", "how's it going", "see you later"):
            self.assertTrue(SMALL_TALK.match(text), text)
        for text in ("hi jarvis what's on my calendar", "thanks, now email Sam", "ok send it",
                     "remind me at 5", "hello world in python", "good morning briefing please"):
            self.assertFalse(SMALL_TALK.match(text), text)


class FakeOllama:
    name, model = "ollama", "qwen-test"

    def __init__(self, up_after=0, fail=False):
        self.checks, self.up_after, self.fail, self.calls = 0, up_after, fail, []

    def status(self):
        self.checks += 1
        return ProviderStatus(name="ollama", kind="local", configured=True,
                              available=self.checks > self.up_after, model=self.model, detail="")

    def generate(self, messages, json_output=False, on_token=None):
        if self.fail:
            raise ProviderError("broken")
        self.calls.append((messages[0].content, json_output))
        return ProviderResponse("{}" if json_output else "hi", "ollama", self.model)


class WarmUpTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(provider=ScriptedProvider([]))

    def test_waits_for_ollama_then_loads_both_prompts(self):
        local = FakeOllama(up_after=2)
        self.app.provider = local
        self.assertTrue(self.app.conversation.warm_up(wait_seconds=5, pause=0))
        self.assertEqual(local.checks, 3)
        self.assertEqual([j for _, j in local.calls], [True, False])
        self.assertTrue(local.calls[0][0].startswith(ROUTER[:60]))

    def test_warms_the_macs_model_behind_boost(self):
        local = FakeOllama()
        self.app.provider = Boosted(local, mock.Mock())
        self.assertTrue(self.app.conversation.warm_up(wait_seconds=1, pause=0))
        self.assertEqual(len(local.calls), 2)

    def test_gives_up_quietly(self):
        self.app.provider = FakeOllama(up_after=10 ** 6)
        self.assertFalse(self.app.conversation.warm_up(wait_seconds=0, pause=0))
        self.app.provider = FakeOllama(fail=True)
        self.assertFalse(self.app.conversation.warm_up(wait_seconds=1, pause=0))
        self.assertFalse(self.app.conversation.warm_up())         # the scripted test model is not Ollama


class SpeedSettingsTests(unittest.TestCase):
    def test_model_stays_loaded_for_hours(self):
        with mock.patch.dict(os.environ, {"JARVIS_KEEP_ALIVE": ""}):
            self.assertEqual(keep_alive(), "8h")
        with mock.patch.dict(os.environ, {"JARVIS_KEEP_ALIVE": "-1"}):
            self.assertEqual(keep_alive(), "-1")
        with mock.patch.dict(os.environ, {"JARVIS_KEEP_ALIVE": "forever; rm"}):
            self.assertEqual(keep_alive(), "8h")

    def test_boost_comes_back_as_soon_as_the_rate_limit_allows(self):
        self.assertEqual(back_off("HTTP 429 (retry after 7s): limit"), 8)
        self.assertEqual(back_off("Rate limit reached. Please try again in 1m2.5s."), 63.5)
        self.assertEqual(back_off("Please try again in 450ms"), 5)
        self.assertEqual(back_off("cannot reach the boost platform"), 120)
        self.assertEqual(back_off("retry after 900s"), 120)

    def test_rate_limit_uses_the_mac_only_for_the_asked_time(self):
        local, remote = FakeOllama(), mock.Mock()
        remote.generate.side_effect = ProviderError("HTTP 429 (retry after 3s): limit")
        boosted = Boosted(local, remote)
        with mock.patch("jarvis.providers.boost.time.time", return_value=1000.0):
            self.assertEqual(boosted.generate([mock.Mock(content="x")]).text, "hi")
        self.assertEqual(boosted._down_until, 1005.0)        # 3 s asked, +1, at least 5

    def test_background_learning_never_uses_the_boost_quota(self):
        from jarvis.learner import Learner
        local = FakeOllama()
        learner = Learner.__new__(Learner)
        learner.app = mock.Mock(provider=Boosted(local, mock.Mock()))
        self.assertIs(learner._model(), local)


if __name__ == "__main__":
    unittest.main()
