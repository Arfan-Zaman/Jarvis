"""The spoken morning briefing, with the model scripted and every tool faked (no Claude, no Mac)."""

import http.client
import json
import threading
from datetime import datetime, timedelta, timezone
from unittest import mock

from jarvis.common import JarvisError
from jarvis.briefing import BRIEFING_KEY, HEADLINES_KEY, Briefing
from jarvis.learner import ACTOR as LEARN_ACTOR
from jarvis.providers.scripted import ScriptedProvider
from support import JarvisTestCase

SPOKEN = ("Good morning. Two things are due today, the Corolla roadworthy and the invoice for the "
          "Mazda detail. One approval is waiting for you, and I have a small self-review proposal. "
          "Overnight I learned dealers must give a statutory warranty on some used cars. In the news, "
          "used car prices eased again this month. The Mac is fine. Have a good day.")
MAC = {"battery": "84%; discharging; 6:10 remaining", "disk_free": "120 GB", "disk_used": "380 GB",
       "disk_total": "500 GB", "wifi_ip": "192.168.1.5", "uptime": "up 3 days", "open_apps": ["Finder"]}
NEWS = {"query": "q", "facts": [
    {"fact": "Used car prices in Australia eased for a third month in October.", "url": "https://news.example.org/prices"},
    {"fact": "A new ceramic coating standard was published for detailers.", "url": "https://news.example.org/coating"}]}


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class BriefingTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.research_calls = 0
        self.research = lambda app, inputs, actor: NEWS
        self.when = datetime.now().astimezone().replace(hour=7, minute=30)

    def fake(self, name, handler):
        tool = self.app.tools.get(name)
        self.app.tools._tools[name] = tool.__class__(tool.name, tool.description, tool.category, handler, tool.inputs)

    def setup_app(self, replies, news_wait=1.0):
        self.model = ScriptedProvider(replies)
        self.app = self.make_app(provider=self.model)

        def research(app, inputs, actor):
            self.research_calls += 1
            return self.research(app, inputs, actor)
        self.fake("claude.research", research)

        def news(app, inputs, actor):             # the local briefing reads open.news; same fixture, its shape
            found = research(app, inputs, actor)
            return {"topic": inputs["topic"], "headlines": [{"title": f["fact"], "url": f["url"]} for f in found["facts"]]}
        self.fake("open.news", news)
        self.fake("mac.status", lambda app, inputs, actor: MAC)
        patch = mock.patch.object(self.app.selfreview, "proposals",
                                  return_value=[{"branch": "jarvis/self-review-2026-11-15"}])
        patch.start()
        self.addCleanup(patch.stop)
        self.app.briefing = Briefing(self.app, now=lambda: self.when, news_wait=news_wait)
        return self.app

    def seed(self):
        app = self.app
        app.create("tasks", {"title": "Corolla roadworthy", "due_at": iso(self.when)})
        app.create("tasks", {"title": "Chase the Hilux buyer", "due_at": iso(self.when - timedelta(days=2))})
        app.create("tasks", {"title": "Order microfibre towels", "priority": "high"})
        done = app.create("tasks", {"title": "Old finished job", "due_at": iso(self.when)})
        app.tasks.complete(done["id"])
        app.tools.execute("memory.save", {
            "content": "Dealers must give a statutory warranty on some used cars. (source: https://law.example.org/w)",
            "category": "learned"}, actor=LEARN_ACTOR)
        old = app.tools.execute("memory.save", {"content": "An old learned fact about tyres from last week.",
                                                "category": "learned"}, actor=LEARN_ACTOR)
        self.sql("UPDATE memories SET created_at = ? WHERE id = ?",
                 (iso(self.when - timedelta(days=4)), old["output"]["id"]))
        app.tools.execute("memory.save", {"content": "The owner likes short answers."}, actor="user")
        victim = app.create("tasks", {"title": "Something to delete"})
        self.assertEqual(app.delete("tasks", victim["id"])["status"], "approval_required")

    def test_spoken_briefing_with_sources_kept_for_the_day(self):
        self.setup_app([SPOKEN])
        self.seed()
        briefing = self.app.briefing.get()
        self.assertEqual(briefing["by"], "model")
        self.assertEqual(briefing["text"], SPOKEN)
        self.assertFalse(briefing["partial"])
        self.assertFalse(briefing["cached"])
        facts = self.model.prompts[0][1].content
        for expected in ("Corolla roadworthy", "Chase the Hilux buyer", "Order microfibre towels",
                         "jarvis/self-review-2026-11-15", "statutory warranty", "eased for a third month", "120 GB"):
            self.assertIn(expected, facts)
        for unwanted in ("Old finished job", "tyres", "short answers"):
            self.assertNotIn(unwanted, facts)
        sections = briefing["sections"]
        self.assertEqual(sections["tasks"]["due_today"], ["Corolla roadworthy"])
        self.assertEqual(sections["tasks"]["overdue"], ["Chase the Hilux buyer"])
        self.assertEqual(sections["waiting"]["approval_count"], 1)
        self.assertEqual(sections["learned"]["count"], 1)
        urls = {s["url"]: s["kind"] for s in briefing["sources"]}
        self.assertEqual(urls, {"https://law.example.org/w": "learned", "https://news.example.org/prices": "headline",
                                "https://news.example.org/coating": "headline"})
        # the same day: kept, no new research and no new model call
        again = self.app.briefing.get()
        self.assertTrue(again["cached"])
        self.assertEqual(again["text"], SPOKEN)
        self.assertEqual(self.research_calls, 1)
        self.assertEqual(len(self.model.prompts), 1)
        # a new day: a new briefing and new headlines
        self.model.replies.append(SPOKEN.replace("Good morning", "Morning"))
        self.when += timedelta(days=1)
        tomorrow = self.app.briefing.get()
        self.assertFalse(tomorrow["cached"])
        self.assertTrue(tomorrow["text"].startswith("Morning"))
        self.assertEqual(self.research_calls, 2)

    def test_plain_sentences_when_the_model_is_unavailable(self):
        self.setup_app([])                        # the scripted stand-in raises ProviderError
        self.seed()
        briefing = self.app.briefing.get()
        self.assertEqual(briefing["by"], "plain")
        text = briefing["text"]
        self.assertTrue(text.startswith("Good morning."))
        for expected in ("Due today: Corolla roadworthy.", "Overdue: Chase the Hilux buyer.", "4 open tasks",
                         "1 approval", "self-review proposal", "statutory warranty", "eased for a third month", "120 GB free"):
            self.assertIn(expected, text)
        self.assertNotIn("http", text)
        self.assertLess(len(text.split()), 190)

    def test_model_reply_cleaned_or_replaced(self):
        long_reply = "Good morning. " + "This goes on and on. " * 60
        self.setup_app(["**Good morning.** Here is a link https://x.example.org/a and " + SPOKEN, long_reply])
        cleaned = self.app.briefing.get()["text"]
        self.assertNotIn("*", cleaned)
        self.assertNotIn("https://", cleaned)
        redo = self.app.briefing.get(refresh=True)
        self.assertEqual(redo["by"], "plain")    # far too long to speak: plain sentences instead

    def test_failed_research_still_gives_a_kept_briefing(self):
        def broken(app, inputs, actor):
            raise JarvisError("Claude Code is not installed")
        self.research = broken
        self.setup_app([SPOKEN])
        briefing = self.app.briefing.get()
        self.assertFalse(briefing["partial"])
        self.assertEqual(briefing["sections"]["headlines"], [])
        self.assertEqual(self.app.settings.get(BRIEFING_KEY)["text"], SPOKEN)

    def test_slow_headlines_are_not_waited_for_and_picked_up_next_time(self):
        release = threading.Event()

        def slow(app, inputs, actor):
            release.wait(5)
            return NEWS
        self.research = slow
        self.setup_app([SPOKEN, SPOKEN], news_wait=0.05)
        first = self.app.briefing.get()
        self.assertTrue(first["partial"])
        self.assertIsNone(first["sections"]["headlines"])
        self.assertIsNone(self.app.settings.get(BRIEFING_KEY))      # not kept without its headlines
        release.set()
        self.app.briefing._news_done.wait(5)
        self.assertEqual(len(self.app.settings.get(HEADLINES_KEY)["items"]), 2)
        second = self.app.briefing.get()
        self.assertFalse(second["partial"])
        self.assertEqual(len([s for s in second["sources"] if s["kind"] == "headline"]), 2)
        self.assertEqual(self.research_calls, 1)

    def test_endpoint(self):
        from jarvis.web import create_server
        self.setup_app([SPOKEN, SPOKEN])
        server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def get(path):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            try:
                conn.request("GET", path)
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()
        status, body = get("/api/briefing")
        self.assertEqual(status, 200)
        self.assertEqual(body["text"], SPOKEN)
        self.assertEqual(body["day"], self.when.date().isoformat())
        self.assertTrue(get("/api/briefing")[1]["cached"])
        self.assertFalse(get("/api/briefing?refresh=1")[1]["cached"])
        self.assertEqual(len(self.model.prompts), 2)
