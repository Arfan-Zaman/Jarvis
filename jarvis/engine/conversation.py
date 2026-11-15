"""Conversation: one chat that both talks and acts.

For every message JARVIS decides:

- ANSWER: talk, explain, calculate, advise. No tools, nothing changes.
- ACT:    the owner wants something done with JARVIS's own tools (add a task,
          look up their tasks...). The request is handed to the reasoning
          engine, which plans, acts, checks and reports.
- REMEMBER: the owner explicitly asks JARVIS to remember something. It is
          saved straight away as owner-provided.

Memory of the owner: every answer is given the most relevant things JARVIS
knows (see context.py), and says which it used. When the owner mentions a
lasting personal fact in passing, JARVIS offers to remember it and saves it
only if the next message says yes.

Honesty rule: what JARVIS says it *did* is written from the engine's record,
never from the model's imagination. Fixed wording describes changes, questions,
approvals and failures. The model is only asked to phrase an answer when
nothing was changed, and then only from the data the tools actually returned.

If a previous action is waiting for information, the owner's next message is
taken as the answer (unless they cancel it).
"""

from __future__ import annotations

import json
import os
import re

from ..common import JarvisError, now_local
from ..logging_setup import get_logger
from ..providers import ChatMessage, ProviderError
from . import persona
from .context import ContextBuilder
from .engine import parse_json

log = get_logger("conversation")

HISTORY = 10
CANCEL = re.compile(r"^\s*(cancel|never ?mind|forget it|stop|don'?t bother|no,? leave it)\b", re.I)
YES = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok|okay|please do|go ahead|do it|absolutely|definitely)\b"
                 r"[\w\s,.!']{0,40}$", re.I)
NO = re.compile(r"^\s*(no|nope|nah|don'?t|do not|not now|no thanks)\b[\w\s,.!']{0,40}$", re.I)
MEMORY_CATEGORIES = ("preference", "personal", "general")
# Saving straight away needs the owner's own words to ask for it. The model's
# opinion is not enough: without one of these, it can only OFFER to remember.
# Requests that need real skill: sent to Claude Code even if the small router says "answer".
HARD_WORK = re.compile(
    r"\b(write|build|create|make|generate|code|program|script|function|debug|fix|refactor|implement|"
    r"analy[sz]e|research|compare|evaluate|design|plan|strategy|essay|report|proposal|explain in detail|"
    r"step[- ]by[- ]step|prove|calculate|optimi[sz]e|translate)\b.{12,}", re.I | re.S)
MAKE_FILES = re.compile(r"\b(save|file|files|folder|page|website|site|app|project|script|document|"
                        r"\.(py|html|js|md|css|json|txt|csv))\b", re.I)
EXPLICIT_REMEMBER = re.compile(r"\b(remember|memori[sz]e|note (that|this|down)|make a note|take a note|"
                               r"don'?t forget|keep in mind|save (this|that))\b", re.I)
# Sentences that claim something was kept. Removed from a reply while JARVIS is
# still only OFFERING to remember, because at that point nothing has been saved.
SAVE_CLAIM = re.compile(r"\b(noted|note of|logged|saved|recorded|stored|flagged|marked|registered|"
                        r"remember(ed)?|memori[sz]ed|"
                        r"keep (that|this|it) in mind|bear (that|this|it) in mind|in (my )?memory|"
                        r"i'?ll (ensure|make sure|keep)|from now on|going forward)\b", re.I)
MEMORY_MARK = re.compile(r"\s*\[memory:\s*([0-9,\s]*)\]\s*$", re.I)

