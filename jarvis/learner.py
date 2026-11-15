"""Continuous learning: JARVIS reads the web about what matters to the owner.

While the server runs, every `JARVIS_LEARN_MINUTES` (default 30) and only when
JARVIS is idle, it:

1. picks ONE search query from the owner's projects, stated interests and
   recent conversations (never repeating a recent one),
2. searches the web and reads the best pages (`web.search`, `web.fetch`),
3. keeps up to three durable, useful facts, each with the page it came from,
   saved as unverified memories in the "learned" category.

Everything goes through `ToolRegistry.execute`, so it is logged, checked by the
safety layer (web reads and memory writes run automatically) and visible in
the activity log. Turn it off with `JARVIS_LEARN=0`.
"""

from __future__ import annotations

import json
import os
import threading
import time

from .logging_setup import get_logger
from .providers.base import ChatMessage, ProviderError

log = get_logger("learner")
ACTOR = "jarvis:learn"
RECENT_KEY = "learn.recent_queries"
STATUS_KEY = "learn.last"

PICK = """You choose what JARVIS, the owner's personal AI, should read about next on the internet
so it becomes more useful to them. Below is what the owner works on and cares about, and what
JARVIS read recently. Pick ONE specific, current web search query (3 to 8 words) that would
teach JARVIS something new and practical for the owner. Do not repeat or rephrase a recent query.
Reply with ONE JSON object: {"query": "...", "why": "<one short sentence>"}"""

EXTRACT = """You are JARVIS's learning step. From the page text below, keep up to 3 facts that are
durable (still true next month), specific, and useful to the owner given why this was searched.
Use ONLY the page text; skip ads, navigation and opinions. Each fact is one plain sentence.
Reply with ONE JSON object: {"facts": ["...", "..."]}  (an empty list if nothing qualifies)"""


def enabled() -> bool:
    return os.environ.get("JARVIS_LEARN", "1") != "0"


def use_claude(app) -> bool:
    """Learn through Claude Code's web search when it is available (JARVIS_LEARN_SOURCE=web turns it off)."""
    if os.environ.get("JARVIS_LEARN_SOURCE", "claude") == "web" or "claude.research" not in app.tools.names():
        return False
    from .tools.claude import claude_binary
    return bool(claude_binary())


def interval_seconds() -> int:
    try:
        return max(5, int(os.environ.get("JARVIS_LEARN_MINUTES", "30"))) * 60
    except ValueError:
        return 1800


def _json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1]) if start >= 0 and end > start else {}


