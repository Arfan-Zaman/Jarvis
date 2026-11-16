"""Email and calendar through the owner's own Mail and Calendar apps (no installs, no accounts).

- mail.recent, mail.search, mail.read: read the owner's mail in Mail.app (automatic).
- mail.draft: opens a ready-to-send message in Mail for the owner to check. It never sends.
- mail.send: sends a message. External communication: the safety layer asks the owner every
  time, for exactly these recipients and words, and the approval works once.
- calendar.today, calendar.upcoming: events from Calendar.app, repeating events included.
- calendar.add_event: adds an event to one of the owner's calendars.

AppleScript runs through `osascript` with every value passed as an argument (`item n of argv`),
never spliced into the script, so text from an email cannot become code. Mail content is read
on this Mac only; it leaves it only when the owner asks JARVIS to summarise something.
The first time, macOS asks the owner to allow JARVIS to control Mail and Calendar.
"""

from __future__ import annotations

import calendar as cal
import re
import subprocess
import time
from datetime import date, datetime, timedelta, timezone

from ..common import JarvisError, ValidationError
from ..safety import ActionCategory
from .registry import Tool, ToolRegistry

READ, WRITE, SEND = ActionCategory.READ, ActionCategory.WRITE, ActionCategory.EXTERNAL_COMMUNICATION
FS, RS = "\x1f", "\x1e"                      # field and record separators in script output
EMAIL = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")
SKIP_MAILBOXES = {"trash", "junk", "spam", "deleted messages", "deleted items", "bin", "junk e-mail"}

# --- shared AppleScript (fixed text only; values arrive through argv) -------------
HELPERS = r'''
on pad(n)
    return text -2 thru -1 of ("0" & (n as integer))
end pad
on iso(d)
    set s to time of d
    return ((year of d) as text) & "-" & my pad(month of d as integer) & "-" & my pad(day of d) & "T" & ¬
        my pad(s div 3600) & ":" & my pad((s mod 3600) div 60) & ":" & my pad(s mod 60)
end iso
on mkdate(s)
    set AppleScript's text item delimiters to "|"
    set p to text items of s
    set AppleScript's text item delimiters to ""
    set d to current date
    set day of d to 1
    set year of d to (item 1 of p) as integer
    set month of d to (item 2 of p) as integer
    set day of d to (item 3 of p) as integer
    set time of d to (item 4 of p) as integer
    return d
end mkdate
on txt(v)
    if v is missing value then return ""
    return v as text
end txt
on joined(lst, sep)
    set AppleScript's text item delimiters to sep
    set t to lst as text
    set AppleScript's text item delimiters to ""
    return t
end joined
'''

# Lists inbox messages received in the last N days: id, sender, subject, date, read.
MAIL_LIST = HELPERS + r'''
on run argv
    set cutoff to (current date) - ((item 1 of argv) as integer) * days
    set FS to character id 31
    set out to {}
    tell application "Mail"
        if (item 2 of argv) is "1" then
            set spec to a reference to (every message of inbox whose date received > cutoff and read status is false)
        else
            set spec to a reference to (every message of inbox whose date received > cutoff)
        end if
        set {ids, froms, subjs, whens, reads} to {id, sender, subject, date received, read status} of spec
    end tell
    repeat with i from 1 to count of ids
        set end of out to ((item i of ids) as text) & FS & my txt(item i of froms) & FS & my txt(item i of subjs) & ¬
            FS & my iso(item i of whens) & FS & ((item i of reads) as text) & FS & "" & FS & ""
    end repeat
    return my joined(out, character id 30)
end run
'''

# Messages whose subject or sender contains the query: in the inbox, or every mailbox.
MAIL_SEARCH = HELPERS + r'''
on run argv
    set q to item 1 of argv
    set cutoff to (current date) - ((item 2 of argv) as integer) * days
    set everywhere to (item 3 of argv) is "1"
    set skip to paragraphs of (item 4 of argv)
    set FS to character id 31
    set out to {}
    tell application "Mail"
        if everywhere then
            set boxes to {}
            repeat with a in accounts
                repeat with mb in mailboxes of a
                    if skip does not contain (name of mb) then set end of boxes to {name of a, name of mb, mb}
                end repeat
            end repeat
        else
            set boxes to {{"", "", inbox}}
        end if
        repeat with b in boxes
            try
                set spec to a reference to (every message of (item 3 of b) whose date received > cutoff and ¬
                    (subject contains q or sender contains q))
                set {ids, froms, subjs, whens, reads} to {id, sender, subject, date received, read status} of spec
                repeat with i from 1 to count of ids
                    set end of out to ((item i of ids) as text) & FS & my txt(item i of froms) & FS & ¬
                        my txt(item i of subjs) & FS & my iso(item i of whens) & FS & ((item i of reads) as text) & ¬
                        FS & (item 1 of b) & FS & (item 2 of b)
                end repeat
            end try
        end repeat
    end tell
    return my joined(out, character id 30)
end run
'''

