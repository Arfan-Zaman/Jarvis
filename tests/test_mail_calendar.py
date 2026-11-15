import subprocess
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from jarvis.engine.conversation import Conversation, system_prompt
from jarvis.tools import mail_calendar as mc
from support import JarvisTestCase

FS, RS = mc.FS, mc.RS


def done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def record(*fields):
    return FS.join(str(f) for f in fields)


class FakeApps:
    """Stands in for osascript: answers by which script was asked, and records every call."""

    def __init__(self, **answers):
        self.answers, self.calls = answers, []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "open":
            return done()
        name = next(n for n in ("MAIL_LIST", "MAIL_SEARCH", "MAIL_BODIES", "MAIL_COMPOSE", "CAL_EVENTS",
                                "CAL_EXCLUDED", "CAL_ADD", "CAL_NAMES") if getattr(mc, n) == args[2])
        answer = self.answers.get(name, "")
        return answer(args) if callable(answer) else (answer if isinstance(answer, subprocess.CompletedProcess)
                                                      else done(answer))

    def scripts(self):
        return [next(n for n in dir(mc) if n.isupper() and getattr(mc, n) == a[2]) for a in self.calls if a[0] == "osascript"]


class MailCalendarCase(JarvisTestCase):
    def setUp(self):
        super().setUp()
        mc._cache.clear()

    def fake(self, **answers):
        apps = FakeApps(**answers)
        patcher = mock.patch.object(mc.subprocess, "run", side_effect=apps)
        patcher.start()
        self.addCleanup(patcher.stop)
        return apps

    def run_tool(self, name, inputs=None, **options):
        return self.app.tools.execute(name, inputs, **options)

    def ok(self, name, inputs=None, **options):
        result = self.run_tool(name, inputs, **options)
        self.assertTrue(result["ok"], result)
        return result["output"]


