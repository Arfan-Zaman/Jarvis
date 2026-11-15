"""Reasoning engine: turns a plain-language goal into planned, executed and
verified tool calls.

How one goal runs:

1. PLAN    The model is asked for a short plan: ordered steps, each naming one
           registered tool. The plan is checked and stored before anything runs.
2. ACT     For each step, the model supplies that tool's inputs. The engine
           executes it through `ToolRegistry.execute`, the same permission-
           checked path as every other tool call. Nothing else can act.
3. CHECK   The engine reads the structured result. Success moves on. A failure
           is shown to the model for one corrected attempt. A refusal stops
           the run. An approval request pauses it.
4. REPORT  Built from the run log, never from the model's own account. A run
           is "completed" only when every planned step has a recorded
           successful execution.

The model can also say it is blocked on missing information, which stops the
run with its question. Limits on plan length, tool failures and model calls
make endless loops impossible. Plan, context and progress are stored, so an
interrupted or paused run can be resumed.

The model is whatever `app.provider` is. With none connected, the engine
refuses to start rather than pretend.
"""

from __future__ import annotations

import json
import re

from ..common import JarvisError, NotFoundError, ValidationError, text
from ..logging_setup import get_logger
from ..providers import ChatMessage, ProviderError
from ..safety import ActionCategory
from ..tools.registry import ToolRegistry

log = get_logger("engine")

ENGINE_ACTOR = "jarvis-core"     # steps chosen by the model are attributed to JARVIS, not the owner
RESUMABLE = ("interrupted", "waiting_approval", "blocked")
ATTEMPTS_PER_STEP = 2
_STOP_WORDS = frozenset("about after again also been before being could does doing from have into just like "
                        "make more most need only other over please should some such than that their them then "
                        "there these they this those what when where which will with would your".split())

PROTOCOL = """You are the planning component of JARVIS. You do not act directly: you choose
from the listed tools and JARVIS executes them and shows you the results.
Reply with ONE JSON object and nothing else.

When asked for a PLAN, reply with either
  {"plan": [{"description": "<what this step does>", "tool": "<tool name>"}, ...]}
or, if the goal cannot be planned without more information from the owner,
  {"blocked": "<the question to ask the owner>"}

When asked for an ACTION for a step, reply with either
  {"inputs": {<inputs for that step's tool>}}
or
  {"blocked": "<the question to ask the owner>"}

When asked for a REVIEW, compare the goal with the recorded results and reply with either
  {"achieved": true, "summary": "<one or two sentences describing only what the results show>"}
or, if the goal is not fully achieved yet,
  {"achieved": false, "missing": "<what is still missing>",
   "next_steps": [{"description": "...", "tool": "..."}, ...]}
(leave next_steps empty if the missing part cannot be done with the tools).

Rules:
- A plan must include the steps that actually make the requested change. Looking
  something up (list, get, search) does not by itself add, create, save or update anything.
- The owner's projects are listed under "projects" with their ids. If the goal names
  one, use its id directly. If the goal does not mention a project, leave project_id out:
  it is optional.
- Ask only when the goal refers to something that genuinely has more than one possible
  meaning (for example "the business" when there are several projects) or a REQUIRED
  input is missing. Then reply {"blocked": "<short question>"}. Never guess which project,
  person or value the owner means, and never ask about something already answered in
  "answers_from_owner".
- Use only the listed tools and only their listed inputs. Use ids from results; never invent them.
- Keep plans short. Never state that something was done unless a result shown to you says so."""


class _Halt(Exception):
    """Stops the current run with a final status and a reason."""

    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def parse_json(reply: str) -> dict:
    """Extract the first JSON object from a model reply."""
    start = reply.find("{") if isinstance(reply, str) else -1
    if start < 0:
        raise ValueError("the reply contained no JSON object")
    try:
        value, _ = json.JSONDecoder().raw_decode(reply[start:])
    except ValueError as exc:
        raise ValueError(f"the reply was not valid JSON ({exc})") from None
    if not isinstance(value, dict):
        raise ValueError("the reply must be a JSON object")
    return value


