"""Reminders and recurring jobs.

The owner says "remind me at 5pm to call the supplier", "remind me tomorrow
morning to send the invoice" or "every weekday at 8am check the used-car
prices", and it happens:

- a REMINDER shows a Mac notification (`mac.notify`), is spoken on the JARVIS
  page if it is open (GET /api/reminders/due) and is posted in the current
  conversation;
- a JOB runs its request the way a chat message is handled, as the actor
  `jarvis:schedule`, in its own "Scheduled: ..." conversation, and the result is
  posted in the current conversation. Anything that needs approval still waits
  for the owner: the safety layer treats this actor like any other.

Times are understood in the owner's local time zone. The background thread
checks every `JARVIS_SCHEDULE_TICK` seconds (default 20); `JARVIS_SCHEDULER=0`
turns it off. Everything goes through `ToolRegistry.execute`, so it is logged.
A schedule is moved on (or finished) *before* it fires, so a crash can never
make it fire twice.
"""

from __future__ import annotations

import os
import queue
import re
import threading
from datetime import date, datetime, time as dtime, timedelta, timezone

from .logging_setup import get_logger

log = get_logger("scheduler")
ACTOR = "jarvis:schedule"
LATE = timedelta(minutes=2)            # fired later than this: say it is late
STALE = timedelta(hours=12)            # missed by more than this (JARVIS was off): skip it

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december")
PARTS = {"morning": (9, 0), "afternoon": (14, 0), "evening": (18, 0), "night": (20, 0), "tonight": (20, 0)}
LATER = {"morning": (11, 0), "afternoon": (16, 0), "evening": (20, 0), "night": (21, 30), "tonight": (21, 30)}
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
           "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
           "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
           "couple of": 2, "a couple of": 2, "few": 3, "a few": 3}

_DAY = r"(mon|tues|wednes|thurs|fri|satur|sun)day"
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_NUM = r"(?P<n>\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|" \
       r"forty-five|forty|fifty|sixty|ninety|(?:a )?couple of|(?:a )?few)"
_FLAGS = re.I

RECUR = re.compile(
    r"\b(?:every|each)\s+(?P<what>day|morning|afternoon|evening|night|weekday|week\s?day|weekend|week|"
    + _DAY + r"(?:\s*(?:,|and|&)\s*" + _DAY + r")*)s?\b|\b(?P<daily>daily)\b|\bon\s+(?P<wkd>weekdays|weekends)\b", _FLAGS)
RELATIVE = re.compile(r"\b(?:in|after)\s+(?:(?P<half>half an?\s+hour)|" + _NUM +
                      r"\s*(?P<unit>minutes?|mins?|hours?|hrs?|days?|weeks?)(?P<andhalf>\s+and\s+a\s+half)?)\b", _FLAGS)
DAYWORD = re.compile(r"\b(?P<w>the day after tomorrow|day after tomorrow|today|tonight|tomorrow|tmrw)\b", _FLAGS)
WEEKDAY = re.compile(r"\b(?:on\s+|next\s+|this\s+|this\s+coming\s+)?" + _DAY + r"\b", _FLAGS)
DATE = re.compile(r"\b(?:on\s+)?(?:the\s+)?(?P<d1>\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+" + _MONTH.replace("(", "(?P<m1>", 1)
                  + r"\b|\b(?:on\s+)?" + _MONTH.replace("(", "(?P<m2>", 1) + r"\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?\b", _FLAGS)
PART = re.compile(r"\b(?:this\s+|in\s+the\s+)?(?P<p>morning|afternoon|evening|tonight|night)\b", _FLAGS)
TIME = re.compile(
    r"\b(?:at\s+|@\s*|by\s+|around\s+|from\s+)?(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)(?=\W|$)"
    r"|\b(?:at\s+|@\s*|by\s+|around\s+)(?P<h2>\d{1,2})(?:[:.](?P<m2>\d{2}))?(?:\s*o'?clock)?\b(?!\s*(?:minutes?|mins?|hours?|days?|%))"
    r"|\b(?P<h3>\d{1,2}):(?P<m3>\d{2})\b"
    r"|\b(?:at\s+)?(?P<word>noon|midday|midnight)\b", _FLAGS)
