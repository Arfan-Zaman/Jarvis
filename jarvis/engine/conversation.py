"""Conversation: one chat that both talks and acts.

For every message JARVIS decides:

- ANSWER: talk, explain, calculate, advise. No tools, nothing changes.
- ACT:    the owner wants something done with JARVIS's own tools (add a task,
          remember something, look up their tasks...). The request is handed
          to the reasoning engine, which plans, acts, checks and reports.

Honesty rule: what JARVIS says it *did* is written from the engine's record,
never from the model's imagination. Fixed wording describes changes, questions,
approvals and failures. The model is only asked to phrase an answer when
nothing was changed, and then only from the data the tools actually returned.

If a previous action is waiting for information, the owner's next message is
taken as the answer (unless they cancel it).
"""

from __future__ import annotations

import json
import re

from ..common import JarvisError, now_local
from ..logging_setup import get_logger
from ..providers import ChatMessage, ProviderError
from .engine import parse_json

log = get_logger("conversation")

HISTORY = 10
CANCEL = re.compile(r"^\s*(cancel|never ?mind|forget it|stop|don'?t bother|no,? leave it)\b", re.I)

ROUTER = """You decide how JARVIS handles the owner's latest message. Reply with ONE JSON object.

{"mode": "act", "goal": "<the request restated as a complete, self-contained instruction>"}
  when the owner wants JARVIS to DO something with its own tools, or to look up their own
  stored information: create, change, complete or list tasks; remember or recall something;
  record a lesson; list or read projects; check JARVIS's health.

{"mode": "answer"}
  for everything else: conversation, greetings, general knowledge, explanations, maths,
  advice, opinions, or requests for abilities JARVIS does not have (email, calendar, web,
  devices, payments). If unsure whether the owner wants an action, choose "answer".

Write the goal so it makes sense without the conversation (resolve "it", "that", "him").

JARVIS's tools:
"""

ANSWER_FROM_DATA = """You are JARVIS. The owner asked something and JARVIS looked it up in its own
database. Answer the owner's message using ONLY the results below. Be brief and natural.
If the results do not contain the answer, say you don't have that information.
Do not mention tools, JSON or databases. Do not claim to have changed anything.

Projects are given by id in the results; use these names for them: {projects}
It is now {today}.

RESULTS:
"""


def system_prompt(tools: list[dict]) -> str:
    abilities = "\n".join(f"- {tool['description']}" for tool in tools)
    return (
        "You are JARVIS, a private assistant running entirely on the owner's Mac. "
        "Be calm, concise and precise, with a light touch of dry wit when it fits. "
        "Speak naturally; never mention JSON, tools or prompts.\n\n"
        f"Actions JARVIS can carry out when the owner asks:\n{abilities}\n\n"
        f"It is now {now_local()} (the owner's local time).\n"
        "JARVIS cannot send email or messages, use a calendar, browse the web, control devices, "
        "make payments, or act outside its own records. Never claim or offer these.\n"
        "In this reply you are only talking. Never say you have done, saved, added or changed "
        "anything: actions are carried out and reported separately. If the owner seems to want "
        "an action, you may suggest how to ask for it. If you do not know something, say so."
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
                return self._say(conversation_id, "Understood. I've dropped that request.", pending)
            return self._act(conversation_id, text, resume=pending)

        decision = self._route(conversation_id)
        if decision.get("mode") == "act":
            return self._act(conversation_id, decision["goal"])
        return self._answer(conversation_id)

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
        goal = decision.get("goal")
        if decision.get("mode") == "act" and isinstance(goal, str) and goal.strip():
            return {"mode": "act", "goal": goal.strip()[:2000]}
        return {"mode": "answer"}

    def _pending_question(self, conversation_id: int) -> int | None:
        """The run the previous JARVIS reply asked a question about, if still open."""
        assistant = [m for m in self.app.conversations.messages(conversation_id, limit=20)
                     if m["role"] in ("assistant", "system")]
        if not assistant or not assistant[-1].get("run_id"):
            return None
        run = self.app.runs.get(assistant[-1]["run_id"], with_steps=False)
        return run["id"] if run["status"] == "blocked" else None

    # --- answering ---------------------------------------------------------
    def _answer(self, conversation_id: int) -> dict:
        prompt = [ChatMessage("system", system_prompt(self.app.tools.list()))]
        prompt += [ChatMessage(m["role"], m["content"]) for m in self._history(conversation_id)]
        response = self.app.provider.generate(prompt)
        return self.app.conversations.add_message(conversation_id, "assistant", response.text,
                                                  response.provider, response.model)

    # --- acting ------------------------------------------------------------
    def _act(self, conversation_id: int, goal: str, resume: int | None = None) -> dict:
        try:
            report = self.app.engine.resume(resume, answer=goal) if resume else self.app.engine.start(goal)
        except (JarvisError, ProviderError) as exc:
            return self.app.conversations.add_message(
                conversation_id, "system", f"I couldn't start that: {exc}", run_id=resume)
        text = self._narrate(conversation_id, report)
        return self._say(conversation_id, text, report["run_id"])

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
            if step["category"] == "read":
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

        if status == "completed":
            if changes:
                return f"Done. {did}"
            return self._answer_from_data(conversation_id, done) or "Done. Nothing needed changing."
        if status == "blocked":
            return (f"{did} " if did else "") + f"Before I go on: {report['question']}"
        if status == "waiting_approval":
            approval = report.get("approval") or {}
            return ((f"{did} " if did else "")
                    + f"This next step needs your approval: {approval.get('summary', 'an action')}. "
                      "Approve or deny it on the System page, then press Continue.")
        if status == "cancelled":
            return "That request was cancelled."
        reason = report.get("error") or "it did not finish"
        return (f"I couldn't complete that. {reason}"
                + (f" What I did manage: {did[2:] if did.startswith('I ') else did}" if did else " Nothing was changed."))

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