# Full details of messages given as account|mailbox|id ("" account and mailbox = the inbox).
MAIL_BODIES = HELPERS + r'''
on run argv
    set n to (item 1 of argv) as integer
    set FS to character id 31
    set out to {}
    tell application "Mail"
        repeat with i from 2 to count of argv
            set AppleScript's text item delimiters to "|"
            set p to text items of (item i of argv)
            set AppleScript's text item delimiters to ""
            set mid to (item -1 of p) as integer
            try
                if (item 1 of p) is "" then
                    set m to first message of inbox whose id is mid
                else
                    set mb to first mailbox of account (item 1 of p) whose name is (item 2 of p)
                    set m to first message of mb whose id is mid
                end if
                set b to my txt(content of m)
                if n > 0 and (length of b) > n then set b to text 1 thru n of b
                set acct to ""
                set box to ""
                try
                    set box to name of mailbox of m
                    set acct to name of account of mailbox of m
                end try
                set tos to ""
                try
                    set tos to my joined(address of to recipients of m, ", ")
                end try
                set end of out to (mid as text) & FS & my txt(sender of m) & FS & my txt(subject of m) & FS & ¬
                    my iso(date received of m) & FS & ((read status of m) as text) & FS & acct & FS & box & FS & tos & FS & b
            end try
        end repeat
    end tell
    return my joined(out, character id 30)
end run
'''

# argv: to (lines), cc (lines), subject, body, send ("1" sends, "" opens it for the owner)
MAIL_COMPOSE = HELPERS + r'''
on run argv
    set tos to paragraphs of (item 1 of argv)
    set ccs to paragraphs of (item 2 of argv)
    set sending to (item 5 of argv) is "1"
    tell application "Mail"
        set msg to make new outgoing message with properties {subject:(item 3 of argv), content:(item 4 of argv), visible:(not sending)}
        tell msg
            repeat with a in tos
                if (a as text) is not "" then make new to recipient at end of to recipients with properties {address:(a as text)}
            end repeat
            repeat with a in ccs
                if (a as text) is not "" then make new cc recipient at end of cc recipients with properties {address:(a as text)}
            end repeat
        end tell
        if sending then
            send msg
            return "sent"
        end if
        activate
        return "drafted"
    end tell
end run
'''

# Events overlapping [start, end) plus every repeating event that began before end. Calendar answers
# each Apple event slowly, so each calendar is read in one bulk request (its `whose` cannot test
# `recurrence` either); exceptions are asked for later, only for
# repeating events that land in the window.
CAL_EVENTS = HELPERS + r'''
on run argv
    set sd to my mkdate(item 1 of argv)
    set ed to my mkdate(item 2 of argv)
    set FS to character id 31
    set out to {}
    tell application "Calendar"
        repeat with c in calendars
            set cname to name of c
            try
                set {titles, starts, ends, places, recs} to ¬
                    {summary, start date, end date, location, recurrence} of every event of c
                repeat with i from 1 to count of titles
                    set r to my txt(item i of recs)
                    set s to item i of starts
                    if s < ed and (r is not "" or (item i of ends) > sd) then
                        set end of out to my txt(item i of titles) & FS & my iso(s) & FS & my iso(item i of ends) & FS & ¬
                            my txt(item i of places) & FS & cname & FS & r & FS & (i as text)
                    end if
                end repeat
            end try
        end repeat
    end tell
    return my joined(out, character id 30)
end run
'''

# argv: pairs of calendar name, event index -> the excluded dates of each such event
CAL_EXCLUDED = HELPERS + r'''
on run argv
    set FS to character id 31
    set out to {}
    tell application "Calendar"
        repeat with i from 1 to (count of argv) div 2
            set exd to {}
            try
                repeat with x in (excluded dates of event ((item (i * 2) of argv) as integer) of ¬
                    (first calendar whose name is (item (i * 2 - 1) of argv)))
                    set end of exd to my iso(x)
                end repeat
            end try
            set end of out to my joined(exd, ",")
        end repeat
    end tell
    return my joined(out, character id 30)
end run
'''