LEAD = re.compile(r"^\W*(?:(?:hey\s+|ok(?:ay)?\s+)?jarvis\W+)?(?:please\s+|can you\s+|could you\s+|would you\s+)*"
                  r"(?:set\s+(?:a|an|me\s+a)\s+(?:reminder|alarm)|remind\s+me|reminder|schedule(?:\s+(?:a|this))?|"
                  r"make\s+sure\s+(?:you|to))?\W*(?:(?:to|that|about|for|of|and)\s+)?", _FLAGS)
REMIND = re.compile(r"\b(remind\s+me|set\s+(?:a|an|me\s+a)\s+(?:reminder|alarm)|reminder\s+(?:to|for|at|in|on|tomorrow))\b", _FLAGS)
LIST = re.compile(r"\b(what|which|show|list|any|tell me|read)\b.{0,40}\b(reminders?|scheduled|schedules|jobs)\b"
                  r"|\bmy\s+(reminders|schedules?|scheduled jobs)\b\W*$", _FLAGS)
CANCEL = re.compile(r"\b(cancel|delete|remove|stop|clear|turn off|drop)\b.{0,60}\b(reminders?|scheduled|schedules?|jobs?)\b",
                    _FLAGS)


# --- the owner's clock --------------------------------------------------------
_ZONE = None


def local_zone():
    """The Mac's time zone, DST-aware where possible (TZ, else /etc/localtime)."""
    global _ZONE
    if _ZONE is None:
        try:
            from zoneinfo import ZoneInfo
            name = os.environ.get("TZ") or os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
            _ZONE = ZoneInfo(name)
        except Exception:  # noqa: BLE001 - fall back to today's fixed offset
            _ZONE = datetime.now().astimezone().tzinfo
    return _ZONE


def local_now() -> datetime:
    return datetime.now(local_zone())


def to_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def from_utc(value: str, zone) -> datetime:
    return datetime.fromisoformat(value).astimezone(zone)


# --- understanding "when" -------------------------------------------------------
def _day_index(name: str) -> int:
    return next(i for i, day in enumerate(DAYS) if day.startswith(name.lower()[:3]))


def _number(word: str) -> int:
    word = word.lower().strip()
    return int(word) if word.isdigit() else NUMBERS[word]


def _at(day: date, hour: int, minute: int, zone) -> datetime:
    return datetime.combine(day, dtime(hour, minute), tzinfo=zone)


def next_occurrence(recur: dict, after: datetime) -> datetime:
    """The first time strictly after `after` that matches {"days": [...], "time": "HH:MM"}."""
    hour, minute = (int(x) for x in recur["time"].split(":"))
    for offset in range(8):
        day = after.date() + timedelta(days=offset)
        if day.weekday() in recur["days"]:
            moment = _at(day, hour, minute, after.tzinfo)
            if moment > after:
                return moment
    raise ValueError("a repeating schedule needs at least one day")