ROUTER = """You decide how JARVIS handles the owner's latest message. Reply with ONE JSON object.

{"mode": "act", "goal": "<the request restated as a complete, self-contained instruction>"}
  when the owner wants JARVIS to DO something with its own tools, or to look up their own
  stored information: create, change, complete or list tasks; search stored memories;
  record a lesson; list or read projects; check JARVIS's health. Also choose "act" for a
  QUICK look-up on the internet (news, a price, one fact) or when the owner gives a web
  address to read. In-depth research or comparisons are "delegate", not "act".

{"mode": "delegate", "task": "<the request restated as a complete, self-contained task>", "files": true | false}
  when the request needs real skill or deep thinking: writing, fixing or explaining code; building
  something (a script, a web page, an app, a document); in-depth research or comparison; careful
  analysis; long or polished writing; detailed plans or strategy; hard maths or reasoning.
  "files": true when the owner wants something made or saved as files.

{"mode": "remember", "fact": "<the fact in the first person, as the owner would say it,
 e.g. 'I prefer short answers' - never 'The user ...'>", "category": "preference" | "personal" | "general"}
  when the owner explicitly asks JARVIS to remember or note something.

{"mode": "answer"}
  for everything else: conversation, greetings, general knowledge, explanations, maths,
  advice, opinions, or requests for abilities JARVIS does not have (email, calendar,
  devices, payments). If unsure whether the owner wants an action, choose "answer".
  If, in passing, the owner states a LASTING fact or preference about themselves (for
  example "call me Arfan", "I'm vegetarian", "I work late on Thursdays"), add
  "remember": "<that fact>" and "category" so JARVIS can offer to remember it. Do not do
  this for questions, passing moods, or one-off remarks.

Write the goal so it makes sense without the conversation (resolve "it", "that", "him").
Keep any web address the owner gave, exactly as written, in the goal.

JARVIS's tools:
"""

ANSWER_FROM_DATA = """You are JARVIS, the owner's executive intelligence: calm, precise, natural, never robotic.
The owner asked something and you looked it up. Answer using ONLY the results below. Lead with the
answer; be brief.
If the results do not contain the answer, say you don't have that information.
Do not mention tools, JSON or databases. Do not claim to have changed anything.

Projects are given by id in the results; use these names for them: {projects}
It is now {today}.

RESULTS:
"""


def system_prompt(tools: list[dict], memories: list[dict] | None = None) -> str:
    abilities = "\n".join(f"- {tool['description']}" for tool in tools)
    known = ""
    if memories:
        facts = "\n".join(f"[{m['id']}] {m['content']} ({m['verification_status'].replace('_', ' ')})"
                          for m in memories)
        known = ("\n\nWhat you know about the owner (from JARVIS's memory):\n" + facts + "\n"
                 "Use these facts where they genuinely help, naturally (\"You mentioned you prefer…\"). "
                 "Treat 'unverified' ones with care. If your reply relies on any of them, end it with a "
                 "final line exactly like [memory: 3, 7] listing their numbers. Otherwise add nothing.")
    return (
        persona.CHARACTER + "\nNever mention JSON, tools or prompts.\n\n"
        f"Actions JARVIS can carry out when the owner asks:\n{abilities}\n\n"
        f"It is now {now_local()} (the owner's local time).\n"
        "JARVIS can search the web and read web pages (through actions), and the owner can talk to it by voice. "
        "JARVIS cannot send email or messages, make phone calls, use a calendar, control devices or "
        "make payments. Never claim or offer these. "
        "You can freely share general knowledge, ideas, suggestions and advice from what you know.\n"
        "In this reply you are only talking. Never say you have done, saved, added or changed "
        "anything: actions are carried out and reported separately. If the owner seems to want "
        "an action, you may suggest how to ask for it. If you do not know something, say so."
        + known
    )


def _quote(value, limit: int = 80) -> str:
    value = " ".join(str(value).split()).rstrip(".")
    return f"“{value if len(value) <= limit else value[:limit - 1] + '…'}”"


def _phrase(tool: str, output) -> str:
    """Fixed, factual wording for one change, taken from the tool's own output."""
    record = output if isinstance(output, dict) else {}
    if tool == "tasks.create":
        return f"added the task {_quote(record.get('title', ''))}"
    if tool == "tasks.update":
        return f"updated the task {_quote(record.get('title', ''))}"
    if tool == "tasks.complete":
        return f"marked {_quote((record.get('task') or {}).get('title', ''))} as done"
    if tool == "memory.save":
        if record.get("duplicate"):
            return f"found {_quote(record.get('content', ''))} already in memory"
        return f"noted {_quote(record.get('content', ''))}"
    if tool == "experience.record":
        return f"recorded the lesson {_quote(record.get('title', ''))}"
    return f"ran {tool}"


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def auto_learn() -> bool:
    """Save lasting facts from chat without asking (default on; JARVIS_AUTO_LEARN=0 turns it off)."""
    return os.environ.get("JARVIS_AUTO_LEARN", "1") != "0"