# argv: title, start, end, all day ("1"), location, notes, calendar name ("" = first writable)
CAL_ADD = HELPERS + r'''
on run argv
    tell application "Calendar"
        if (item 7 of argv) is "" then
            set c to first calendar whose writable is true
        else
            set c to first calendar whose name is (item 7 of argv)
        end if
        tell c
            set e to make new event with properties {summary:(item 1 of argv), start date:my mkdate(item 2 of argv), ¬
                end date:my mkdate(item 3 of argv), allday event:((item 4 of argv) is "1"), ¬
                location:(item 5 of argv), description:(item 6 of argv)}
        end tell
        return (uid of e) & (character id 31) & (name of c)
    end tell
end run
'''

CAL_NAMES = HELPERS + r'''
on run argv
    tell application "Calendar" to set names to name of calendars whose writable is true
    return my joined(names, linefeed)
end run
'''


def _osascript(app_name: str, script: str, *args, timeout: int = 60, retry: bool = True) -> str:
    try:
        done = subprocess.run(["osascript", "-e", script, *map(str, args)], capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise JarvisError("osascript is not available on this Mac") from None
    except subprocess.TimeoutExpired:
        raise JarvisError(f"{app_name} took too long to answer") from None
    if done.returncode:
        err = (done.stderr or "").strip()
        if "(-600)" in err and retry:              # the app was quitting or still starting: once more
            subprocess.run(["open", "-g", "-a", app_name], capture_output=True, timeout=15)
            time.sleep(2)
            return _osascript(app_name, script, *args, timeout=timeout, retry=False)
        if "-1743" in err or "Not authorized" in err or "not allowed" in err.lower():
            raise JarvisError(
                f"macOS hasn't let JARVIS use {app_name} yet. Open System Settings > Privacy & Security > "
                f"Automation and turn on {app_name} for the app running JARVIS, then ask again.")
        if "-1728" in err or "Can’t get" in err or "Can't get" in err:
            raise JarvisError(f"{app_name} couldn't find that ({err[-160:]})")
        raise JarvisError(f"{app_name} reported a problem: {err[-200:] or 'unknown error'}")
    return done.stdout.rstrip("\n")


def _records(out: str, fields: tuple[str, ...]) -> list[dict]:
    rows = []
    for chunk in out.split(RS):
        if chunk.strip():
            parts = chunk.split(FS, len(fields) - 1)
            rows.append(dict(zip(fields, parts + [""] * (len(fields) - len(parts)))))
    return rows


def _limit(inputs, key, default, top):
    return max(1, min(int(inputs.get(key, default)), top))


# --- mail ---------------------------------------------------------------------
MSG_FIELDS = ("id", "from", "subject", "date", "read", "account", "mailbox")
FULL_FIELDS = MSG_FIELDS + ("to", "body")


def _message(row: dict) -> dict:
    out = {"id": int(row["id"]) if row["id"].isdigit() else row["id"], "from": row["from"],
           "subject": row["subject"] or "(no subject)", "date": row["date"], "unread": row["read"] == "false"}
    for key in ("account", "mailbox", "to"):
        if row.get(key):
            out[key] = row[key]
    if "body" in row:
        out["body"] = re.sub(r"\n{3,}", "\n\n", row["body"]).strip()
    return out


def _key(row) -> str:
    return f"{row.get('account', '')}|{row.get('mailbox', '')}|{row['id']}"


def _with_bodies(rows: list[dict], chars: int) -> list[dict]:
    if not rows or chars <= 0:
        return [_message(r) for r in rows]
    full = {r["id"]: r for r in _records(_osascript("Mail", MAIL_BODIES, chars, *map(_key, rows), timeout=90),
                                         FULL_FIELDS)}
    return [_message({**r, **full.get(r["id"], {})}) for r in rows]


def mail_recent(app, inputs, actor):
    days, limit = _limit(inputs, "days", 3, 60), _limit(inputs, "limit", 10, 30)
    rows = _records(_osascript("Mail", MAIL_LIST, days, "1" if inputs.get("unread_only") else ""), MSG_FIELDS)
    rows.sort(key=lambda r: r["date"], reverse=True)
    messages = _with_bodies(rows[:limit], max(0, min(inputs.get("preview_chars", 500), 4000)))
    return {"days": days, "found": len(rows), "unread": sum(r["read"] == "false" for r in rows),
            "messages": messages}


def mail_search(app, inputs, actor):
    query = inputs["query"].strip()
    if not query:
        raise ValidationError("mail.search: 'query' is empty")
    days, limit = _limit(inputs, "days", 90, 3650), _limit(inputs, "limit", 10, 30)
    everywhere = inputs.get("where", "inbox") == "everywhere"
    out = _osascript("Mail", MAIL_SEARCH, query[:200], days, "1" if everywhere else "",
                     "\n".join(sorted(SKIP_MAILBOXES)), timeout=120)
    seen, rows = set(), []
    for row in sorted(_records(out, MSG_FIELDS), key=lambda r: r["date"], reverse=True):
        twin = (row["from"], row["subject"], row["date"])      # Gmail keeps one copy in Inbox and All Mail
        if twin not in seen:
            seen.add(twin)
            rows.append(row)
    messages = _with_bodies(rows[:limit], max(0, min(inputs.get("preview_chars", 300), 4000)))
    return {"query": query, "where": "everywhere" if everywhere else "inbox", "days": days,
            "found": len(rows), "messages": messages}


def mail_read(app, inputs, actor):
    ref = f"{inputs.get('account', '')}|{inputs.get('mailbox', '')}|{inputs['id']}"
    found = _records(_osascript("Mail", MAIL_BODIES, 20000, ref), FULL_FIELDS)
    if not found:
        raise JarvisError(f"Mail has no message {inputs['id']} there (it may have been moved or deleted)")
    return _message(found[0])


def _addresses(value: str, field: str, required: bool) -> list[str]:
    found = [re.sub(r"^.*<([^>]+)>$", r"\1", a.strip()).strip("<> ")
             for a in re.split(r"[,;\n]", value or "") if a.strip()]
    bad = [a for a in found if not EMAIL.match(a)]
    if bad:
        raise ValidationError(f"not an email address: {', '.join(bad)}")
    if required and not found:
        raise ValidationError(f"'{field}' needs at least one email address")
    if len(found) > 20:
        raise ValidationError("at most 20 recipients")
    return found


def _compose(inputs: dict, send: bool) -> dict:
    to = _addresses(inputs.get("to", ""), "to", required=send)
    cc = _addresses(inputs.get("cc", ""), "cc", required=False)
    subject, body = inputs.get("subject", "").strip()[:300], inputs.get("body", "")[:20000]
    if send and not (subject or body.strip()):
        raise ValidationError("mail.send: the message is empty")
    result = _osascript("Mail", MAIL_COMPOSE, "\n".join(to), "\n".join(cc), subject, body, "1" if send else "")
    return {"to": to, "cc": cc, "subject": subject, "status": result or ("sent" if send else "drafted")}


def mail_draft(app, inputs, actor):
    if inputs.get("reply_to_id") is not None:
        original = mail_read(app, {"id": inputs["reply_to_id"], "account": inputs.get("account", ""),
                                   "mailbox": inputs.get("mailbox", "")}, actor)
        subject = original["subject"]
        inputs = {**inputs, "to": inputs.get("to") or original["from"],
                  "subject": inputs.get("subject") or (subject if subject.lower().startswith("re:") else f"Re: {subject}"),
                  "body": inputs.get("body", "") + f"\n\nOn {original['date'].replace('T', ' ')[:16]}, "
                          f"{original['from']} wrote:\n" + "\n".join(f"> {line}" for line in
                                                                    original.get("body", "")[:6000].splitlines())}
    out = _compose(inputs, send=False)
    out["note"] = "The draft is open in Mail for the owner to check and send. Nothing was sent."
    return out


def mail_send(app, inputs, actor):
    return _compose(inputs, send=True)


# --- calendar ------------------------------------------------------------------
EVENT_FIELDS = ("title", "start", "end", "location", "calendar", "recurrence", "index")
CACHE_SECONDS = 120                 # Calendar is slow to read; follow-up questions reuse the last read
_cache: dict = {}
DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _as_arg(moment: datetime) -> str:
    return f"{moment.year}|{moment.month}|{moment.day}|{moment.hour * 3600 + moment.minute * 60 + moment.second}"


def _parse_until(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    if "T" in value:
        return datetime.strptime(value, "%Y%m%dT%H%M%S")
    return datetime.strptime(value, "%Y%m%d") + timedelta(days=1) - timedelta(seconds=1)


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> int | None:
    last = cal.monthrange(year, month)[1]
    if nth > 0:
        day = 1 + (weekday - date(year, month, 1).weekday()) % 7 + (nth - 1) * 7
    else:
        day = last - (date(year, month, last).weekday() - weekday) % 7 + (nth + 1) * 7
    return day if 1 <= day <= last else None


def _month_days(year: int, month: int, start: datetime, parts: dict) -> list[int]:
    last = cal.monthrange(year, month)[1]
    days = set()
    for item in filter(None, parts.get("BYDAY", "").split(",")):
        m = re.fullmatch(r"([+-]?\d{1,2})?([A-Z]{2})", item)
        if not m or m.group(2) not in DAYS:
            continue
        weekday = DAYS.index(m.group(2))
        if m.group(1):
            day = _nth_weekday(year, month, weekday, int(m.group(1)))
            if day:
                days.add(day)
        else:
            days.update(d for d in range(1, last + 1) if date(year, month, d).weekday() == weekday)
    for item in filter(None, parts.get("BYMONTHDAY", "").split(",")):
        n = int(item)
        day = n if n > 0 else last + 1 + n
        if 1 <= day <= last:
            days.add(day)
    if not parts.get("BYDAY") and not parts.get("BYMONTHDAY") and start.day <= last:
        days.add(start.day)
    return sorted(days)


def occurrences(start: datetime, rule: str, window_start: datetime, window_end: datetime):
    """Start times of a repeating event (RFC 5545 RRULE, the forms Calendar writes) before window_end."""
    parts = dict(p.split("=", 1) for p in rule.upper().removeprefix("RRULE:").split(";") if "=" in p)
    freq, interval = parts.get("FREQ"), max(1, int(parts.get("INTERVAL", "1") or 1))
    count = int(parts["COUNT"]) if parts.get("COUNT", "").isdigit() else None
    until = _parse_until(parts.get("UNTIL"))
    stop = min(window_end, until) if until else window_end
    clock = timedelta(hours=start.hour, minutes=start.minute, seconds=start.second)
    seen, k = 0, 0
    if count is None and freq in ("DAILY", "WEEKLY"):              # jump close to the window
        span = interval * (1 if freq == "DAILY" else 7)
        k = max(0, (window_start - start).days // span - 1)
    for _ in range(20000):
        if freq == "DAILY":
            anchor = start.date() + timedelta(days=k * interval)
            days = [anchor]
        elif freq == "WEEKLY":
            anchor = start.date() - timedelta(days=start.weekday()) + timedelta(weeks=k * interval)
            picked = [DAYS.index(d) for d in parts.get("BYDAY", "").split(",") if d in DAYS] or [start.weekday()]
            days = [anchor + timedelta(days=d) for d in sorted(set(picked))]
        elif freq == "MONTHLY":
            months = start.month - 1 + k * interval
            year, month = start.year + months // 12, months % 12 + 1
            anchor = date(year, month, 1)
            days = [date(year, month, d) for d in _month_days(year, month, start, parts)]
        elif freq == "YEARLY":
            year = start.year + k * interval
            anchor = date(year, 1, 1)
            months = [int(m) for m in parts.get("BYMONTH", "").split(",") if m.isdigit()] or [start.month]
            days = []
            for month in months:
                if parts.get("BYDAY") or parts.get("BYMONTHDAY"):
                    days += [date(year, month, d) for d in _month_days(year, month, start, parts)]
                elif start.day <= cal.monthrange(year, month)[1]:
                    days.append(date(year, month, start.day))
        else:
            return
        if datetime.combine(anchor, datetime.min.time()) > stop:
            return
        for day in sorted(days):
            moment = datetime.combine(day, datetime.min.time()) + clock
            if moment < start:
                continue
            if moment > stop:
                return
            seen += 1
            if count is not None and seen > count:
                return
            yield moment
        k += 1


def _when(start: datetime, end: datetime, all_day: bool) -> str:
    day = f"{start:%a} {start.day} {start:%b}"
    if all_day:
        last = end - timedelta(seconds=1)
        return f"{day}, all day" if last.date() <= start.date() else f"{day} to {last:%a} {last.day} {last:%b}, all day"
    fmt = lambda t: f"{t.hour % 12 or 12}:{t:%M} {'am' if t.hour < 12 else 'pm'}"    # noqa: E731
    return f"{day}, {fmt(start)} to {fmt(end)}"


def _calendar_rows(window_start: datetime, window_end: datetime) -> list[dict]:
    """Calendar's events for a window: reused for a couple of minutes if a read already covered it."""
    hit = _cache.get("rows")
    if hit and time.monotonic() - hit["at"] < CACHE_SECONDS and hit["start"] <= window_start \
            and hit["end"] >= window_end:
        return hit["rows"]
    start = min(window_start, datetime.combine(date.today(), datetime.min.time()))   # one read serves
    end = max(window_end, start + timedelta(days=15))                                # today and the week
    out = _osascript("Calendar", CAL_EVENTS, _as_arg(start), _as_arg(end), timeout=180)
    rows = _records(out, EVENT_FIELDS)
    _cache["rows"] = {"at": time.monotonic(), "start": start, "end": end, "rows": rows}
    return rows


def _events(window_start: datetime, window_end: datetime) -> list[dict]:
    found = []                                   # (row, start, length)
    for row in _calendar_rows(window_start, window_end):
        try:
            start, end = datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"])
        except ValueError:
            continue
        starts = occurrences(start, row["recurrence"], window_start, window_end) if row["recurrence"] else [start]
        found += [(row, s, end - start) for s in starts if s < window_end and s + (end - start) > window_start]
    repeating = list({(r["calendar"], r["index"]): r for r, _, _ in found if r["recurrence"]})
    skipped = {}
    if repeating:                                # cancelled single occurrences of repeating events
        out = _osascript("Calendar", CAL_EXCLUDED, *[v for pair in repeating for v in pair], timeout=60)
        for pair, dates in zip(repeating, out.split(RS)):
            skipped[pair] = {d[:16] for d in dates.split(",") if d}
    events, seen = [], set()
    for row, s, length in found:
        spans = (length + timedelta(seconds=1)).total_seconds()    # Calendar ends all-day events at 23:59:59
        all_day = s.time() == datetime.min.time() and length >= timedelta(hours=23) and spans % 86400 in (0, 1)
        if s.isoformat()[:16] in skipped.get((row["calendar"], row["index"]), ()) or (row["title"], s) in seen:
            continue
        seen.add((row["title"], s))
        event = {"title": row["title"] or "(untitled)", "start": s.isoformat(timespec="minutes"),
                 "end": (s + length).isoformat(timespec="minutes"), "all_day": all_day,
                 "when": _when(s, s + length, all_day), "calendar": row["calendar"]}
        if row["location"]:
            event["location"] = row["location"]
        if row["recurrence"]:
            event["repeats"] = True
        events.append(event)
    events.sort(key=lambda e: (e["start"], not e["all_day"]))
    return events


def calendar_today(app, inputs, actor):
    today = datetime.combine(date.today(), datetime.min.time())
    events = _events(today, today + timedelta(days=1))
    now = datetime.now().isoformat(timespec="minutes")
    return {"date": f"{today:%A} {today.day} {today:%B %Y}", "events": events,
            "still_to_come": sum(e["end"] > now and not e["all_day"] for e in events)}


def calendar_upcoming(app, inputs, actor):
    days = _limit(inputs, "days", 7, 60)
    now = datetime.now().replace(second=0, microsecond=0)
    events = _events(now, datetime.combine(now.date() + timedelta(days=days), datetime.min.time()))
    return {"days": days, "events": events[:_limit(inputs, "limit", 50, 200)], "found": len(events)}


def _moment(value: str, field: str) -> tuple[datetime, bool]:
    value = value.strip().replace(" ", "T", 1) if value else ""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.fromisoformat(value), True
        return datetime.fromisoformat(value).replace(tzinfo=None, second=0, microsecond=0), False
    except ValueError:
        raise ValidationError(f"calendar.add_event: '{field}' must be a date and time like 2026-11-17T14:00") from None


def calendar_add_event(app, inputs, actor):
    title = inputs["title"].strip()[:200]
    if not title:
        raise ValidationError("calendar.add_event: 'title' is empty")
    start, date_only = _moment(inputs["start"], "start")
    all_day = bool(inputs.get("all_day")) or date_only
    if inputs.get("end"):
        end = _moment(inputs["end"], "end")[0]
        if all_day and end <= start + timedelta(hours=23):
            end = start + timedelta(days=1)
    else:
        end = start + (timedelta(days=1) if all_day else timedelta(minutes=inputs.get("duration_minutes", 60)))
    if all_day:
        start = start.replace(hour=0, minute=0)
    if end <= start:
        raise ValidationError("calendar.add_event: the event must end after it starts")
    if start < datetime.now() - timedelta(days=1):
        raise ValidationError("calendar.add_event: that time is in the past")
    name = inputs.get("calendar", "").strip()
    if name:
        names = [n.strip() for n in _osascript("Calendar", CAL_NAMES).splitlines() if n.strip()]
        if name not in names:
            match = [n for n in names if n.lower() == name.lower()]
            if not match:
                raise ValidationError(f"no calendar called {name}; yours are: {', '.join(names)}")
            name = match[0]
    uid, _, used = _osascript("Calendar", CAL_ADD, title, _as_arg(start), _as_arg(end), "1" if all_day else "",
                              inputs.get("location", "")[:200], inputs.get("notes", "")[:4000], name).partition(FS)
    _cache.clear()                               # the next read must include it
    return {"added": True, "title": title, "when": _when(start, end, all_day), "calendar": used or name,
            "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"), "uid": uid}


def register_mail_calendar(registry: ToolRegistry) -> None:
    S = lambda d, **x: {"type": "string", "description": d, **x}       # noqa: E731
    N = lambda d: {"type": "integer", "description": d}                 # noqa: E731
    B = lambda d: {"type": "boolean", "description": d}                 # noqa: E731
    message = {"to": S("Email addresses, separated by commas."), "cc": S("Copy to (email addresses)."),
               "subject": S("Subject line."), "body": S("The message text.")}
    for tool in (
        Tool("mail.recent", "Read the owner's recent email in Mail (sender, subject, time, start of each message), "
             "to list or summarise it.", READ, mail_recent,
             {"days": N("How many days back (default 3)."), "limit": N("Most messages (default 10, up to 30)."),
              "unread_only": B("Only unread messages."), "preview_chars": N("How much of each message to read.")}),
        Tool("mail.search", "Search the owner's email in Mail by sender or subject.", READ, mail_search,
             {"query": S("A name, address or words from the subject.", required=True),
              "where": S("inbox (default) or everywhere (all mailboxes).", enum=["inbox", "everywhere"]),
              "days": N("How many days back (default 90)."), "limit": N("Most messages (default 10)."),
              "preview_chars": N("How much of each message to read.")}),
        Tool("mail.read", "Read one whole email from Mail, by the id that mail.recent or mail.search gave.", READ,
             mail_read, {"id": {**N("The message id."), "required": True}, "account": S("Its account, as mail.search gave it."),
                         "mailbox": S("Its mailbox, as mail.search gave it.")}),
        Tool("mail.draft", "Write an email or a reply and open it in Mail for the owner to check. Never sends.",
             WRITE, mail_draft, {**message, "reply_to_id": N("Id of the email being answered (from mail.recent "
                                                             "or mail.search); fills in the recipient and subject."),
                                 "account": S("Account of that email."), "mailbox": S("Mailbox of that email.")}),
        Tool("mail.send", "Send an email from Mail. The owner approves every message before it goes.", SEND,
             mail_send, {**message, "to": S("Email addresses, separated by commas.", required=True)}),
        Tool("calendar.today", "The owner's calendar events for today (Calendar app).", READ, calendar_today),
        Tool("calendar.upcoming", "The owner's calendar events for the coming days (Calendar app).", READ,
             calendar_upcoming, {"days": N("How many days ahead (default 7, up to 60)."),
                                 "limit": N("Most events (default 50).")}),
        Tool("calendar.add_event", "Add an event to the owner's calendar.", WRITE, calendar_add_event,
             {"title": S("What it is.", required=True),
              "start": S("Local start, like 2026-11-17T14:00, or a date like 2026-11-17 for all day.", required=True),
              "end": S("Local end, like 2026-11-17T15:00."), "duration_minutes": N("Length if no end (default 60)."),
              "all_day": B("An all-day event."), "location": S("Where."), "notes": S("Notes."),
              "calendar": S("Which calendar (by name); default the first one that can be changed.")}),
    ):
        registry.register(tool)