def parse(text: str, now: datetime) -> dict | None:
    """Find a time in plain English. Returns {"at", "recur", "rest", "when"} or None.

    `at` is a local datetime (the first time it fires), `recur` is None or
    {"days": [...], "time": "HH:MM"}, `rest` is the text with the time words
    taken out (what to be reminded of), `when` the words that said when.
    """
    spans, found = [], {}

    def take(pattern, key):
        for match in pattern.finditer(text):
            if not any(s < match.end() and match.start() < e for s, e in spans):
                spans.append(match.span())
                found[key] = match
                return match
        return None

    take(RECUR, "recur")
    take(RELATIVE, "relative")
    take(DATE, "date")
    take(DAYWORD, "dayword")
    if "recur" not in found:
        take(WEEKDAY, "weekday")
    take(TIME, "time")
    take(PART, "part")
    if not found:
        return None

    zone = now.tzinfo
    when = " ".join(text[s:e].strip() for s, e in sorted(spans))
    rest = text
    for start, end in sorted(spans, reverse=True):
        rest = rest[:start] + " " + rest[end:]

    if "relative" in found and "recur" not in found:
        m = found["relative"]
        if m.group("half"):
            delta = timedelta(minutes=30)
        else:
            amount = _number(m.group("n"))
            unit = m.group("unit").lower()
            minutes = {"m": 1, "h": 60, "d": 1440, "w": 10080}[unit[0]] * amount
            if m.group("andhalf"):
                minutes += {"m": 0.5, "h": 30, "d": 720, "w": 5040}[unit[0]]
            delta = timedelta(minutes=minutes)
        at = (now.astimezone(timezone.utc) + delta).astimezone(zone).replace(second=0, microsecond=0)
        if at <= now:
            at += timedelta(minutes=1)
        return {"at": at, "recur": None, "rest": _clean(rest), "when": when}

    # the time of day
    hour = minute = later = None
    part = found["part"].group("p").lower() if "part" in found else None
    if "dayword" in found and found["dayword"].group("w").lower() == "tonight":
        part = part or "tonight"
    if "recur" in found and (found["recur"].group("what") or "").lower() in PARTS:
        part = part or found["recur"].group("what").lower()
    explicit_ampm = False
    if "time" in found:
        m = found["time"]
        if m.group("word"):
            hour, minute = (0, 0) if m.group("word").lower() == "midnight" else (12, 0)
            explicit_ampm = True
        else:
            hour = int(m.group("h") or m.group("h2") or m.group("h3"))
            minute = int(m.group("m") or m.group("m2") or m.group("m3") or 0)
            ap = (m.group("ap") or "").lower().replace(".", "")
            if ap:
                explicit_ampm = True
                hour = hour % 12 + (12 if ap == "pm" else 0)
            elif m.group("h3") and hour >= 13:
                explicit_ampm = True
            if hour > 23 or minute > 59:
                return None
        if not explicit_ampm and hour <= 12 and part in ("afternoon", "evening", "night", "tonight") and hour < 12:
            hour, explicit_ampm = hour + 12, True
        elif not explicit_ampm and part == "morning":
            explicit_ampm = True
    elif part:
        hour, minute = PARTS[part]
        explicit_ampm = True
        later = LATER.get(part)            # "this afternoon" at 2:30 pm: later this afternoon, not tomorrow

    if "recur" in found:
        m = found["recur"]
        what = (m.group("what") or "").lower().replace(" ", "")
        if m.group("daily") or what in ("day",) or what in PARTS:
            days = list(range(7))
        elif what == "weekday" or (m.group("wkd") or "").lower() == "weekdays":
            days = [0, 1, 2, 3, 4]
        elif what == "weekend" or (m.group("wkd") or "").lower() == "weekends":
            days = [5, 6]
        elif what == "week":
            days = [now.weekday()]
        else:
            days = sorted({_day_index(n) for n in re.findall(_DAY, m.group(0), _FLAGS)})
        if hour is None:
            hour, minute = 9, 0
        elif not explicit_ampm and 1 <= hour <= 6:
            hour += 12                              # "every day at 5": the afternoon
        recur = {"days": days, "time": f"{hour:02d}:{minute:02d}"}
        return {"at": next_occurrence(recur, now), "recur": recur, "rest": _clean(rest), "when": when}

    # the day
    day = None
    if "date" in found:
        m = found["date"]
        month = next(i for i, name in enumerate(MONTHS, 1) if name.startswith((m.group("m1") or m.group("m2")).lower()[:3]))
        try:
            day = date(now.year, month, int(m.group("d1") or m.group("d2")))
        except ValueError:
            return None
        if day < now.date():
            day = date(now.year + 1, month, day.day)
    elif "dayword" in found:
        word = found["dayword"].group("w").lower()
        day = now.date() + timedelta(days=2 if "after" in word else 1 if word in ("tomorrow", "tmrw") else 0)
    elif "weekday" in found:
        target = _day_index(found["weekday"].group(1))
        ahead = (target - now.weekday()) % 7
        if found["weekday"].group(0).lower().lstrip().startswith("next") and ahead == 0:
            ahead = 7
        day = now.date() + timedelta(days=ahead)

    if hour is None:
        if day is None:
            return None
        hour, minute = 9, 0
        explicit_ampm = True

    candidates = [(hour, minute)] + ([later] if later else [])
    if not explicit_ampm and day is not None and 1 <= hour <= 6:
        candidates = [(hour + 12, minute)]                   # "tomorrow at 5": the afternoon
    elif not explicit_ampm and hour < 12:
        candidates = [(hour, minute), (hour + 12, minute)]   # "at 5": whichever 5 o'clock comes next
    if day is not None:
        options = [_at(day, h, mi, zone) for h, mi in candidates]
        future = [o for o in options if o > now]
        at = future[0] if future else options[-1]
        if at <= now and "weekday" in found:
            at += timedelta(days=7)
        if at <= now:
            return None                              # a time already gone ("today at 7am" at 9am)
    else:
        at = None
        for offset in (0, 1):
            for h, mi in candidates:
                option = _at(now.date() + timedelta(days=offset), h, mi, zone)
                if option > now:
                    at = option
                    break
            if at:
                break
    return {"at": at, "recur": None, "rest": _clean(rest), "when": when}


