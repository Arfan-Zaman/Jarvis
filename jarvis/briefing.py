"""The spoken morning briefing: 30-60 seconds on what matters today.

It gathers, from what JARVIS already has:
- open tasks, and the ones due today or overdue (`app.tasks`);
- what it learned since yesterday (memories saved by the learner, source `jarvis:learn`);
- approvals waiting for the owner and self-review proposals;
- the Mac (`mac.status`): battery and free disk space;
- two or three headlines on the owner's interests (`open.news`; `claude.research` when JARVIS_BRAIN=claude).

The local model turns those facts into a short spoken script; if it is unavailable the
briefing is put together from plain sentences instead, so there is always one to play.

One briefing is kept per day. Headlines are slow (a web search), so they are fetched in the
background when the server starts and the briefing waits only briefly for them; a briefing
built without them is not kept, so the next request picks the headlines up.
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timedelta, timezone

from .learner import ACTOR as LEARN_ACTOR
from .logging_setup import get_logger
from .providers.base import ChatMessage, ProviderError
from .tools.mac import describe_status

log = get_logger("briefing")

ACTOR = "jarvis:briefing"
BRIEFING_KEY = "briefing.today"
HEADLINES_KEY = "briefing.headlines"
URL = re.compile(r"\(source: (https?://[^)\s]+)\)")
DEFAULT_TOPICS = "the Australian used-car market; car detailing and paint protection; AI assistants"

SPEAK = (
    "You are JARVIS, the owner's personal assistant, giving their spoken morning briefing. "
    "Write what you will say out loud: 30 to 60 seconds, about 80 to 140 words, warm, plain and "
    "natural, like a capable assistant talking, never a list. No headings, bullets, markdown, "
    "URLs or emoji. Say numbers the way people say them. Open with a short good-morning, cover "
    "only the facts given (skip anything empty), most useful first, and end with one short line. "
    "Never invent anything that is not in the facts."
)


def enabled() -> bool:
    return os.environ.get("JARVIS_BRIEFING", "1").strip().lower() not in ("0", "off", "false", "no")


def topics() -> str:
    return os.environ.get("JARVIS_BRIEFING_TOPICS", "").strip() or DEFAULT_TOPICS


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _clip(text: str, limit: int = 160) -> str:
    text = URL.sub("", str(text)).strip()
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


class Briefing:
    def __init__(self, app, now=None, news_wait: float | None = None):
        self.app = app
        self.now = now or (lambda: datetime.now().astimezone())     # the owner's local time
        self.news_wait = float(os.environ.get("JARVIS_BRIEFING_NEWS_WAIT", "20")) if news_wait is None else news_wait
        self._build = threading.Lock()
        self._news = threading.Lock()
        self._news_done = threading.Event()
        self._news_done.set()
        self._thread = None
        self._stop = threading.Event()

    def today(self) -> str:
        return self.now().date().isoformat()

    # --- the day's briefing -------------------------------------------------
    def get(self, refresh: bool = False) -> dict:
        """Today's briefing: the kept one, or a new one."""
        with self._build:
            kept = self.app.settings.get(BRIEFING_KEY)
            if not refresh and kept and kept.get("day") == self.today():
                return {**kept, "cached": True}
            briefing = self.build(wait=self.news_wait)
            if not briefing["partial"]:
                self.app.settings.set(BRIEFING_KEY, briefing, category="briefing", source="jarvis")
            return {**briefing, "cached": False}

    def build(self, wait: float = 0) -> dict:
        facts = self.gather(wait)
        text, by = self.speak(facts)
        news = facts["headlines"]
        return {
            "day": self.today(), "made_at": self.now().isoformat(timespec="seconds"), "text": text, "by": by,
            "sections": facts["sections"], "sources": facts["sources"],
            "partial": news is None,           # the headlines were still on their way
        }

    # --- gathering ----------------------------------------------------------
    def gather(self, wait: float = 0) -> dict:
        sections, sources = {}, []
        for name, part in (("tasks", self.tasks), ("learned", self.learned), ("waiting", self.waiting),
                           ("mac", self.mac)):
            try:
                sections[name] = part()
            except Exception as exc:  # noqa: BLE001 - one broken part never stops the briefing
                log.warning("Briefing: %s unavailable: %s", name, exc)
                sections[name] = None
        for item in (sections.get("learned") or {}).get("items", []):
            if item.get("url"):
                sources.append({"title": item["text"], "url": item["url"], "kind": "learned"})
        headlines = self.headlines(wait)
        sections["headlines"] = headlines
        for item in headlines or []:
            sources.append({"title": item["fact"], "url": item["url"], "kind": "headline"})
        return {"sections": sections, "sources": sources, "headlines": headlines}

    def tasks(self) -> dict:
        open_ = self.app.tasks.list(status="in_progress", limit=50) + self.app.tasks.list(status="pending", limit=200)
        today = self.today()
        due, overdue = [], []
        for task in open_:
            moment = _parse(task.get("due_at"))
            if not moment:
                continue
            day = moment.astimezone(self.now().tzinfo).date().isoformat()
            if day == today:
                due.append(task["title"])
            elif day < today:
                overdue.append(task["title"])
        top = [t["title"] for t in open_ if t["priority"] in ("urgent", "high")][:3]
        return {"open": len(open_), "due_today": due[:5], "overdue": overdue[:5], "top": top}

    def learned(self) -> dict:
        since = (self.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        items = []
        for memory in self.app.memory.list(source=LEARN_ACTOR, limit=50):
            moment = _parse(memory.get("created_at"))
            if moment and moment >= since:
                found = URL.search(memory["content"])
                items.append({"text": _clip(memory["content"], 300), "url": found.group(1) if found else None})
        return {"count": len(items), "items": items[:3]}

    def waiting(self) -> dict:
        approvals = [a["summary"] for a in self.app.safety.list_approvals(status="pending", limit=20)]
        try:
            proposals = [p["branch"] for p in self.app.selfreview.proposals()]
        except Exception:  # noqa: BLE001 - not a git checkout
            proposals = []
        return {"approvals": approvals[:5], "approval_count": len(approvals), "proposals": proposals[:5]}

    def mac(self) -> dict | None:
        result = self.app.tools.execute("mac.status", {}, actor=ACTOR)
        if not result["ok"]:
            return None
        data = result["output"] or {}
        return {"battery": data.get("battery"), "disk_free": data.get("disk_free"),
                "disk_total": data.get("disk_total"), "said": describe_status(data)}

    # --- headlines (slow: a web search) -------------------------------------
    def headlines(self, wait: float = 0) -> list | None:
        """Today's headlines; [] if research failed, None if still being fetched."""
        kept = self.app.settings.get(HEADLINES_KEY) or {}
        if kept.get("day") == self.today():
            return kept.get("items") or []
        self.fetch_headlines(background=True)
        self._news_done.wait(max(0.0, wait))
        kept = self.app.settings.get(HEADLINES_KEY) or {}
        return (kept.get("items") or []) if kept.get("day") == self.today() else None

    def fetch_headlines(self, background: bool = False) -> None:
        if not self._news.acquire(blocking=False):     # already being fetched
            return
        self._news_done.clear()

        def work():
            try:
                day = self.today()
                if os.environ.get("JARVIS_BRAIN", "local") == "claude" and "claude.research" in self.app.tools.names():
                    result = self.app.tools.execute("claude.research", {
                        "query": f"The most important news from the last two days ({day}) about: {topics()}",
                        "why": "Two or three headlines for the owner's spoken morning briefing.",
                        "count": 3}, actor=ACTOR)
                    items = (result["output"] or {}).get("facts", [])[:3] if result["ok"] else []
                else:                                   # free and local: Google News headlines, no Claude
                    result = self.app.tools.execute("open.news", {"topic": topics(), "limit": 3}, actor=ACTOR)
                    items = [{"fact": h["title"], "url": h["url"]} for h in
                             (result["output"] or {}).get("headlines", [])[:3]] if result["ok"] else []
                if not result["ok"]:
                    log.info("Briefing headlines unavailable: %s", result.get("error"))
                self.app.settings.set(HEADLINES_KEY, {"day": day, "items": items}, category="briefing",
                                      source="jarvis")
            except Exception as exc:  # noqa: BLE001
                log.warning("Briefing headlines failed: %s", exc)
            finally:
                self._news.release()
                self._news_done.set()

        if background:
            threading.Thread(target=work, name="jarvis-briefing-news", daemon=True).start()
        else:
            work()

    # --- speaking -----------------------------------------------------------
    def plain(self, facts: dict) -> str:
        """The briefing from plain sentences, when the model is unavailable."""
        s = facts["sections"]
        hour = self.now().hour
        lines = ["Good morning." if hour < 12 else "Good afternoon." if hour < 18 else "Good evening."]
        tasks = s.get("tasks")
        if tasks:
            if tasks["due_today"]:
                lines.append(f"Due today: {', '.join(tasks['due_today'][:3])}.")
            if tasks["overdue"]:
                lines.append(f"Overdue: {', '.join(tasks['overdue'][:3])}.")
            if tasks["open"]:
                lines.append(f"You have {_plural(tasks['open'], 'open task')}"
                             + (f", top of the list is {tasks['top'][0]}." if tasks["top"] else "."))
            else:
                lines.append("Your task list is clear.")
        waiting = s.get("waiting")
        if waiting and (waiting["approval_count"] or waiting["proposals"]):
            parts = []
            if waiting["approval_count"]:
                parts.append(_plural(waiting["approval_count"], "approval"))
            if waiting["proposals"]:
                parts.append(_plural(len(waiting["proposals"]), "self-review proposal"))
            lines.append(f"Waiting for you: {' and '.join(parts)}.")
        learned = s.get("learned")
        if learned and learned["items"]:
            lines.append(f"Overnight I learned: {_clip(learned['items'][0]['text'])}")
        for n, item in enumerate((facts.get("headlines") or [])[:2]):
            lines.append(f"{'In the news' if n == 0 else 'Also'}: {_clip(item['fact'])}")
        mac = s.get("mac")
        if mac and mac.get("disk_free"):
            battery = str(mac.get("battery") or "").split(";")[0].strip()
            lines.append(f"The Mac is fine: {mac['disk_free']} free" + (f", battery {battery}." if battery else "."))
        lines.append("That's your briefing.")
        return " ".join(line if line.endswith((".", "!", "?", "…")) else line + "." for line in lines)

    def speak(self, facts: dict) -> tuple[str, str]:
        s = facts["sections"]
        notes = [f"Local time: {self.now().strftime('%A %d %B, %I:%M %p')}"]
        if s.get("tasks"):
            notes.append(f"Tasks: {s['tasks']}")
        if s.get("waiting"):
            notes.append(f"Waiting for the owner: {s['waiting']}")
        if s.get("learned"):
            notes.append("Learned overnight: " + "; ".join(i["text"] for i in s["learned"]["items"]))
        if facts.get("headlines"):
            notes.append("Headlines: " + "; ".join(_clip(i["fact"], 300) for i in facts["headlines"]))
        if s.get("mac"):
            notes.append(f"Mac: {s['mac']['said']}")
        try:
            reply = self.app.provider.generate([ChatMessage("system", SPEAK),
                                                ChatMessage("user", "\n".join(notes))]).text.strip()
        except ProviderError as exc:
            log.info("Briefing from plain sentences (model unavailable: %s)", exc)
            reply = ""
        reply = re.sub(r"https?://\S+", "", reply)
        reply = re.sub(r"[*#`_]+|^\s*[-•]\s*", "", reply, flags=re.M)
        reply = " ".join(reply.split())
        words = len(reply.split())
        if 25 <= words <= 190:
            return reply, "model"
        return self.plain(facts), "plain"

    # --- background ---------------------------------------------------------
    def start(self) -> "Briefing":
        """Fetch the day's headlines ahead of time, so the first wake of the day is quick."""
        if not enabled() or self._thread:
            return self
        self._thread = threading.Thread(target=self._run, name="jarvis-briefing", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        if self._stop.wait(20):
            return
        while not self._stop.is_set():
            kept = self.app.settings.get(HEADLINES_KEY) or {}
            if kept.get("day") != self.today() and self.now().hour >= 4:
                self.fetch_headlines()
            self._stop.wait(1800)

    def status(self) -> dict:
        kept = self.app.settings.get(BRIEFING_KEY) or {}
        return {"enabled": enabled(), "today": self.today(), "ready": kept.get("day") == self.today(),
                "fetching_headlines": self._news.locked()}
