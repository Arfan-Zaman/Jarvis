"""Reminders and recurring jobs, driven by a fake clock."""

import http.client
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone

from jarvis.providers.scripted import ScriptedProvider
from jarvis.safety import ActionCategory
from jarvis.scheduler import ACTOR, describe_recur, parse
from jarvis.tools import Tool
from jarvis.web import create_server
from support import JarvisTestCase

ZONE = timezone(timedelta(hours=11))                       # Sydney in summer
MONDAY_2PM = datetime(2026, 11, 16, 14, 5, tzinfo=ZONE)


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)

    def set(self, *args):
        self.now = datetime(*args, tzinfo=ZONE)


def fake_scheduler(app, start=MONDAY_2PM):
    clock = Clock(start)
    app.scheduler.clock = clock
    app.scheduler.inline_jobs = True
    app.notifications = []
    app.scheduler.notify = lambda title, message: app.notifications.append((title, message))
    return clock


class ParseTests(unittest.TestCase):
    def when(self, text, now=MONDAY_2PM):
        found = parse(text, now)
        return found and (found["at"].strftime("%a %d %H:%M"), found["rest"])

    def test_the_owners_phrasings(self):
        cases = {
            "Jarvis, remind me at 5pm to call the supplier": ("Mon 16 17:00", "call the supplier"),
            "remind me tomorrow morning to send the invoice": ("Tue 17 09:00", "send the invoice"),
            "remind me to call mum in an hour": ("Mon 16 15:05", "call mum"),
            "remind me in 20 minutes to check the oven": ("Mon 16 14:25", "check the oven"),
            "remind me in half an hour to stretch": ("Mon 16 14:35", "stretch"),
            "remind me on Friday at 3 that the rego is due": ("Fri 20 15:00", "the rego is due"),
            "remind me at 9 to lock up": ("Mon 16 21:00", "lock up"),              # the next 9 o'clock
            "remind me tomorrow at 5 to ring Sam": ("Tue 17 17:00", "ring Sam"),
            "remind me tonight to take out the bins": ("Mon 16 20:00", "take out the bins"),
            "remind me this afternoon to call the bank": ("Mon 16 16:00", "call the bank"),
            "remind me on 20 November to renew the insurance": ("Fri 20 09:00", "renew the insurance"),
            "remind me next monday to pay rent": ("Mon 23 09:00", "pay rent"),
            "remind me at noon to eat": ("Tue 17 12:00", "eat"),
            "set a reminder for 4:15pm to pick up the car": ("Mon 16 16:15", "pick up the car"),
            "remind me at 17:30 to leave": ("Mon 16 17:30", "leave"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.when(text), expected)

    def test_repeating(self):
        found = parse("every weekday at 8am check the used-car prices", MONDAY_2PM)
        self.assertEqual(found["recur"], {"days": [0, 1, 2, 3, 4], "time": "08:00"})
        self.assertEqual(found["at"].strftime("%a %d %H:%M"), "Tue 17 08:00")
        self.assertEqual(found["rest"], "check the used-car prices")
        friday = datetime(2026, 11, 20, 9, 0, tzinfo=ZONE)
        self.assertEqual(parse("every weekday at 8am x", friday)["at"].strftime("%a %d"), "Mon 23")
        both = parse("remind me every Monday and Thursday at 7:30am to water the plants", MONDAY_2PM)
        self.assertEqual(describe_recur(both["recur"]), "every Monday and Thursday at 7:30 am")
        self.assertEqual(parse("daily at 6pm summarise my tasks", MONDAY_2PM)["recur"]["time"], "18:00")
        self.assertEqual(parse("every morning check my email", MONDAY_2PM)["recur"]["time"], "09:00")

    def test_no_time_means_no_schedule(self):
        self.assertIsNone(parse("remind me to call 3 suppliers", MONDAY_2PM))
        self.assertIsNone(parse("what's the weather like", MONDAY_2PM))


class ReminderTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.model = ScriptedProvider([])                      # reminders never need the model
        self.app = self.make_app(provider=self.model)
        self.clock = fake_scheduler(self.app)

    def say(self, text, conversation_id=None):
        result = self.app.chat(text, conversation_id)
        return result["reply"], result["conversation"]["id"]

    def test_reminder_is_set_and_fires_once(self):
        reply, convo = self.say("Jarvis, remind me at 5pm to call the supplier")
        self.assertEqual(reply["content"], "Reminder set for today at 5:00 pm: call the supplier.")
        self.assertEqual(self.model.prompts, [])
        [item] = self.app.schedules.list()
        self.assertEqual((item["kind"], item["text"], item["conversation_id"]), ("reminder", "call the supplier", convo))

        self.clock.set(2026, 11, 16, 16, 59)
        self.assertEqual(self.app.scheduler.tick(), [])
        self.clock.set(2026, 11, 16, 17, 0, 10)
        self.assertEqual(self.app.scheduler.tick(), [item["id"]])
        self.assertEqual(self.app.scheduler.tick(), [])           # never twice
        self.assertEqual(self.app.notifications, [("JARVIS reminder", "call the supplier")])
        self.assertEqual(self.app.conversations.messages(convo)[-1]["content"], "Reminder: call the supplier.")
        self.assertEqual(self.app.schedules.get(item["id"])["status"], "done")
        alerts = self.app.scheduler.due_alerts()
        self.assertEqual([a["text"] for a in alerts], ["Reminder: call the supplier."])
        self.assertEqual(self.app.scheduler.due_alerts(), [])      # spoken once

    def test_reminder_goes_to_the_conversation_the_owner_is_in_now(self):
        _, first = self.say("remind me in 10 minutes to stretch")
        newer = self.app.conversations.create({"title": "Later chat"})["id"]
        self.clock.advance(minutes=10)
        self.app.scheduler.tick()
        self.assertEqual(self.app.conversations.messages(newer)[-1]["content"], "Reminder: stretch.")

    def test_works_with_no_model_connected(self):
        app = self.make_app()                                  # no provider at all
        fake_scheduler(app)
        reply = app.chat("remind me tomorrow morning to send the invoice")["reply"]
        self.assertEqual(reply["content"], "Reminder set for tomorrow at 9:00 am: send the invoice.")

    def test_late_reminder_says_when_it_was_due_and_stale_ones_are_skipped(self):
        self.say("remind me at 5pm to call the supplier")
        self.say("remind me at 6pm to lock up")
        self.clock.set(2026, 11, 16, 17, 30)                    # JARVIS was off at 5pm
        self.app.scheduler.tick()
        self.assertIn("(this was due at 5:00 pm)", self.app.notifications and
                      self.app.conversations.messages(self.app.conversations.list(limit=1)[0]["id"])[-1]["content"])
        self.clock.set(2026, 11, 17, 8, 0)                      # 14 hours late: skip it
        self.assertEqual(self.app.scheduler.tick(), [])
        lock = [i for i in self.app.schedules.list(status=None) if i["text"] == "lock up"][0]
        self.assertEqual(lock["status"], "done")
        self.assertIn("Missed", lock["last_result"])

    def test_list_and_cancel_by_voice(self):
        self.say("remind me at 5pm to call the supplier")
        self.say("remind me tomorrow at 9am to pay the rego")
        listed, _ = self.say("What reminders do I have?")
        self.assertIn("call the supplier — 5:00 pm today", listed["content"])
        self.assertIn("pay the rego — 9:00 am tomorrow", listed["content"])
        cancelled, _ = self.say("cancel the supplier reminder")
        self.assertEqual(cancelled["content"], "Cancelled: call the supplier.")
        self.assertEqual([i["text"] for i in self.app.schedules.list()], ["pay the rego"])
        self.clock.set(2026, 11, 16, 17, 1)
        self.assertEqual(self.app.scheduler.tick(), [])

    def test_router_can_schedule_what_the_patterns_miss(self):
        model = ScriptedProvider([{"mode": "schedule", "kind": "reminder", "when": "at 5pm", "what": "chase the bank"}])
        app = self.make_app(provider=model)
        fake_scheduler(app)
        reply = app.chat("ping me about chasing the bank around 5pm")["reply"]
        self.assertEqual(reply["content"], "Reminder set for today at 5:00 pm: chase the bank.")

    def test_bad_time_is_explained(self):
        result = self.app.tools.execute("schedule.add", {"text": "x", "when": "whenever"})
        self.assertFalse(result["ok"])
        self.assertIn("couldn't tell when", result["error"])


class JobTests(JarvisTestCase):
    def test_recurring_job_runs_as_the_scheduler_and_moves_on(self):
        model = ScriptedProvider([{"mode": "answer"}, "Used-car prices are flat this week."])
        app = self.make_app(provider=model)
        clock = fake_scheduler(app, datetime(2026, 11, 20, 9, 0, tzinfo=ZONE))      # a Friday
        reply = app.chat("every weekday at 8am check the used-car prices")["reply"]
        self.assertEqual(reply["content"], "Scheduled: every weekday at 8:00 am I'll check the used-car prices. "
                                           "First run: Monday 23 November at 8:00 am.")
        clock.set(2026, 11, 23, 8, 0)
        [item] = app.schedules.list()
        self.assertEqual(app.scheduler.tick(), [item["id"]])
        item = app.schedules.get(item["id"])
        self.assertEqual(item["next_at"], "2026-11-23T21:00:00.000+00:00")          # Tuesday 8am local
        self.assertEqual(item["last_result"], "Used-car prices are flat this week.")
        job_convo = app.conversations.get_with_messages(item["job_conversation_id"])
        self.assertEqual([m["role"] for m in job_convo["messages"]], ["user", "assistant"])
        current = app.conversations.list(limit=1)[0]["id"]
        self.assertIn("Used-car prices are flat", app.conversations.messages(current)[-1]["content"])
        self.assertEqual(app.notifications, [("JARVIS", "Done: check the used-car prices")])

    def test_job_needing_approval_waits_for_the_owner(self):
        app_holder = {}

        def payment(app, inputs, actor):
            app_holder["paid"] = True
            return {"paid": True}

        model = ScriptedProvider([
            {"mode": "act", "goal": "Pay the supplier invoice"},
            {"plan": [{"description": "Pay it", "tool": "test.pay"}]}, {"inputs": {}}])
        app = self.make_app(provider=model)
        app.tools.register(Tool("test.pay", "Pay a bill.", ActionCategory.FINANCIAL, payment))
        fake_scheduler(app)
        app.tools.execute("schedule.add", {"kind": "job", "when": "in 5 minutes", "text": "pay the supplier invoice"})
        app.scheduler.clock.advance(minutes=5)
        app.scheduler.tick()
        self.assertNotIn("paid", app_holder)
        [run] = [r for r in app.runs.list(kind="goal")]
        self.assertEqual((run["actor"], run["status"]), (ACTOR, "waiting_approval"))
        self.assertEqual(len(app.safety.list_approvals("pending")), 1)
        self.assertEqual(app.notifications, [("JARVIS", "Needs your approval: pay the supplier invoice")])

    def test_failed_job_is_reported_not_fatal(self):
        app = self.make_app(provider=ScriptedProvider([]))         # the model has nothing to say: it fails
        fake_scheduler(app)
        app.tools.execute("schedule.add", {"kind": "job", "when": "in 1 minute", "text": "check prices"})
        app.scheduler.clock.advance(minutes=1)
        app.scheduler.tick()
        self.assertEqual(app.notifications, [("JARVIS", "Scheduled job failed: check prices")])


class ReminderApiTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers={"Content-Type": "application/json"} if body is not None else {})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_list_add_cancel_and_due(self):
        clock = fake_scheduler(self.app)
        status, made = self.call("POST", "/api/reminders", {"text": "call the supplier", "when": "at 5pm"})
        self.assertEqual((status, made["summary"]), (201, "Reminder set for today at 5:00 pm: call the supplier."))
        status, listed = self.call("GET", "/api/reminders")
        self.assertEqual([(i["text"], i["when"]) for i in listed["items"]], [("call the supplier", "5:00 pm today")])
        self.assertEqual(self.call("POST", "/api/reminders", {"text": "x", "when": "someday"})[0], 400)

        clock.set(2026, 11, 16, 17, 0)
        self.app.scheduler.tick()
        due = self.call("GET", "/api/reminders/due")[1]["items"]
        self.assertEqual([d["text"] for d in due], ["Reminder: call the supplier."])
        self.assertEqual(self.call("GET", "/api/reminders/due")[1]["items"], [])

        other = self.call("POST", "/api/reminders", {"text": "lock up", "when": "every day at 9pm"})[1]
        status, cancelled = self.call("POST", f"/api/reminders/{other['id']}/cancel")
        self.assertEqual((status, cancelled["status"]), (200, "cancelled"))
        self.assertEqual(self.call("GET", "/api/reminders")[1]["items"], [])
        self.assertEqual(self.call("POST", "/api/reminders/999/cancel")[0], 404)


if __name__ == "__main__":
    unittest.main()