def _clean(rest: str) -> str:
    rest = re.sub(r"\s+", " ", rest).strip()
    rest = LEAD.sub("", rest, count=1)
    rest = re.sub(r"^(?:to|that|about|for|of|and|then|,)\s+", "", rest, flags=_FLAGS)
    rest = re.sub(r"\s+(?:on|at|by|in|from)\W*$", "", rest, flags=_FLAGS)
    return rest.strip(" ,.;:!?-")


# --- saying "when" -----------------------------------------------------------------
def clock(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'am' if moment.hour < 12 else 'pm'}"


def day_words(moment: datetime, now: datetime) -> str:
    gap = (moment.date() - now.date()).days
    if gap == 0:
        return "today"
    if gap == 1:
        return "tomorrow"
    return f"{DAYS[moment.weekday()].title()} {moment.day} {MONTHS[moment.month - 1].title()}"


def describe_recur(recur: dict) -> str:
    days = sorted(recur["days"])
    hour, minute = (int(x) for x in recur["time"].split(":"))
    at = clock(datetime(2000, 1, 1, hour, minute))
    if days == list(range(7)):
        which = "every day"
    elif days == [0, 1, 2, 3, 4]:
        which = "every weekday"
    elif days == [5, 6]:
        which = "every weekend day"
    else:
        names = [DAYS[d].title() for d in days]
        which = "every " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1])
    return f"{which} at {at}"


def describe(item: dict, now: datetime) -> str:
    """'5:00 pm today', 'every weekday at 8:00 am (next: tomorrow 8:00 am)'."""
    if not item.get("next_at"):
        return "finished"
    at = from_utc(item["next_at"], now.tzinfo)
    single = f"{clock(at)} {day_words(at, now)}"
    return f"{describe_recur(item['recur'])} (next: {day_words(at, now)} {clock(at)})" if item.get("recur") else single


# --- the scheduler -------------------------------------------------------------------
def enabled() -> bool:
    return os.environ.get("JARVIS_SCHEDULER", "1") != "0"


def tick_seconds() -> int:
    try:
        return max(5, int(os.environ.get("JARVIS_SCHEDULE_TICK", "20")))
    except ValueError:
        return 20


