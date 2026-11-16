"""Local-first JARVIS: open-data tools, the gap loop, and Claude only when needed."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from support import JarvisTestCase

from jarvis.providers.scripted import ScriptedProvider

from jarvis import gaps
from jarvis.engine import conversation
from jarvis.tools import opendata


class OpenDataTests(JarvisTestCase):
    def test_weather_shapes_open_meteo(self):
        replies = [{"results": [{"name": "Perth", "admin1": "Western Australia", "country": "Australia",
                                 "latitude": -31.9, "longitude": 115.9}]},
                   {"current": {"temperature_2m": 26.6, "weather_code": 3},
                    "daily": {"time": ["2026-11-16"], "weather_code": [61], "temperature_2m_min": [15],
                              "temperature_2m_max": [27], "precipitation_probability_max": [40], "uv_index_max": [9]}}]
        with mock.patch.object(opendata, "_json", side_effect=replies):
            out = opendata.open_weather(None, {"place": "Perth, Australia", "days": 1}, "t")
        self.assertEqual(out["place"], "Perth, Western Australia, Australia")
        self.assertEqual((out["now"]["temperature_c"], out["now"]["sky"]), (26.6, "overcast"))
        self.assertEqual(out["days"][0]["sky"], "light rain")

    def test_currency_falls_back_for_codes_the_ecb_lacks(self):
        replies = [{"date": "2026-11-16", "rates": {"USD": 0.65}}, {"rates": {"BDT": 84.7}}]
        with mock.patch.object(opendata, "_json", side_effect=replies):
            out = opendata.open_currency(None, {"from": "aud", "to": "USD,BDT", "amount": 100}, "t")
        self.assertEqual(out["converted"], {"USD": 65.0, "BDT": 8470.0})
        self.assertIn("open.er-api.com", out["source"])

    def test_vin_must_look_like_a_vin(self):
        self.assertFalse(self.make_app().tools.execute("open.vin", {"vin": "abc"})["ok"])

    def test_open_tools_are_read_only_and_automatic(self):
        app = self.make_app()
        for tool in app.tools.list():
            if tool["name"].startswith("open."):
                self.assertEqual((tool["permission"], tool["requires_approval"]), ("web_read", False))


class GapLoopTests(JarvisTestCase):
    def test_gaps_are_counted_not_duplicated(self):
        app = self.make_app()
        gaps.record(app, "web", "Find the WA rego price", "nothing found")
        gaps.record(app, "web", "find the wa rego price", "still nothing")
        [gap] = gaps.open_gaps(app)
        self.assertEqual((gap["count"], gap["reason"]), (2, "still nothing"))
        self.assertTrue(gaps.due(app))

    def test_teach_hands_gaps_to_a_review_and_clears_them(self):
        app = self.make_app()
        gaps.record(app, "browser", "Book a service slot on mechanic.example", "ran out of steps")
        seen = {}
        with mock.patch.object(app.selfreview, "once", side_effect=lambda focus=None: seen.setdefault("focus", focus)
                               and {"ok": True, "branch": "jarvis/self-review-2026-11-16"}):
            out = app.selfreview.teach()
        self.assertEqual(out["branch"], "jarvis/self-review-2026-11-16")
        self.assertIn("BUILD THE ABILITY INTO JARVIS", seen["focus"])
        self.assertIn("Book a service slot", seen["focus"])
        self.assertEqual(gaps.open_gaps(app), [])
        self.assertFalse(gaps.due(app))

    def test_owner_can_ask_jarvis_to_learn_something(self):
        app = self.make_app(provider=ScriptedProvider([]))
        with mock.patch.object(app.selfreview, "teach_soon") as soon:
            reply = app.chat("Jarvis, learn how to read my supplier's PDF invoices")["reply"]
        self.assertEqual(gaps.open_gaps(app)[0]["request"], "read my supplier's PDF invoices")
        if "claude.work" in app.tools.names():
            soon.assert_called_once()
            self.assertIn("build it into me", reply["content"])


class LocalFirstTests(JarvisTestCase):
    def test_brain_is_local_unless_asked(self):
        with mock.patch.dict(os.environ, {"JARVIS_BRAIN": ""}):
            self.assertEqual(conversation.brain(), "local")
        with mock.patch.dict(os.environ, {"JARVIS_BRAIN": "claude"}):
            self.assertEqual(conversation.brain(), "claude")

    def test_only_code_and_builds_count_as_hard_work(self):
        self.assertIsNone(conversation.HARD_WORK.search("Plan my week so that I can grow the detailing business faster"))
        self.assertIsNotNone(conversation.HARD_WORK.search("Write a python script that renames my photos by date taken"))

    def test_actions_and_open_data_skip_the_quick_web_answer(self):
        self.assertTrue(conversation.Conversation.DOINGS.search("Send the supplier an email"))
        self.assertTrue(conversation.OPEN_DATA.search("What's the weather in Perth tomorrow?"))
        self.assertFalse(conversation.Conversation.DOINGS.search("Who won the cricket last night?"))


if __name__ == "__main__":
    unittest.main()