class MailReadTests(MailCalendarCase):
    def test_recent_mail_is_newest_first_with_the_start_of_each_message(self):
        listing = RS.join([
            record(11, "Old <old@example.com>", "Older", "2026-11-14T09:00:00", "true", "", ""),
            record(12, "Sam <sam@example.com>", "Quote ready", "2026-11-16T08:30:00", "false", "", ""),
            record(13, "Ana <ana@example.com>", "", "2026-11-15T10:00:00", "false", "", ""),
        ])
        bodies = RS.join([
            record(12, "Sam <sam@example.com>", "Quote ready", "2026-11-16T08:30:00", "false", "iCloud", "INBOX",
                   "me@example.com", "Hi,\n\n\n\nthe quote is attached."),
            record(13, "Ana <ana@example.com>", "", "2026-11-15T10:00:00", "false", "iCloud", "INBOX", "", "Lunch?"),
        ])
        apps = self.fake(MAIL_LIST=listing, MAIL_BODIES=bodies)
        out = self.ok("mail.recent", {"limit": 2})
        self.assertEqual((out["found"], out["unread"]), (3, 2))
        self.assertEqual([m["id"] for m in out["messages"]], [12, 13])
        self.assertEqual(out["messages"][0]["body"], "Hi,\n\nthe quote is attached.")
        self.assertEqual(out["messages"][1]["subject"], "(no subject)")
        self.assertTrue(out["messages"][0]["unread"])
        # values travel as arguments after the fixed script, never inside it
        self.assertEqual(apps.calls[0][:3], ["osascript", "-e", mc.MAIL_LIST])
        self.assertEqual(apps.calls[0][3:], ["3", ""])
        self.assertEqual(apps.calls[1][3:], ["500", "||12", "||13"])
        self.assertEqual(self.app.tools.get("mail.recent").category.value, "read")

    def test_unread_only_and_no_preview(self):
        apps = self.fake(MAIL_LIST=record(5, "a@b.com", "Hi", "2026-11-16T08:00:00", "false", "", ""))
        out = self.ok("mail.recent", {"unread_only": True, "preview_chars": 0, "days": 1})
        self.assertNotIn("body", out["messages"][0])
        self.assertEqual(apps.scripts(), ["MAIL_LIST"])
        self.assertEqual(apps.calls[0][3:], ["1", "1"])

    def test_search_text_cannot_become_code(self):
        sneaky = '" & (do shell script "rm -rf ~") & "'
        apps = self.fake(MAIL_SEARCH="")
        out = self.ok("mail.search", {"query": sneaky})
        self.assertEqual(out["found"], 0)
        self.assertEqual(apps.calls[0][2], mc.MAIL_SEARCH)      # the script text is untouched
        self.assertEqual(apps.calls[0][3], sneaky)              # the query is only an argument
        self.assertNotIn("rm -rf", mc.MAIL_SEARCH)

    def test_search_everywhere_drops_gmail_twins_and_reads_matches(self):
        hit = ("Sam <sam@example.com>", "Invoice 7", "2026-11-10T12:00:00", "true")
        listing = RS.join([record(1, *hit, "Gmail", "INBOX"), record(2, *hit, "Gmail", "All Mail"),
                           record(3, "Bo <bo@example.com>", "Invoice 6", "2026-10-01T12:00:00", "true", "Work", "Archive")])
        apps = self.fake(MAIL_SEARCH=listing, MAIL_BODIES=lambda args: done(RS.join(
            record(a.split("|")[-1], *hit, "x", "y", "", "text") for a in args[4:])))
        out = self.ok("mail.search", {"query": "invoice", "where": "everywhere"})
        self.assertEqual(out["found"], 2)
        self.assertEqual([m["id"] for m in out["messages"]], [1, 3])
        self.assertEqual(apps.calls[0][5], "1")
        self.assertEqual(apps.calls[1][4:], ["Gmail|INBOX|1", "Work|Archive|3"])
        self.assertIn("Trash", apps.calls[0][6].title())

    def test_empty_search_is_refused(self):
        self.fake()
        self.assertFalse(self.run_tool("mail.search", {"query": "  "})["ok"])

    def test_read_one_message(self):
        self.fake(MAIL_BODIES=record(9, "a@b.com", "Hello", "2026-11-16T08:00:00", "true", "iCloud", "INBOX",
                                     "me@x.com", "Full text"))
        out = self.ok("mail.read", {"id": 9})
        self.assertEqual((out["body"], out["to"], out["account"]), ("Full text", "me@x.com", "iCloud"))

    def test_missing_message_is_explained(self):
        self.fake(MAIL_BODIES="")
        result = self.run_tool("mail.read", {"id": 404})
        self.assertFalse(result["ok"])
        self.assertIn("moved or deleted", result["error"])

    def test_automation_not_allowed_explains_the_fix(self):
        self.fake(MAIL_LIST=done("", 1, "execution error: Not authorized to send Apple events to Mail. (-1743)"))
        result = self.run_tool("mail.recent")
        self.assertFalse(result["ok"])
        self.assertIn("Privacy & Security > Automation", result["error"])

    def test_app_that_was_quitting_is_tried_once_more(self):
        answers = iter([done("", 1, "Mail got an error: Application isn’t running. (-600)"), done("")])
        apps = self.fake(MAIL_LIST=lambda args: next(answers))
        with mock.patch.object(mc.time, "sleep"):
            self.assertTrue(self.run_tool("mail.recent")["ok"])
        self.assertEqual(apps.scripts(), ["MAIL_LIST", "MAIL_LIST"])


