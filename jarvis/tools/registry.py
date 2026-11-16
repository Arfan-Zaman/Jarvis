"""Tool registry and execution engine.

A tool is a named capability with a description, an input schema and a
permission level (its safety category). `ToolRegistry.execute` is the only
way a tool runs. It always, in this order:

1. finds the tool (unknown tools are refused),
2. checks the caller's allow-list, if one was given,
3. validates the inputs against the schema,
4. asks the safety layer (read: runs; write: runs unless read-only mode;
   anything high-impact: pauses for human approval),
5. runs the handler, catching every error,
6. writes the outcome to the run log,
7. returns a structured result. It never raises for a failed tool.

There is deliberately no shell or "run arbitrary code" tool.

To add a tool, write a handler `fn(app, inputs, actor)` that returns
JSON-serialisable data and call `registry.register(Tool(...))`.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from ..common import JarvisError, NotFoundError, PermissionDenied, ValidationError, utcnow
from ..logging_setup import get_logger
from ..safety import APPROVAL_REQUIRED, ActionCategory

log = get_logger("tools")

_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
_SPEC_KEYS = {"type", "description", "required", "enum", "default"}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    category: ActionCategory          # permission level
    handler: Callable                 # fn(app, inputs: dict, actor: str) -> JSON-serialisable
    inputs: dict = field(default_factory=dict)   # {field: {type, description, required, enum, default}}

    def spec(self) -> dict:
        """Public description, used for discovery (and later shown to a model)."""
        return {"name": self.name, "description": self.description,
                "permission": self.category.value,
                "requires_approval": self.category in APPROVAL_REQUIRED,
                "inputs": self.inputs}


def approval_summary(name: str, inputs: dict) -> str:
    """What the owner is approving, in words: the tool and the inputs that matter (shown on the Approve button)."""
    plain = {
        "skills.install": lambda i: f"Install the skill from {i.get('source')}" + (f" (only '{i['name']}')" if i.get("name") else ""),
        "system.install": lambda i: f"Install {i.get('package')} with {i.get('manager')}",
        "browser.use": lambda i: f"Use JARVIS's Chrome to: {i.get('task')}",
        "claude.operate": lambda i: f"Mac access for: {i.get('task')}",
        "claude.browse": lambda i: f"Browser task: {i.get('task')}",
        "mail.send": lambda i: f"Send an email to {i.get('to')}: {i.get('subject')}",
    }
    try:
        text = plain[name](inputs) if name in plain else f"Run tool {name}"
    except Exception:  # noqa: BLE001
        text = f"Run tool {name}"
    text = " ".join(str(text).split())
    return text if len(text) <= 240 else text[:239] + "…"


class ToolRegistry:
    def __init__(self, app):
        self.app = app
        self._tools: dict[str, Tool] = {}

    # --- registration and discovery ---------------------------------------
    def register(self, tool: Tool) -> Tool:
        if not isinstance(tool.name, str) or not _NAME.match(tool.name):
            raise ValidationError(f"Invalid tool name: {tool.name!r} (use lower-case words joined by dots)")
        if tool.name in self._tools:
            raise ValidationError(f"Tool {tool.name} is already registered")
        if not isinstance(tool.category, ActionCategory):
            raise ValidationError(f"Tool {tool.name}: permission must be an ActionCategory")
        if not tool.description.strip() or not callable(tool.handler):
            raise ValidationError(f"Tool {tool.name}: a description and a handler are required")
        for name, spec in tool.inputs.items():
            if spec.get("type") not in _TYPES or set(spec) - _SPEC_KEYS:
                raise ValidationError(f"Tool {tool.name}: bad schema for input {name!r}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except (KeyError, TypeError):
            raise NotFoundError(f"Unknown tool: {name}") from None

    def list(self, permission: str | None = None) -> list[dict]:
        return [tool.spec() for name, tool in sorted(self._tools.items())
                if permission is None or tool.category.value == permission]

    def names(self) -> list[str]:
        return sorted(self._tools)

    # --- input validation --------------------------------------------------
    @staticmethod
    def validate(tool: Tool, inputs) -> dict:
        if inputs is None:
            inputs = {}
        if not isinstance(inputs, dict):
            raise ValidationError("inputs must be an object of named values")
        unknown = sorted(set(inputs) - set(tool.inputs))
        if unknown:
            raise ValidationError(f"Unknown input(s) for {tool.name}: {', '.join(map(str, unknown))}")
        clean = {}
        for name, spec in tool.inputs.items():
            value = inputs.get(name, spec.get("default"))
            if value is None:
                if spec.get("required"):
                    raise ValidationError(f"{tool.name}: '{name}' is required")
                continue
            expected = _TYPES[spec["type"]]
            if not isinstance(value, expected) or (isinstance(value, bool) and spec["type"] != "boolean"):
                raise ValidationError(f"{tool.name}: '{name}' must be a {spec['type']}")
            if "enum" in spec and value not in spec["enum"]:
                raise ValidationError(f"{tool.name}: '{name}' must be one of: {', '.join(map(str, spec['enum']))}")
            clean[name] = value
        return clean

    # --- execution ---------------------------------------------------------
    def execute(self, name: str, inputs: dict | None = None, *, actor: str = "user",
                approval_id: int | None = None, run_id: int | None = None,
                allowed: list[str] | None = None, plan_id: int | None = None) -> dict:
        """Run a tool and return a structured result. Never raises for tool failure.

        `allowed` restricts the caller to a list of tool names (for agents).
        `run_id` appends to an existing run; otherwise a run is created.
        To proceed after approval, call again with the same inputs, the
        `approval_id`, and the `run_id` from the first result.
        """
        runs = self.app.runs
        started_at, clock = utcnow(), time.monotonic()
        run = runs.get(run_id, with_steps=False) if run_id is not None else \
            runs.create(f"Tool call: {name}", kind="tool", actor=actor)
        status, output, error, approval, category = "failed", None, None, None, None
        recorded_inputs = inputs
        try:
            try:
                tool = self.get(name)
            except NotFoundError as exc:
                raise PermissionDenied(str(exc)) from None
            category = tool.category.value
            if allowed is not None and name not in allowed:
                raise PermissionDenied(f"{actor} is not permitted to use the tool {name}")
            clean = recorded_inputs = self.validate(tool, inputs)
            decision = self.app.safety.authorize(
                f"tool.{name}", tool.category, approval_summary(name, clean),
                details={"tool": name, "inputs": clean}, actor=actor, approval_id=approval_id)
            if decision.requires_approval:
                status, approval = "waiting_approval", decision.approval
            else:
                output = json.loads(json.dumps(tool.handler(self.app, clean, actor), default=str))
                status = "succeeded"
        except PermissionDenied as exc:
            status, error = "refused", str(exc)
            self.app.events.record("audit", f"tool.{name}", f"Tool refused: {exc}", level="warning", actor=actor)
        except JarvisError as exc:          # bad input, missing record, provider error...
            error = str(exc)
        except Exception as exc:            # noqa: BLE001 - a broken tool must not break JARVIS
            log.exception("Tool %s crashed", name)
            error = f"{type(exc).__name__}: {exc}"

        duration_ms = int((time.monotonic() - clock) * 1000)
        step = runs.add_step(
            run["id"], tool=str(name), category=category, actor=actor, inputs=recorded_inputs, output=output,
            error=error, status=status, approval_id=approval["id"] if approval else approval_id,
            started_at=started_at, duration_ms=duration_ms, plan_id=plan_id)
        if run["kind"] == "tool":           # single-call runs follow their one tool
            runs.set_status(run["id"], {"succeeded": "completed", "waiting_approval": "waiting_approval"}
                            .get(status, "failed"), result=output, error=error)
        return {
            "ok": status == "succeeded",
            "status": "approval_required" if status == "waiting_approval" else status,
            "tool": name, "permission": category, "output": output, "error": error,
            "approval": approval, "run_id": run["id"], "step_id": step["id"], "duration_ms": duration_ms,
        }