class Conversation:
    def __init__(self, app):
        self.app = app

    # --- entry point -------------------------------------------------------
    def respond(self, conversation_id: int, text: str) -> dict:
        """Produce and store JARVIS's reply to the latest user message."""
        pending = self._pending_question(conversation_id)
        if pending:
            if CANCEL.match(text):
                self.app.engine.cancel(pending)
                return self._say(conversation_id, persona.DROPPED, pending)
            return self._act(conversation_id, text, resume=pending)

        offer = self._pending_offer(conversation_id)
        if offer and YES.match(text):
            return self._remember(conversation_id, offer["fact"], offer["category"])
        if offer and NO.match(text):
            return self._say(conversation_id, persona.WONT_KEEP, None)

        decision = self._route(conversation_id)
        if decision.get("mode") == "act":
            return self._act(conversation_id, decision["goal"])
        if decision.get("mode") == "delegate":
            return self._delegate(conversation_id, decision["task"], decision["files"])
        if decision.get("mode") == "remember":
            return self._remember(conversation_id, decision["fact"], decision["category"])
        if decision.get("remember") and auto_learn():
            # Owner's standing instruction: keep lasting facts without asking. Saved as
            # unverified, with the chat as its source, so it can be reviewed or deleted.
            self._learn(decision["remember"])
            return self._answer(conversation_id)
        return self._answer(conversation_id, offer=decision.get("remember"))

    def _learn(self, offer: dict) -> dict | None:
        result = self.app.tools.execute(
            "memory.save", {"content": offer["fact"], "category": offer["category"],
                            "verification_status": "unverified", "confidence": 0.7}, actor="jarvis:learn")
        return result["output"] if result["ok"] else None

    # --- routing -----------------------------------------------------------
    def _history(self, conversation_id: int) -> list[dict]:
        return [m for m in self.app.conversations.messages(conversation_id)
                if m["role"] in ("user", "assistant")][-HISTORY:]

    def _route(self, conversation_id: int) -> dict:
        tools = "\n".join(f"- {t['name']}: {t['description']}" for t in self.app.tools.list())
        transcript = "\n".join(f"{m['role'].upper()}: {m['content'][:1000]}" for m in self._history(conversation_id))
        try:
            reply = self.app.provider.generate(
                [ChatMessage("system", ROUTER + tools),
                 ChatMessage("user", f"CONVERSATION (latest message last):\n{transcript}")],
                json_output=True).text
            decision = parse_json(reply)
        except (ValueError, ProviderError) as exc:
            log.info("Routing fell back to answer: %s", exc)
            return {"mode": "answer"}
        goal, fact = decision.get("goal"), decision.get("fact") or decision.get("remember")
        category = decision.get("category") if decision.get("category") in MEMORY_CATEGORIES else "general"
        fact = fact.strip()[:500] if isinstance(fact, str) and fact.strip() else None
        task = decision.get("task")
        latest = next((m["content"] for m in reversed(self._history(conversation_id)) if m["role"] == "user"), "")
        can_delegate = "claude.work" in self.app.tools.names()
        if can_delegate and decision.get("mode") in ("answer", None) and HARD_WORK.search(latest):
            task, decision = latest, {"mode": "delegate"}   # the small model under-rates hard work
        if decision.get("mode") == "delegate" and isinstance(task, str) and task.strip() and can_delegate:
            files = decision.get("files") is True or bool(MAKE_FILES.search(f"{latest} {task}"))
            return {"mode": "delegate", "task": task.strip()[:6000], "files": files}
        if decision.get("mode") == "act" and isinstance(goal, str) and goal.strip():
            return {"mode": "act", "goal": goal.strip()[:2000]}
        if decision.get("mode") == "remember" and fact:
            latest = next((m["content"] for m in reversed(self._history(conversation_id)) if m["role"] == "user"), "")
            if EXPLICIT_REMEMBER.search(latest):
                return {"mode": "remember", "fact": fact, "category": category}
            # Not asked in so many words: answer, and offer instead of saving silently.
            return {"mode": "answer", "remember": {"fact": fact, "category": category}}
        return {"mode": "answer", "remember": {"fact": fact, "category": category} if fact else None}

    def _pending_question(self, conversation_id: int) -> int | None:
        """The run the previous JARVIS reply asked a question about, if still open."""
        assistant = [m for m in self.app.conversations.messages(conversation_id, limit=20)
                     if m["role"] in ("assistant", "system")]
        if not assistant or not assistant[-1].get("run_id"):
            return None
        run = self.app.runs.get(assistant[-1]["run_id"], with_steps=False)
        return run["id"] if run["status"] == "blocked" else None

    def _pending_offer(self, conversation_id: int) -> dict | None:
        """The memory JARVIS offered to keep in its previous reply, if any."""
        replies = [m for m in self.app.conversations.messages(conversation_id, limit=20)
                   if m["role"] in ("assistant", "system")]
        return replies[-1]["memory_offer"] if replies else None

    # --- answering ---------------------------------------------------------
    def _answer(self, conversation_id: int, offer: dict | None = None, note: str = "") -> dict:
        history = self._history(conversation_id)
        latest = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        memories = ContextBuilder(self.app).build(latest)["memories"]
        instructions = system_prompt(self.app.tools.list(), memories)
        if offer:   # JARVIS asks about saving it itself, in fixed wording, after this reply
            instructions += ("\nDo not mention remembering, noting or saving anything in this reply, "
                             "and do not ask whether to: that question is asked separately.")
        prompt = [ChatMessage("system", instructions)]
        prompt += [ChatMessage(m["role"], m["content"]) for m in history]
        response = self.app.provider.generate(prompt)
        text, refs = response.text, []
        mark = MEMORY_MARK.search(text)
        if mark:                     # keep only ids that were really supplied
            ids = {int(n) for n in re.findall(r"\d+", mark.group(1))}
            refs = [{"id": m["id"], "content": m["content"]} for m in memories if m["id"] in ids]
            text = text[:mark.start()].rstrip()
        if offer:
            # A plain statement gets a plain acknowledgement; only a real question keeps the
            # model's answer, and then without any sentence claiming something was kept.
            kept = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s and not SAVE_CLAIM.search(s)]
            text = " ".join(kept) if "?" in latest and kept else "Understood."
            text += f"\n\nShall I remember that: {_quote(offer['fact'], 200)}?"
        return self.app.conversations.add_message(
            conversation_id, "assistant", (text or "…") + note, response.provider, response.model,
            memory_refs=refs or None, memory_offer=offer)

    # --- remembering -------------------------------------------------------
    def _remember(self, conversation_id: int, fact: str, category: str) -> dict:
        """Save a fact the owner asked JARVIS to keep (or agreed to), as owner-provided."""
        result = self.app.tools.execute(
            "memory.save", {"content": fact, "category": category, "verification_status": "user_provided"},
            actor="user:chat")
        if not result["ok"]:
            return self.app.conversations.add_message(
                conversation_id, "system", f"I couldn't save that: {result['error']}")
        saved = result["output"]
        text = (persona.ALREADY_KNOWN.format(fact=_quote(saved['content'], 200)) if saved.get("duplicate")
                else persona.REMEMBERED.format(fact=_quote(saved['content'], 200)))
        status = self.app.provider.status()
        return self.app.conversations.add_message(
            conversation_id, "assistant", text, status.name, status.model,
            memory_refs=[{"id": saved["id"], "content": saved["content"]}])

    # --- acting ------------------------------------------------------------
    def _act(self, conversation_id: int, goal: str, resume: int | None = None) -> dict:
        try:
            report = self.app.engine.resume(resume, answer=goal) if resume else self.app.engine.start(goal)
        except (JarvisError, ProviderError) as exc:
            return self.app.conversations.add_message(
                conversation_id, "system", f"I couldn't start that: {exc}", run_id=resume)
        text = self._narrate(conversation_id, report)
        return self._say(conversation_id, text, report["run_id"])

    def _delegate(self, conversation_id: int, task: str, files: bool) -> dict:
        """Hard work goes to Claude Code (claude.work); its result is JARVIS's reply."""
        result = self.app.tools.execute("claude.work", {"task": task, "write_files": files}, actor="user:chat")
        if result["ok"]:
            text = (result["output"] or {}).get("result", "").strip() or "Completed."
            return self.app.conversations.add_message(
                conversation_id, "assistant", text, "claude-code", "claude", run_id=result["run_id"])
        if result["status"] == "approval_required":
            return self._say(conversation_id, persona.NEEDS_APPROVAL if hasattr(persona, "NEEDS_APPROVAL")
                             else "That needs your approval first.", result["run_id"])
        log.info("Delegation failed, answering locally: %s", result["error"])
        error = str(result["error"] or "")
        why = ("Claude Code is signed out; run `claude` in Terminal and sign in"
               if "authenticat" in error.lower() or "login" in error.lower() else f"Claude Code failed: {error[:200]}")
        return self._answer(conversation_id, note=f"\n\n(Answered by the local model only. {why}.)")

    def _say(self, conversation_id: int, text: str, run_id: int | None) -> dict:
        status = self.app.provider.status()
        return self.app.conversations.add_message(conversation_id, "assistant", text,
                                                  status.name, status.model, run_id=run_id)

    def _narrate(self, conversation_id: int, report: dict) -> str:
        """Describe what happened, using only what the run log recorded."""
        run = self.app.runs.get(report["run_id"])
        done = [s for s in run["steps"] if s["plan_id"] is not None and s["status"] == "succeeded"]
        changes, created = [], set()
        for step in done:
            if step["category"] in ("read", "web_read"):
                continue
            output = step["output"] if isinstance(step["output"], dict) else {}
            if step["tool"] == "tasks.update" and output.get("id") in created:
                continue                      # refining a task it just added is part of adding it
            if step["tool"] == "tasks.create":
                created.add(output.get("id"))
            phrase = _phrase(step["tool"], step["output"])
            if phrase not in changes:
                changes.append(phrase)
        did = f"I {_join(changes)}." if changes else ""
        status = report["status"]

        prefix = f"{did} " if did else ""
        if status == "completed":
            if changes:
                return persona.COMPLETED.format(did=did)
            answer = self._answer_from_data(conversation_id, done) or persona.COMPLETED_NOTHING_CHANGED
            return answer + self._sources(done)
        if status == "blocked":
            return persona.NEEDS_INFORMATION.format(did=prefix, question=report["question"])
        if status == "waiting_approval":
            approval = report.get("approval") or {}
            return persona.NEEDS_APPROVAL.format(did=prefix, summary=approval.get("summary", "an action"))
        if status == "cancelled":
            return persona.CANCELLED
        reason = report.get("error") or "It did not finish."
        return persona.FAILED.format(reason=reason) + (
            persona.FAILED_PARTIAL.format(did=did) if did else persona.FAILED_NOTHING_CHANGED)

    @staticmethod
    def _sources(steps: list[dict]) -> str:
        """Web addresses actually used, taken from the tool results (never from the model)."""
        outputs = [(s["tool"], s["output"] if isinstance(s["output"], dict) else {}) for s in steps]
        # Pages actually read are the sources; search hits count only if nothing was read.
        urls = [o["url"] for tool, o in outputs if tool == "web.fetch" and o.get("url")]
        if not urls:
            urls = [r["url"] for tool, o in outputs if tool == "web.search"
                    for r in o.get("results", [])[:3] if r.get("url")]
        urls = list(dict.fromkeys(urls))[:4]
        return ("\n\nSources: " + ", ".join(urls)) if urls else ""

    def _answer_from_data(self, conversation_id: int, steps: list[dict]) -> str | None:
        """Phrase a reply to a look-up from the data the tools returned."""
        results = json.dumps([{"tool": s["tool"], "result": s["output"]} for s in steps], default=str)[:8000]
        question = next((m["content"] for m in reversed(self._history(conversation_id)) if m["role"] == "user"), "")
        try:
            projects = ", ".join(f"{p['id']} = {p['name']}" for p in self.app.projects.list(active=None, limit=100))
            instructions = ANSWER_FROM_DATA.format(projects=projects or "none", today=now_local())
            reply = self.app.provider.generate([ChatMessage("system", instructions + results),
                                                ChatMessage("user", question)]).text.strip()
        except ProviderError as exc:
            log.info("Could not phrase look-up answer: %s", exc)
            return None
        return reply or None