def _question(reply: dict) -> str | None:
    blocked = reply.get("blocked")
    return blocked.strip() if isinstance(blocked, str) and blocked.strip() else None


class Engine:
    def __init__(self, app):
        self.app = app

    # --- public API --------------------------------------------------------
    def start(self, goal: str, actor: str = "user", allowed: list[str] | None = None) -> dict:
        """Plan and carry out a goal. Returns the report (see `report`)."""
        goal = text("goal", required=True, max_len=2000)(goal)
        self.app.safety.authorize("run.start", ActionCategory.WRITE, "Start a goal run", actor=actor)
        self._require_model()
        context = {"allowed": allowed, "answers": [], **self._recall(goal, allowed)}
        run = self.app.runs.create(goal, kind="goal", actor=actor)
        self.app.runs.update(run["id"], context=context)
        self.app.events.record("engine", "run.start", f"Goal run #{run['id']} started: {goal[:120]}", actor=actor,
                               details={"run_id": run["id"]})
        return self._drive(run["id"])

    def resume(self, run_id: int, answer: str | None = None, actor: str = "user") -> dict:
        """Continue a run that was interrupted, is waiting for approval, or
        was blocked on a question (`answer` supplies the missing information)."""
        run = self._goal_run(run_id)
        if run["status"] not in RESUMABLE:
            raise ValidationError(f"Run {run_id} is {run['status']} and cannot be resumed")
        self.app.safety.authorize("run.resume", ActionCategory.WRITE, "Resume a goal run", actor=actor)
        self._require_model()
        context = run["context"] or {"allowed": None, "answers": []}
        if run["status"] == "blocked":
            if not answer or not answer.strip():
                raise ValidationError(f"Run {run_id} is waiting for an answer: {run['error']}")
            context.setdefault("answers", []).append({"question": run["error"], "answer": answer.strip()})
            self.app.runs.update(run_id, context=context)
        for step in run["plan"]:
            if step["status"] == "running":       # was mid-step when JARVIS stopped
                done = any(e["plan_id"] == step["id"] and e["status"] == "succeeded" for e in run["steps"])
                self.app.runs.update_plan_step(step["id"], status="completed" if done else "pending")
            elif step["status"] == "blocked" and not step["approval_id"]:
                self.app.runs.update_plan_step(step["id"], status="pending", note=None)
        self.app.events.record("engine", "run.resume", f"Goal run #{run_id} resumed", actor=actor,
                               details={"run_id": run_id})
        return self._drive(run_id)

    def cancel(self, run_id: int, actor: str = "user") -> dict:
        run = self._goal_run(run_id)
        if run["status"] not in (*RESUMABLE, "running"):
            raise ValidationError(f"Run {run_id} is already {run['status']}")
        self.app.runs.update(run_id, status="cancelled", error="Cancelled by the owner")
        self.app.events.record("engine", "run.cancel", f"Goal run #{run_id} cancelled", actor=actor,
                               details={"run_id": run_id})
        return self.report(run_id)

    def report(self, run_id: int) -> dict:
        """What actually happened, taken from the stored plan and run log."""
        run = self._goal_run(run_id)
        plan, executions = run["plan"], [e for e in run["steps"] if e["plan_id"] is not None]
        proven = {e["plan_id"] for e in executions if e["status"] == "succeeded"}
        done = [step for step in plan if step["status"] == "completed" and step["id"] in proven]
        verified = bool(plan) and len(done) == len(plan) and run["status"] == "completed"
        waiting = next((step for step in plan if step["status"] == "blocked" and step["approval_id"]), None)
        headline = {
            "completed": f"Completed all {len(plan)} planned step(s); each has a recorded successful result.",
            "failed": f"Stopped after {len(done)} of {len(plan)} planned step(s): {run['error']}",
            "blocked": f"Needs information from you: {run['error']}",
            "waiting_approval": f"Paused for your approval after {len(done)} of {len(plan)} step(s): {run['error']}",
            "cancelled": f"Cancelled after {len(done)} of {len(plan)} planned step(s).",
            "interrupted": f"Interrupted after {len(done)} of {len(plan)} planned step(s). It can be resumed.",
            "running": f"In progress: {len(done)} of {len(plan)} planned step(s) done.",
        }[run["status"]]
        model_summary = (run["result"] or {}).get("model_summary")
        changes = [{"tool": e["tool"], "what": self._describe(e["output"])} for e in executions
                   if e["status"] == "succeeded" and e["category"] != "read"]
        if run["status"] == "completed":
            headline = (f"Goal achieved and checked: {len(plan)} step(s) succeeded, "
                        + (f"{len(changes)} change(s) made." if changes else "no changes were needed or made."))
        return {
            "run_id": run_id, "goal": run["goal"], "status": run["status"], "verified_complete": verified,
            "summary": headline, "error": run["error"],
            "question": run["error"] if run["status"] == "blocked" else None,
            "approval": self.app.safety.get_approval(waiting["approval_id"])
            if waiting and run["status"] == "waiting_approval" else None,
            "plan": [{"position": step["position"], "description": step["description"], "tool": step["tool"],
                      "status": step["status"], "attempts": step["attempts"], "note": step["note"]}
                     for step in plan],
            "executions": [{"step_id": e["id"], "plan_position": next(
                                (s["position"] for s in plan if s["id"] == e["plan_id"]), None),
                            "tool": e["tool"], "status": e["status"], "error": e["error"],
                            "duration_ms": e["duration_ms"]} for e in executions],
            "changes_made": changes,
            "counts": {status: sum(1 for e in executions if e["status"] == status)
                       for status in ("succeeded", "failed", "refused", "waiting_approval")},
            "context_used": {"memories": [m["id"] for m in (run["context"] or {}).get("memories", [])],
                             "lessons": [m["id"] for m in (run["context"] or {}).get("lessons", [])]},
            "model_summary": model_summary,
            "model_summary_note": "Written by the model. The status and steps above are what was verified."
            if model_summary else None,
            "created_at": run["created_at"], "finished_at": run["finished_at"],
        }

    # --- internals ---------------------------------------------------------
    @staticmethod
    def _describe(output) -> str:
        """A short, factual description of what a write tool produced."""
        record = output.get("task", output) if isinstance(output, dict) else {}
        for key in ("title", "content", "name"):
            if isinstance(record.get(key), str):
                return f"{key}: {record[key][:120]}" + (f" (#{record['id']})" if "id" in record else "")
        return json.dumps(output, default=str)[:120]

    def _goal_run(self, run_id: int) -> dict:
        run = self.app.runs.get(run_id)
        if run["kind"] != "goal":
            raise NotFoundError(f"Run {run_id} is not a goal run")
        return run

    def _require_model(self) -> None:
        status = self.app.provider.status()
        if not (status.configured and status.available):
            raise ProviderError("No AI model is connected, so JARVIS cannot plan or carry out goals. "
                                + status.detail)

    def _recall(self, goal: str, allowed) -> dict:
        """Read-only context: stored memories and lessons that mention the goal's key words."""
        if allowed is not None and "memory.search" not in allowed:
            return {"memories": [], "lessons": []}
        words = [w for w in dict.fromkeys(re.findall(r"[a-z0-9]{4,}", goal.lower())) if w not in _STOP_WORDS][:6]
        memories, lessons = {}, {}
        for word in words:
            for item in self.app.memory.list(query=word, limit=3):
                memories.setdefault(item["id"], {key: item[key] for key in (
                    "id", "content", "category", "source", "confidence", "verification_status")})
            for item in self.app.experiences.lessons(word, limit=2):
                lessons.setdefault(item["id"], {key: item[key] for key in ("id", "title", "outcome", "lesson")})
        return {"memories": list(memories.values())[:5], "lessons": list(lessons.values())[:3]}

    def _tools(self, allowed) -> list[dict]:
        return [tool for tool in self.app.tools.list() if allowed is None or tool["name"] in allowed]

    def _ask(self, kind: str, payload: dict, check, budget: dict, allowed) -> dict:
        """One question to the model, with one retry if the reply is unusable."""
        messages = [ChatMessage("system", PROTOCOL + "\n\nTOOLS:\n" + json.dumps(self._tools(allowed))),
                    ChatMessage("user", json.dumps({"request": kind, **payload}, default=str))]
        problem = ""
        for _ in range(2):
            if budget["calls"] >= self.app.config.engine_max_model_calls:
                raise _Halt("failed", f"Stopped: the limit of {self.app.config.engine_max_model_calls} "
                                      "model calls for one goal was reached")
            budget["calls"] += 1
            reply = self.app.provider.generate(messages, json_output=True).text
            try:
                return check(parse_json(reply))
            except (ValueError, JarvisError) as exc:
                problem = str(exc)
                messages += [ChatMessage("assistant", reply[:2000]),
                             ChatMessage("user", f"That reply cannot be used: {problem}. "
                                                 f"Reply again with one valid JSON object for the {kind}.")]
        raise _Halt("failed", f"The model gave an unusable {kind.lower()} twice: {problem}")

    def _state(self, run: dict) -> dict:
        context = run["context"] or {}
        answers = context.get("answers", [])
        goal = run["goal"]
        if answers:     # fold the owner's answers into the goal itself, so they cannot be overlooked
            goal += "\n\nThe owner has clarified: " + " ".join(
                f'Q: "{item["question"]}" A: "{item["answer"]}".' for item in answers)
        return {
            "goal": goal,
            "known_memories": context.get("memories", []), "lessons": context.get("lessons", []),
            "answers_from_owner": context.get("answers", []),
            "projects": [{"id": p["id"], "name": p["name"]} for p in self.app.projects.list(limit=100)],
            "plan": [{"position": s["position"], "description": s["description"], "tool": s["tool"],
                      "status": s["status"]} for s in run["plan"]],
            "results_so_far": [{"tool": e["tool"], "status": e["status"], "error": e["error"],
                                "output": json.dumps(e["output"], default=str)[:2000]}
                               for e in run["steps"] if e["plan_id"] is not None],
        }

    def _drive(self, run_id: int) -> dict:
        runs, config = self.app.runs, self.app.config
        runs.update(run_id, status="running", error=None)
        budget = {"calls": 0, "failures": 0}
        try:
            run = runs.get(run_id)
            allowed = (run["context"] or {}).get("allowed")
            if not run["plan"]:
                self._plan(run, budget, allowed)
            while True:
                for step in runs.get(run_id)["plan"]:
                    if step["status"] != "completed":
                        self._step(run_id, step, budget, allowed)
                if self._finish(run_id, budget, allowed):
                    break
        except _Halt as halt:
            runs.update(run_id, status=halt.status, error=halt.reason)
        except ProviderError as exc:
            runs.update(run_id, status="failed", error=f"The AI model failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - a bug here must not leave a run stuck as 'running'
            log.exception("Engine error in run %s", run_id)
            runs.update(run_id, status="failed", error=f"Internal engine error: {type(exc).__name__}: {exc}")
        final = runs.get(run_id)
        self.app.events.record("engine", f"run.{final['status']}",
                               f"Goal run #{run_id} {final['status']}" + (f": {final['error']}" if final["error"] else ""),
                               level="info" if final["status"] in ("completed", "waiting_approval", "blocked") else "warning",
                               details={"run_id": run_id})
        if final["status"] in ("completed", "failed"):
            self._remember(final)
        return self.report(run_id)

    def _plan(self, run: dict, budget: dict, allowed) -> None:
        names = {tool["name"] for tool in self._tools(allowed)}
        limit = self.app.config.engine_max_steps

        def check(reply: dict) -> dict:
            if _question(reply):
                return reply
            plan = reply.get("plan")
            if not isinstance(plan, list) or not plan:
                raise ValueError('expected {"plan": [...]} with at least one step')
            self._check_steps(plan, names, limit)
            return reply

        reply = self._ask("PLAN", self._state(run), check, budget, allowed)
        if _question(reply):
            raise _Halt("blocked", _question(reply))
        self.app.runs.set_plan(run["id"], [{"description": item["description"].strip()[:500], "tool": item["tool"]}
                                           for item in reply["plan"]])

    @staticmethod
    def _check_steps(steps: list, names: set, limit: int) -> None:
        if len(steps) > limit:
            raise ValueError(f"the plan has {len(steps)} steps; the limit is {limit}")
        for number, item in enumerate(steps, 1):
            if not isinstance(item, dict) or not isinstance(item.get("description"), str) \
                    or not item["description"].strip():
                raise ValueError(f"step {number} needs a description")
            if item.get("tool") not in names:
                raise ValueError(f"step {number} uses '{item.get('tool')}', which is not an available tool")

    def _step(self, run_id: int, step: dict, budget: dict, allowed) -> None:
        runs, tool = self.app.runs, self.app.tools.get(step["tool"])

        if step["status"] == "blocked" and step["approval_id"]:      # resuming after an approval request
            self.app.safety.list_approvals()                           # expires stale approvals
            approval = self.app.safety.get_approval(step["approval_id"])
            if approval["status"] == "pending":
                raise _Halt("waiting_approval", f"Approval #{approval['id']} is still undecided: {approval['summary']}")
            if approval["status"] != "approved":
                runs.update_plan_step(step["id"], status="failed", note=f"Approval #{approval['id']} was not granted")
                raise _Halt("failed", f"Approval #{approval['id']} was {approval['status']}, so step "
                                      f"{step['position']} was not carried out")
            return self._execute(run_id, step, step["inputs"], budget, allowed, approval["id"])

        problem = None
        for attempt in range(1, ATTEMPTS_PER_STEP + 1):
            def check(reply: dict) -> dict:
                if _question(reply):
                    return reply
                if not isinstance(reply.get("inputs"), dict):
                    raise ValueError('expected {"inputs": {...}}')
                return {"inputs": ToolRegistry.validate(tool, reply["inputs"])}

            state = self._state(runs.get(run_id))
            reply = self._ask("ACTION", {**state, "step": {"position": step["position"],
                                                           "description": step["description"], "tool": tool.spec()},
                                         "previous_attempt_failed_with": problem}, check, budget, allowed)
            if _question(reply):
                runs.update_plan_step(step["id"], status="blocked", note=_question(reply))
                raise _Halt("blocked", _question(reply))
            problem = self._execute(run_id, step, reply["inputs"], budget, allowed, None,
                                    last_attempt=attempt == ATTEMPTS_PER_STEP)
            if problem is None:
                return

    def _execute(self, run_id, step, inputs, budget, allowed, approval_id, last_attempt=True) -> str | None:
        """Run one planned step. Returns None on success, or the error to retry with."""
        runs = self.app.runs
        attempts = runs.get(run_id)["plan"][step["position"] - 1]["attempts"] + 1
        runs.update_plan_step(step["id"], status="running", inputs=inputs, attempts=attempts)
        result = self.app.tools.execute(step["tool"], inputs, actor=ENGINE_ACTOR, run_id=run_id, allowed=allowed,
                                        approval_id=approval_id, plan_id=step["id"])
        if result["ok"]:
            runs.update_plan_step(step["id"], status="completed", note=None)
            return None
        if result["status"] == "approval_required":
            runs.update_plan_step(step["id"], status="blocked", approval_id=result["approval"]["id"],
                                  note="Waiting for approval")
            raise _Halt("waiting_approval", f"Step {step['position']} ({step['tool']}) needs your approval "
                                            f"(#{result['approval']['id']})")
        if result["status"] == "refused":
            runs.update_plan_step(step["id"], status="failed", note=result["error"])
            raise _Halt("failed", f"Step {step['position']} ({step['tool']}) was refused: {result['error']}")
        budget["failures"] += 1
        over = budget["failures"] >= self.app.config.engine_max_failures
        if last_attempt or over:
            runs.update_plan_step(step["id"], status="failed", note=result["error"])
            why = f"the limit of {self.app.config.engine_max_failures} tool failures was reached" if over \
                else f"it failed {attempts} time(s)"
            raise _Halt("failed", f"Step {step['position']} ({step['tool']}) failed and {why}: {result['error']}")
        runs.update_plan_step(step["id"], status="pending", note=result["error"])
        return result["error"]

    def _finish(self, run_id: int, budget: dict, allowed) -> None:
        run = self.app.runs.get(run_id)
        proven = {e["plan_id"] for e in run["steps"] if e["status"] == "succeeded"}
        unproven = [s["position"] for s in run["plan"] if s["status"] != "completed" or s["id"] not in proven]
        if not run["plan"] or unproven:
            raise _Halt("failed", f"Completion could not be verified for step(s) {unproven}")

        # Every step ran. Now check the GOAL was achieved, not just the plan.
        names = {tool["name"] for tool in self._tools(allowed)}
        room = self.app.config.engine_max_steps - len(run["plan"])
        context = run["context"] or {}

        def check(reply: dict) -> dict:
            if reply.get("achieved") is True:
                return reply
            if reply.get("achieved") is not False:
                raise ValueError('expected {"achieved": true, ...} or {"achieved": false, ...}')
            if not isinstance(reply.get("missing"), str) or not reply["missing"].strip():
                raise ValueError('when "achieved" is false, say what is "missing"')
            steps = reply.get("next_steps") or []
            if not isinstance(steps, list):
                raise ValueError('"next_steps" must be a list')
            if steps:
                self._check_steps(steps, names, max(room, 0))
            return reply

        try:
            review = self._ask("REVIEW", self._state(run), check, budget, allowed)
        except _Halt as halt:
            if "model calls" in halt.reason:
                raise
            raise _Halt("failed", "Every planned step succeeded, but the model could not confirm the goal was "
                                  "achieved, so it is not reported as complete") from None
        if review["achieved"]:
            summary = review.get("summary")
            summary = summary.strip()[:1000] if isinstance(summary, str) and summary.strip() else None
            self.app.runs.update(run_id, status="completed", error=None, result={"model_summary": summary})
            return True
        missing, extra = review["missing"].strip()[:500], review.get("next_steps") or []
        if extra and not context.get("extended"):        # one chance to add the missing steps
            self.app.runs.append_plan(run_id, [{"description": item["description"].strip()[:500],
                                                "tool": item["tool"]} for item in extra])
            self.app.runs.update(run_id, context={**context, "extended": True})
            return False
        raise _Halt("failed", f"The planned steps ran, but the goal was not achieved: {missing}")

    def _remember(self, run: dict) -> None:
        """Record the outcome as an experience, once, and only if it is new."""
        if not any(e["plan_id"] is not None for e in run["steps"]):
            return                                      # nothing was attempted, nothing to learn
        success = run["status"] == "completed"
        title = f"Goal {'completed' if success else 'failed'}: {run['goal']}"[:300]
        outcome = "success" if success else "failure"
        if any(item["title"] == title and item["outcome"] == outcome
               for item in self.app.experiences.list(query=run["goal"][:80], limit=50)):
            return
        steps = "; ".join(f"{s['position']}. {s['description']} [{s['status']}]" for s in run["plan"])
        self.app.tools.execute("experience.record", {
            "title": title, "outcome": outcome, "category": "run",
            "description": f"Run #{run['id']}. Steps: {steps}." + ("" if success else f" Error: {run['error']}"),
        }, actor=ENGINE_ACTOR, run_id=run["id"])