class Learner:
    def __init__(self, app):
        self.app = app
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # --- what to read about ------------------------------------------------
    def context(self) -> str:
        lines = []
        for project in self.app.projects.list()[:10]:
            lines.append(f"Project: {project['name']} - {project.get('description', '')[:160]}")
        for memory in self.app.memory.list(limit=200):
            if memory["category"] in ("preference", "personal", "general") and memory["source"] != ACTOR:
                lines.append(f"About the owner: {memory['content'][:160]}")
        recent = []
        for conversation in self.app.conversations.list(limit=8):
            for message in self.app.conversations.messages(conversation["id"], limit=6):
                if message["role"] == "user":
                    recent.append(message["content"][:140])
        lines += [f"Owner said: {text}" for text in recent[:15]]
        return "\n".join(lines[:60]) or "Nothing known yet: choose a broadly useful topic for a business owner."

    def recent(self) -> list[str]:
        value = self.app.settings.get(RECENT_KEY, [])
        return value if isinstance(value, list) else []

    def pick(self) -> dict:
        recent = self.recent()
        prompt = f"{self.context()}\n\nRecently read (do not repeat):\n" + "\n".join(f"- {q}" for q in recent[-25:])
        reply = self.app.provider.generate([ChatMessage("system", PICK), ChatMessage("user", prompt)],
                                           json_output=True).text
        choice = _json(reply)
        query = str(choice.get("query", "")).strip()[:120]
        if not query or query.lower() in (q.lower() for q in recent):
            raise ValueError(f"no new query chosen ({reply[:120]!r})")
        return {"query": query, "why": str(choice.get("why", ""))[:200]}

    # --- one learning pass -------------------------------------------------
    def once(self) -> dict:
        """Run one pass now and return what was learned. Never raises."""
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "A learning pass is already running."}
        started = time.monotonic()
        try:
            choice = self.pick()
            deep = self.research(choice) if use_claude(self.app) else None
            if deep is not None:                      # full-web research through Claude Code
                saved, read = deep
                found = {"ok": False}
            else:
                found = self.app.tools.execute("web.search", {"query": choice["query"], "limit": 5}, actor=ACTOR)
            results = ((found.get("output") or {}).get("results") or []) if found["ok"] else []
            if deep is None:
                saved, read = [], []
            for result in (results[:3] if deep is None else []):
                if len(read) >= 2:
                    break
                url = result.get("url") or result.get("link")
                if not url:
                    continue
                page = self.app.tools.execute("web.fetch", {"url": url, "max_chars": 6000,
                                                            "focus": choice["query"]}, actor=ACTOR)
                text = (page.get("output") or {}).get("text", "") if page["ok"] else ""
                if len(text) < 300:
                    continue
                read.append(url)
                reply = self.app.provider.generate([
                    ChatMessage("system", EXTRACT),
                    ChatMessage("user", f"Searched because: {choice['why']}\nQuery: {choice['query']}\n"
                                        f"Page: {url}\n\n{text[:6000]}")], json_output=True).text
                for fact in (_json(reply).get("facts") or [])[:3]:
                    if not isinstance(fact, str) or len(fact.strip()) < 15:
                        continue
                    result_ = self.app.tools.execute("memory.save", {
                        "content": f"{fact.strip()[:400]} (source: {url})", "category": "learned",
                        "verification_status": "unverified", "confidence": 0.6}, actor=ACTOR)
                    if result_["ok"] and not (result_["output"] or {}).get("duplicate"):
                        saved.append(result_["output"]["id"])
            recent = (self.recent() + [choice["query"]])[-50:]
            self.app.settings.set(RECENT_KEY, recent, category="learning", source="jarvis")
            outcome = {"ok": True, "query": choice["query"], "why": choice["why"], "read": read,
                       "saved": len(saved), "seconds": round(time.monotonic() - started)}
            self.app.events.record("learning", "learn.pass",
                                   f"Read about “{choice['query']}”: {len(saved)} new fact(s) from {len(read)} page(s)",
                                   actor=ACTOR, details=outcome)
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            outcome = {"ok": False, "error": str(exc)[:300]}
            log.info("Learning pass skipped: %s", exc)
        except Exception as exc:  # noqa: BLE001 - learning must never take JARVIS down
            log.exception("Learning pass crashed")
            outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            self._lock.release()
        outcome["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.app.settings.set(STATUS_KEY, outcome, category="learning", source="jarvis")
        return outcome

    def research(self, choice: dict):
        """Learn through Claude Code's web search. Returns (saved ids, pages) or None to fall back."""
        found = self.app.tools.execute("claude.research", {"query": choice["query"], "why": choice["why"],
                                                           "count": 3}, actor=ACTOR)
        if not found["ok"]:
            log.info("Claude research unavailable, using basic search: %s", found["error"])
            return None
        saved, read = [], []
        for item in (found["output"] or {}).get("facts", [])[:3]:
            result = self.app.tools.execute("memory.save", {
                "content": f"{item['fact']} (source: {item['url']})", "category": "learned",
                "verification_status": "unverified", "confidence": 0.65}, actor=ACTOR)
            if result["ok"] and not (result["output"] or {}).get("duplicate"):
                saved.append(result["output"]["id"])
            if item["url"] not in read:
                read.append(item["url"])
        return saved, read

    # --- background loop ---------------------------------------------------
    def idle(self) -> bool:
        status = self.app.provider.status()
        if not (status.configured and status.available):
            return False
        try:
            return self.app.engine.live().get("state") == "calm"
        except Exception:  # noqa: BLE001
            return False

    def start(self) -> "Learner":
        if not enabled() or self._thread:
            return self
        self._thread = threading.Thread(target=self._run, name="jarvis-learner", daemon=True)
        self._thread.start()
        log.info("Continuous learning on: a pass every %d minutes when idle", interval_seconds() // 60)
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        if self._stop.wait(90):          # let startup finish first
            return
        while not self._stop.is_set():
            if self.idle():
                self.once()
            self._stop.wait(interval_seconds())

    def status(self) -> dict:
        return {"enabled": enabled(), "interval_minutes": interval_seconds() // 60,
                "running": bool(self._thread and self._thread.is_alive()),
                "last": self.app.settings.get(STATUS_KEY), "recent": self.recent()[-10:]}