class MailWriteTests(MailCalendarCase):
    def test_draft_opens_in_mail_and_never_sends(self):
        apps = self.fake(MAIL_COMPOSE="drafted")
        out = self.ok("mail.draft", {"to": "Sam <sam@example.com>, bo@example.com", "subject": "Hi", "body": "Hello"})
        self.assertEqual(out["to"], ["sam@example.com", "bo@example.com"])
        self.assertIn("Nothing was sent", out["note"])
        args = apps.calls[0]
        self.assertEqual(args[3:], ["sam@example.com\nbo@example.com", "", "Hi", "Hello", ""])   # "" = do not send
        self.assertEqual(self.app.tools.get("mail.draft").category.value, "write")

    def test_reply_draft_answers_the_sender_and_quotes_them(self):
        original = record(12, "Sam Lee <sam@example.com>", "Quote ready", "2026-11-16T08:30:00", "true",
                          "iCloud", "INBOX", "me@example.com", "Line one\nLine two")
        apps = self.fake(MAIL_BODIES=original, MAIL_COMPOSE="drafted")
        out = self.ok("mail.draft", {"reply_to_id": 12, "body": "Thanks, looks good."})
        self.assertEqual((out["to"], out["subject"]), (["sam@example.com"], "Re: Quote ready"))
        body = apps.calls[1][6]
        self.assertTrue(body.startswith("Thanks, looks good."))
        self.assertIn("Sam Lee <sam@example.com> wrote:\n> Line one\n> Line two", body)
        self.assertEqual(apps.calls[1][7], "")

    def test_bad_addresses_are_refused_before_mail_is_touched(self):
        apps = self.fake()
        result = self.run_tool("mail.draft", {"to": "sam at example", "body": "x"})
        self.assertFalse(result["ok"])
        self.assertIn("not an email address", result["error"])
        self.assertEqual(apps.calls, [])

    def test_send_waits_for_the_owner_every_time_and_sends_only_what_was_approved(self):
        apps = self.fake(MAIL_COMPOSE="sent")
        message = {"to": "sam@example.com", "subject": "Quote", "body": "Yes, go ahead."}
        first = self.run_tool("mail.send", message, actor="jarvis-core")
        self.assertEqual(first["status"], "approval_required")
        self.assertEqual(first["permission"], "external_communication")
        self.assertEqual(apps.calls, [])                        # nothing sent while waiting
        approval = first["approval"]["id"]
        # an approval cannot be stretched to different words or recipients
        changed = self.run_tool("mail.send", {**message, "to": "boss@example.com"}, approval_id=approval)
        self.assertNotEqual(changed["status"], "succeeded")
        self.assertEqual(apps.calls, [])
        again = self.run_tool("mail.send", message, actor="jarvis-core")
        self.app.safety.approve(again["approval"]["id"])
        sent = self.run_tool("mail.send", message, approval_id=again["approval"]["id"], run_id=again["run_id"])
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(apps.calls[-1][3:], ["sam@example.com", "", "Quote", "Yes, go ahead.", "1"])
        # used once: the same approval does not send a second copy
        repeat = self.run_tool("mail.send", message, approval_id=again["approval"]["id"])
        self.assertFalse(repeat["ok"])
        self.assertEqual(len(apps.calls), 1)

    def test_send_needs_a_recipient_and_words(self):
        self.fake(MAIL_COMPOSE="sent")
        tool = self.app.tools.get("mail.send")
        with self.assertRaises(Exception):
            tool.handler(self.app, {"to": "sam@example.com", "subject": "", "body": "  "}, "t")
        with self.assertRaises(Exception):
            tool.handler(self.app, {"to": "", "body": "hi"}, "t")


def iso(moment):
    return moment.isoformat(timespec="seconds")


