"""Continuous learning: one pass, with the model scripted and the web faked (no network)."""

from unittest import mock

from jarvis.providers.scripted import ScriptedProvider
from jarvis.tools import web
from support import JarvisTestCase

PAGE = "Dealers in Australia must give a statutory warranty on used cars under certain conditions. " * 10


class LearnerTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.model = ScriptedProvider([
            {"query": "used car warranty rules Australia", "why": "The owner sells used cars."},
            {"facts": ["Licensed dealers must give a statutory warranty on some used cars.", "tiny"]},
            {"facts": []},
        ])
        self.app = self.make_app(provider=self.model)
        search = {"query": "q", "results": [{"title": "A", "url": "https://example.org/a"},
                                            {"title": "B", "url": "https://example.org/b"}], "searched": [], "errors": []}
        page = {"url": "https://example.org/a", "title": "A", "text": PAGE, "truncated": False}
        self.patches = [mock.patch.object(web, "web_search", return_value=search),
                        mock.patch.object(web, "web_fetch", return_value=page)]
        for p in self.patches:
            p.start()
        # the registry keeps references to the handlers: re-point them at the fakes
        for name, fake in (("web.search", web.web_search), ("web.fetch", web.web_fetch)):
            tool = self.app.tools.get(name)
            self.app.tools._tools[name] = tool.__class__(tool.name, tool.description, tool.category, fake, tool.inputs)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_one_pass_saves_sourced_unverified_facts(self):
        out = self.app.learner.once()
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["query"], out["saved"], len(out["read"])), ("used car warranty rules Australia", 1, 2))
        learned = [m for m in self.app.memory.list() if m["source"] == "jarvis:learn"]
        self.assertEqual(len(learned), 1)                       # the too-short "tiny" fact was dropped
        self.assertIn("(source: https://example.org/a)", learned[0]["content"])
        self.assertEqual((learned[0]["category"], learned[0]["verification_status"]), ("learned", "unverified"))
        self.assertEqual(self.app.learner.status()["recent"], ["used car warranty rules Australia"])

    def test_a_repeated_query_is_refused(self):
        self.app.settings.set("learn.recent_queries", ["used car warranty rules Australia"])
        out = self.app.learner.once()
        self.assertFalse(out["ok"])
        self.assertEqual(self.app.memory.list(), [])
