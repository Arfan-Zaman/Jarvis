"""Reminders and recurring jobs (see `jarvis/scheduler.py`).

- schedule.add: a reminder ("remind me at 5pm to call the supplier") or a job
  JARVIS runs itself ("every weekday at 8am check the used-car prices").
- schedule.list: what is set, with when each fires next.
- schedule.cancel: stop one, by its number or by what it is about.
"""

from __future__ import annotations

from ..common import ValidationError
from ..safety import ActionCategory
from .registry import Tool, ToolRegistry

READ, WRITE = ActionCategory.READ, ActionCategory.WRITE


def add(app, inputs, actor):
    item = app.scheduler.add(inputs.get("kind", "reminder"), inputs["text"], inputs["when"], source=actor)
    return {"id": item["id"], "kind": item["kind"], "text": item["text"], "next_at": item["next_at"],
            "recur": item["recur"], "summary": item["summary"]}


def list_(app, inputs, actor):
    items = app.scheduler.listing()
    return {"count": len(items), "items": [{"id": i["id"], "kind": i["kind"], "text": i["text"], "when": i["when"]}
                                           for i in items]}


def cancel(app, inputs, actor):
    if inputs.get("id") is not None:
        item = app.scheduler.cancel(inputs["id"], actor=actor)
        return {"id": item["id"], "text": item["text"], "status": item["status"], "summary": item["summary"]}
    about = (inputs.get("about") or "").strip()
    if not about:
        raise ValidationError("schedule.cancel: give the reminder's number ('id') or what it is about ('about')")
    matches = app.scheduler.find(about)
    if not matches:
        raise ValidationError(f"No reminder or scheduled job matches {about!r}")
    item = app.scheduler.cancel(matches[0]["id"], actor=actor)
    return {"id": item["id"], "text": item["text"], "status": item["status"], "summary": item["summary"]}


def register_schedule(registry: ToolRegistry) -> None:
    S = lambda d, **x: {"type": "string", "description": d, **x}    # noqa: E731
    for tool in (
        Tool("schedule.add", "Set a reminder for the owner, or a job JARVIS runs at a time or on a repeating "
             "schedule (e.g. 'every weekday at 8am').", WRITE, add,
             {"text": S("What to remind about, or the request to carry out.", required=True),
              "when": S("When, in plain English: 'at 5pm', 'tomorrow morning', 'in 20 minutes', "
                        "'every weekday at 8am'.", required=True),
              "kind": S("'reminder' (tell the owner) or 'job' (JARVIS does the request itself).",
                        enum=["reminder", "job"], default="reminder")}),
        Tool("schedule.list", "List the owner's reminders and scheduled jobs and when each fires next.", READ, list_),
        Tool("schedule.cancel", "Cancel a reminder or scheduled job, by its number or by what it is about.", WRITE,
             cancel, {"id": {"type": "integer", "description": "The reminder's number."},
                      "about": S("Words from what it is about, e.g. 'supplier'.")}),
    ):
        registry.register(tool)