class CalendarTests(MailCalendarCase):
    def test_today_includes_one_offs_repeats_and_all_day_events(self):
        today = datetime.combine(date.today(), datetime.min.time())
        weekly_start = today - timedelta(weeks=10) + timedelta(hours=9)
        rows = RS.join([
            record("Dentist", iso(today + timedelta(hours=15)), iso(today + timedelta(hours=15, minutes=30)),
                   "Main St", "Home", "", 1),
            record("Standup", iso(weekly_start), iso(weekly_start + timedelta(minutes=15)), "", "Work",
                   "FREQ=WEEKLY;INTERVAL=1", 4),
            record("Cancelled weekly", iso(weekly_start), iso(weekly_start + timedelta(hours=1)), "", "Work",
                   "FREQ=WEEKLY", 5),
            record("Holiday", iso(today), iso(today + timedelta(hours=23, minutes=59, seconds=59)), "", "Holidays", "", 2),
            record("Yesterday", iso(today - timedelta(hours=5)), iso(today - timedelta(hours=4)), "", "Home", "", 3),
        ])
        apps = self.fake(CAL_EVENTS=rows, CAL_EXCLUDED=RS.join(["", iso(today + timedelta(hours=9))]))
        out = self.ok("calendar.today")
        self.assertEqual([e["title"] for e in out["events"]], ["Holiday", "Standup", "Dentist"])
        holiday, standup, dentist = out["events"]
        self.assertTrue(holiday["all_day"])
        self.assertTrue(holiday["when"].endswith("all day"))
        self.assertTrue(standup["repeats"])
        self.assertTrue(standup["when"].endswith("9:00 am to 9:15 am"))
        self.assertEqual(dentist["location"], "Main St")
        self.assertEqual(apps.calls[1][3:], ["Work", "4", "Work", "5"])
        # dates go to AppleScript as plain numbers: year|month|day|seconds
        self.assertEqual(apps.calls[0][3], f"{today.year}|{today.month}|{today.day}|0")

    def test_one_read_serves_today_and_the_week(self):
        apps = self.fake(CAL_EVENTS="")
        self.ok("calendar.today")
        self.ok("calendar.upcoming", {"days": 7})
        self.assertEqual(apps.scripts(), ["CAL_EVENTS"])
        self.ok("calendar.upcoming", {"days": 30})              # beyond the first read: read again
        self.assertEqual(apps.scripts(), ["CAL_EVENTS", "CAL_EVENTS"])

    def test_add_event_defaults_to_an_hour_and_clears_the_cache(self):
        start = (datetime.now() + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
        apps = self.fake(CAL_ADD=f"UID-1{FS}Home", CAL_EVENTS="")
        self.ok("calendar.today")
        out = self.ok("calendar.add_event", {"title": "Call Sam", "start": start.strftime("%Y-%m-%d %H:%M"),
                                             "location": "Phone"})
        self.assertEqual((out["calendar"], out["end"]), ("Home", (start + timedelta(hours=1)).isoformat(timespec="minutes")))
        self.assertTrue(out["when"].endswith("2:00 pm to 3:00 pm"))
        args = apps.calls[1]
        self.assertEqual(args[3:], ["Call Sam", f"{start.year}|{start.month}|{start.day}|{14 * 3600}",
                                    f"{start.year}|{start.month}|{start.day}|{15 * 3600}", "", "Phone", "", ""])
        self.ok("calendar.today")
        self.assertEqual(apps.scripts(), ["CAL_EVENTS", "CAL_ADD", "CAL_EVENTS"])
        self.assertEqual(self.app.tools.get("calendar.add_event").category.value, "write")

    def test_add_all_day_event_to_a_named_calendar(self):
        day = date.today() + timedelta(days=3)
        apps = self.fake(CAL_NAMES="Home\nWork", CAL_ADD=f"UID-2{FS}Work")
        out = self.ok("calendar.add_event", {"title": "Conference", "start": day.isoformat(), "calendar": "work"})
        self.assertIn("all day", out["when"])
        self.assertEqual(apps.calls[1][6], "1")
        self.assertEqual(apps.calls[1][9], "Work")

    def test_add_event_refuses_unknown_calendars_and_the_past(self):
        self.fake(CAL_NAMES="Home\nWork")
        later = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        unknown = self.run_tool("calendar.add_event", {"title": "X", "start": later, "calendar": "Gym"})
        self.assertIn("yours are: Home, Work", unknown["error"])
        past = self.run_tool("calendar.add_event", {"title": "X", "start": "2020-01-01T10:00"})
        self.assertIn("in the past", past["error"])
        bad = self.run_tool("calendar.add_event", {"title": "X", "start": "tomorrow at 3"})
        self.assertIn("2026-11-17T14:00", bad["error"])


class RepeatTests(unittest.TestCase):
    def between(self, start, rule, a, b):
        return [d for d in mc.occurrences(start, rule, a, b) if d >= a]

    def test_weekly_on_chosen_days(self):
        got = self.between(datetime(2025, 1, 6, 9), "FREQ=WEEKLY;BYDAY=MO,WE", datetime(2026, 11, 16), datetime(2026, 11, 23))
        self.assertEqual(got, [datetime(2026, 11, 16, 9), datetime(2026, 11, 18, 9)])

    def test_fortnightly(self):
        got = self.between(datetime(2026, 11, 2, 9), "FREQ=WEEKLY;INTERVAL=2", datetime(2026, 11, 1), datetime(2026, 12, 1))
        self.assertEqual(got, [datetime(2026, 11, 2, 9), datetime(2026, 11, 16, 9), datetime(2026, 11, 30, 9)])

    def test_monthly_last_friday_and_day_of_month(self):
        got = self.between(datetime(2020, 3, 27, 10), "FREQ=MONTHLY;BYDAY=-1FR", datetime(2026, 11, 1), datetime(2027, 1, 1))
        self.assertEqual(got, [datetime(2026, 11, 27, 10), datetime(2026, 12, 25, 10)])
        got = self.between(datetime(2026, 1, 31), "FREQ=MONTHLY", datetime(2026, 2, 1), datetime(2026, 4, 1))
        self.assertEqual(got, [datetime(2026, 3, 31)])           # February has no 31st

    def test_yearly_second_monday_of_june(self):
        rule = "FREQ=YEARLY;INTERVAL=1;COUNT=6;BYMONTH=6;BYDAY=2MO"
        self.assertEqual(self.between(datetime(2025, 6, 9), rule, datetime(2027, 1, 1), datetime(2028, 1, 1)),
                         [datetime(2027, 6, 14)])
        self.assertEqual(self.between(datetime(2025, 6, 9), rule, datetime(2031, 1, 1), datetime(2032, 1, 1)), [])

    def test_count_and_until_end_a_series(self):
        self.assertEqual(len(list(mc.occurrences(datetime(2026, 11, 1, 8), "FREQ=DAILY;COUNT=5",
                                                 datetime(2026, 11, 1), datetime(2026, 12, 1)))), 5)
        got = list(mc.occurrences(datetime(2026, 11, 1, 8), "FREQ=DAILY;UNTIL=20261103", datetime(2026, 11, 1),
                                  datetime(2026, 12, 1)))
        self.assertEqual(got[-1], datetime(2026, 11, 3, 8))

    def test_unknown_rule_gives_nothing(self):
        self.assertEqual(list(mc.occurrences(datetime(2026, 1, 1), "FREQ=SECONDLY", datetime(2026, 1, 1),
                                             datetime(2026, 1, 2))), [])


class ConversationKnowsTests(unittest.TestCase):
    def test_mail_and_calendar_requests_reach_the_planner(self):
        for text in ("Summarise my unread emails", "Check my inbox", "Draft a reply to Sam",
                     "What's on my calendar tomorrow?", "Add a meeting with Bo at 3pm", "Any appointments today?"):
            self.assertTrue(Conversation.OWN_DATA.search(text), text)
        for text in ("What events are on in Sydney this weekend?", "How do I send a parcel overseas?"):
            self.assertFalse(Conversation.OWN_DATA.search(text), text)

    def test_prompt_no_longer_denies_email_and_calendar(self):
        prompt = system_prompt([])
        self.assertNotIn("cannot send email", prompt)
        self.assertIn("approves every message", prompt)
        self.assertIn("Calendar", prompt)


if __name__ == "__main__":
    unittest.main()