class Scheduler:
    def __init__(self, app, clock=None, inline_jobs: bool = False):
        self.app = app
        self.clock = clock or local_now
        self.inline_jobs = inline_jobs          # tests run jobs straight away instead of on the worker
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._jobs: queue.Queue = queue.Queue()
        self._threads: list[threading.Thread] = []

    def now(self) -> datetime:
        return self.clock()

    # --- adding, listing, cancelling ------------------------------------------
    def add(self, kind: str, text: str, when: str, *, conversation_id: int | None = None,
            source: str = "user") -> dict:
        """Add a reminder or job. `when` is plain English ("at 5pm", "every weekday at 8am")."""
        from .common import ValidationError
        now = self.now()
        parsed = parse(when or "", now)
        if not parsed or parsed["at"] is None:
            raise ValidationError(f"I couldn't tell when {when!r} is. Try something like 'at 5pm', "
                                  "'tomorrow morning' or 'every weekday at 8am'.")
        what = (text or "").strip() or parsed["rest"]
        item = self.app.schedules.create(kind=kind, text=what, next_at=to_utc(parsed["at"]), recur=parsed["recur"],
                                         when_text=parsed["when"] or when, conversation_id=conversation_id,
                                         source=source)
        item["summary"] = self.confirmation(item)
        self.app.events.record("schedule", f"{kind}.add", f"{kind.title()} #{item['id']} set: {what[:80]} "
                               f"({describe(item, now)})", actor=source, details={"id": item["id"]})
        return item

    def confirmation(self, item: dict) -> str:
        now = self.now()
        at = from_utc(item["next_at"], now.tzinfo)
        when = f"{day_words(at, now)} at {clock(at)}"
        if item["kind"] == "reminder":
            if item["recur"]:
                return f"I'll remind you {describe_recur(item['recur'])} to {item['text']}. First one: {when}."
            return f"Reminder set for {when}: {item['text']}."
        if item["recur"]:
            return f"Scheduled: {describe_recur(item['recur'])} I'll {item['text']}. First run: {when}."
        return f"Scheduled for {when}: {item['text']}."

    def cancel(self, schedule_id: int, actor: str = "user") -> dict:
        item = self.app.schedules.get(schedule_id)
        if item["status"] != "active":
            return {**item, "summary": f"That one was already {item['status']}."}
        item = self.app.schedules.update(schedule_id, status="cancelled", next_at=None)
        self.app.events.record("schedule", f"{item['kind']}.cancel", f"Cancelled #{schedule_id}: {item['text'][:80]}",
                               actor=actor, details={"id": schedule_id})
        return {**item, "summary": f"Cancelled: {item['text']}."}

    def find(self, words: str) -> list[dict]:
        """Active schedules whose text shares the most words with `words` (best first)."""
        wanted = {w for w in re.findall(r"[a-z0-9']+", words.lower()) if len(w) > 2} - {
            "cancel", "delete", "remove", "stop", "the", "reminder", "reminders", "job", "jobs", "scheduled",
            "schedule", "about", "for", "and", "please", "jarvis", "turn", "off", "clear", "drop", "that", "one", "my"}
        scored = []
        for item in self.app.schedules.list():
            have = set(re.findall(r"[a-z0-9']+", item["text"].lower()))
            score = len(wanted & have)
            if score:
                scored.append((score, item))
        return [item for _, item in sorted(scored, key=lambda pair: -pair[0])]

    def listing(self) -> list[dict]:
        now = self.now()
        return [{**item, "when": describe(item, now)} for item in self.app.schedules.list()]

    def spoken_list(self) -> str:
        items = self.listing()
        if not items:
            return "You have no reminders or scheduled jobs."
        lines = [f"{i['id']}. {i['text']} — {i['when']}" + (" (job)" if i["kind"] == "job" else "") for i in items]
        return f"You have {len(items)}:\n" + "\n".join(lines)

    # --- firing ---------------------------------------------------------------
    def tick(self) -> list[int]:
        """Fire everything that is due now. Returns the ids fired."""
        if not self._lock.acquire(blocking=False):
            return []
        fired = []
        try:
            now = self.now()
            for item in self.app.schedules.due(to_utc(now)):
                try:
                    if self._fire(item, now):
                        fired.append(item["id"])
                except Exception:  # noqa: BLE001 - one broken schedule must not stop the others
                    log.exception("Schedule #%s failed to fire", item["id"])
        finally:
            self._lock.release()
        return fired

    def _fire(self, item: dict, now: datetime) -> bool:
        due = from_utc(item["next_at"], now.tzinfo)
        late = now - due
        # move it on first, so it can never fire twice
        nxt = to_utc(next_occurrence(item["recur"], now)) if item["recur"] else None
        changes = {"next_at": nxt, "status": "active" if nxt else "done"}
        if late > STALE:
            self.app.schedules.update(item["id"], **changes, last_result=f"Missed at {clock(due)} "
                                      f"{day_words(due, now)} (JARVIS was not running)")
            self.app.events.record("schedule", f"{item['kind']}.missed", f"Missed #{item['id']}: {item['text'][:80]}",
                                   level="warning", actor=ACTOR, details={"id": item["id"]})
            return False
        self.app.schedules.update(item["id"], **changes, fire_count=item["fire_count"] + 1,
                                  last_fired_at=to_utc(now))
        if item["kind"] == "reminder":
            self._remind(item, due if late > LATE else None)
        elif self.inline_jobs:
            self.run_job(item)
        else:
            self._jobs.put(item)
        return True

    def notify(self, title: str, message: str) -> None:
        self.app.tools.execute("mac.notify", {"title": title, "message": message}, actor=ACTOR)

    def current_conversation(self, item: dict) -> int:
        """The conversation the owner is in now (the most recent one), made if there is none."""
        latest = [c for c in self.app.conversations.list(limit=20) if c.get("source") != ACTOR]
        if latest:                             # not a "Scheduled: ..." conversation of a job
            return latest[0]["id"]
        if item.get("conversation_id"):
            return item["conversation_id"]
        return self.app.conversations.create({"title": "Reminders", "source": "jarvis:reminders"})["id"]

    def _post(self, item: dict, text: str, run_id: int | None = None) -> dict:
        return self.app.conversations.add_message(self.current_conversation(item), "assistant", text,
                                                  "jarvis", "scheduler", run_id=run_id)

    def _remind(self, item: dict, late_from: datetime | None) -> None:
        text = item["text"]
        note = f" (this was due at {clock(late_from)})" if late_from else ""
        self.notify("JARVIS reminder", text)
        self.app.schedules.add_alert(item["id"], f"Reminder: {text}.{note}", to_utc(self.now()))
        self._post(item, f"Reminder: {text}.{note}")
        self.app.events.record("schedule", "reminder.fired", f"Reminder #{item['id']}: {text[:80]}",
                               actor=ACTOR, details={"id": item["id"]})

    def run_job(self, item: dict) -> dict:
        """Run a job's request like a chat message, as `jarvis:schedule`. Never raises."""
        from .engine.conversation import Conversation
        text = item["text"]
        try:
            convo = item.get("job_conversation_id")
            try:
                if convo:
                    self.app.conversations.get(convo)
            except Exception:  # noqa: BLE001 - deleted: start a new one
                convo = None
            if not convo:
                convo = self.app.conversations.create({"title": f"Scheduled: {text}"[:200], "source": ACTOR})["id"]
                self.app.schedules.update(item["id"], job_conversation_id=convo)
            self.app.conversations.add_message(convo, "user", text)
            status = self.app.provider.status()
            if not (status.configured and status.available):
                raise RuntimeError(f"no AI model is connected ({status.detail})")
            reply = Conversation(self.app).respond(convo, text, actor=ACTOR)
            run = self.app.runs.get(reply["run_id"], with_steps=False) if reply.get("run_id") else None
            waiting = bool(run and run["status"] == "waiting_approval")
            result = reply["content"]
            headline = f"Needs your approval: {text}" if waiting else f"Done: {text}"
            self._post(item, f"Scheduled job “{text}”:\n\n{result}", run_id=reply.get("run_id"))
            outcome = {"ok": True, "waiting_approval": waiting, "reply": result}
        except Exception as exc:  # noqa: BLE001 - a failed job is reported, never fatal
            log.warning("Scheduled job #%s failed: %s", item["id"], exc)
            result, headline = f"It failed: {exc}", f"Scheduled job failed: {text}"
            self._post(item, f"Scheduled job “{text}” failed: {exc}")
            outcome = {"ok": False, "error": str(exc)[:300]}
        self.app.schedules.update(item["id"], last_result=result[:500])
        self.notify("JARVIS", headline)
        self.app.schedules.add_alert(item["id"], headline + ".", to_utc(self.now()))
        self.app.events.record("schedule", "job.ran", f"Job #{item['id']} ran: {text[:80]}",
                               level="info" if outcome["ok"] else "warning", actor=ACTOR,
                               details={"id": item["id"], **{k: v for k, v in outcome.items() if k != "reply"}})
        return outcome

    def due_alerts(self) -> list[dict]:
        """Alerts for the JARVIS page to speak, each handed out once (recent ones only)."""
        since = to_utc(self.now() - timedelta(minutes=30))
        return self.app.schedules.take_alerts(since)

    # --- background loop --------------------------------------------------------
    def start(self) -> "Scheduler":
        if not enabled() or self._threads:
            return self
        for target, name in ((self._run, "jarvis-scheduler"), (self._work, "jarvis-scheduled-jobs")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)
        log.info("Scheduler on: checking reminders every %d seconds", tick_seconds())
        return self

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(None)

    def _run(self) -> None:
        if self._stop.wait(3):
            return
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the scheduler must never take JARVIS down
                log.exception("Scheduler tick failed")
            self._stop.wait(tick_seconds())

    def _work(self) -> None:
        while not self._stop.is_set():
            item = self._jobs.get()
            if item is None:
                return
            self.run_job(item)

    def status(self) -> dict:
        return {"enabled": enabled(), "running": any(t.is_alive() for t in self._threads),
                "active": self.app.schedules.count("active"), "tick_seconds": tick_seconds()}
