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

    BOOTSTRAP = {"services": [[["com", "net"], ["https://rdap.verisign.com/com/v1/"]],
                              [["au"], ["https://rdap.cctld.au/rdap/"]]]}

    def test_domain_lookup_reads_the_registry_record(self):
        record = {"ldhName": "MONSOORMOTORS.COM.AU", "status": ["server renew prohibited"],
                  "events": [{"eventAction": "registration", "eventDate": "2021-03-04T01:02:03Z"},
                             {"eventAction": "expiration", "eventDate": "2027-03-04T01:02:03Z"}],
                  "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                                                                 ["fn", {}, "text", "Example Registrar Pty Ltd"]]]}],
                  "nameservers": [{"ldhName": "NS1.EXAMPLE.NET"}]}
        with mock.patch.object(opendata, "_json", side_effect=[self.BOOTSTRAP, record]) as fetch:
            out = opendata.open_domain(None, {"domain": "https://www.MonsoorMotors.com.au/cars"}, "t")
        self.assertEqual(fetch.call_args_list[1].args[0], "https://rdap.cctld.au/rdap/domain/monsoormotors.com.au")
        self.assertEqual((out["domain"], out["registered"], out["registrar"]),
                         ("monsoormotors.com.au", True, "Example Registrar Pty Ltd"))
        self.assertEqual((out["registered_on"], out["expires_on"], out["nameservers"]),
                         ("2021-03-04", "2027-03-04", ["ns1.example.net"]))

    def test_domain_unknown_to_the_registry_looks_available(self):
        import urllib.error
        missing = opendata.WebError("rdap.cctld.au answered HTTP 404")
        missing.__cause__ = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch.object(opendata, "_json", side_effect=[self.BOOTSTRAP, missing]):
            out = opendata.open_domain(None, {"domain": "aureusdetailing.com.au"}, "t")
        self.assertFalse(out["registered"])
        self.assertIn("available", out["note"])
        self.assertIn("auDA", out["note"])

    def test_domain_must_look_like_a_domain(self):
        self.assertFalse(self.make_app().tools.execute("open.domain", {"domain": "not a domain"})["ok"])

    def test_domain_questions_skip_the_browser(self):
        self.assertTrue(conversation.DOMAIN_CHECK.search(
            "Search for the domain 'aureusdetailing.com.au' to check its availability and ownership details."))
        self.assertTrue(conversation.DOMAIN_CHECK.search("who owns monsoormotors.com.au?"))
        self.assertTrue(conversation.DOMAIN_CHECK.search("whois example.net"))
        self.assertFalse(conversation.DOMAIN_CHECK.search("Is report.pdf available in Downloads?"))
        self.assertFalse(conversation.DOMAIN_CHECK.search("What's the weather in Perth tomorrow?"))

    def test_open_tools_are_read_only_and_automatic(self):
        app = self.make_app()
        for tool in app.tools.list():
            if tool["name"].startswith("open."):
                self.assertEqual((tool["permission"], tool["requires_approval"]), ("web_read", False))


class BrowserAgentTests(unittest.TestCase):
    def test_refs_are_read_however_the_model_writes_them(self):
        from jarvis.tools.browser import _ref
        for step in ({"ref": "e5"}, {"ref": "[ref=e5]"}, {"ref": "ref=e5"}, {"target": "e5"}, {"target": "[ref=e5]"}):
            self.assertEqual(_ref(step), "e5", step)
        self.assertEqual(_ref({}), "")

    def test_type_step_sends_playwright_its_target(self):
        from jarvis.tools import browser
        page = "```yaml\n- textbox \"Domain\" [ref=e5]\n```"
        replies = iter(['{"action": "type", "target": "[ref=e5]", "element": "Domain box", "text": "x.com.au"}',
                        '{"action": "done", "answer": "ok"}'])
        app = mock.Mock()
        app.provider.generate.side_effect = lambda *a, **k: mock.Mock(text=next(replies))
        calls = []
        with mock.patch.object(browser.Browser, "call", side_effect=lambda _app, name, args: calls.append((name, args)) or page):
            out = browser._browser_use(app, {"task": "check a domain"})
        self.assertTrue(out["done"])
        typed = [args for name, args in calls if name == "browser_type"]
        self.assertEqual(typed[0]["target"], "e5")
        self.assertEqual(typed[0]["text"], "x.com.au")


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
