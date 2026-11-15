"""Run log: a durable record of every tool execution.

A *run* is one piece of work; a *step* is one tool call inside it. Steps are
never edited after they are written, so the log shows what actually happened.
"""

from __future__ import annotations

import json

from ..common import NotFoundError, utcnow
from ..db import Database

RUN_STATUSES = ("running", "waiting_approval", "blocked", "completed", "failed", "cancelled", "interrupted")
OPEN_STATUSES = ("running", "waiting_approval", "blocked")
PLAN_STATUSES = ("pending", "running", "completed", "failed", "blocked")
MAX_STORED_CHARS = 100_000


def _encode(value) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, default=str, sort_keys=True)
    if len(encoded) > MAX_STORED_CHARS:
        encoded = json.dumps({"truncated": True, "preview": encoded[:MAX_STORED_CHARS]})
    return encoded


def _decode(row, *fields) -> dict:
    data = dict(row)
    for name in fields:
        data[name] = json.loads(data[name]) if data[name] else None
    return data


class RunStore:
    def __init__(self, db: Database):
        self.db = db

    def create(self, goal: str, *, kind: str = "tool", actor: str = "user", agent_id: int | None = None) -> dict:
        now = utcnow()
        with self.db.connect() as conn:
            run_id = conn.execute(
                "INSERT INTO runs (kind, goal, actor, agent_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?)", (kind, goal, actor, agent_id, now, now)).lastrowid
        return self.get(run_id, with_steps=False)

    def set_status(self, run_id: int, status: str, *, result=None, error: str | None = None) -> dict:
        if status not in RUN_STATUSES:
            raise ValueError(f"unknown run status: {status}")
        now = utcnow()
        finished = None if status in OPEN_STATUSES else now
        with self.db.connect() as conn:
            changed = conn.execute(
                "UPDATE runs SET status = ?, result = ?, error = ?, updated_at = ?, finished_at = ? WHERE id = ?",
                (status, _encode(result), error, now, finished, run_id)).rowcount
        if not changed:
            raise NotFoundError(f"Run {run_id} not found")
        return self.get(run_id, with_steps=False)

    def add_step(self, run_id: int, *, tool: str, category: str | None, actor: str, inputs, output,
                 error: str | None, status: str, approval_id: int | None, started_at: str,
                 duration_ms: int, plan_id: int | None = None) -> dict:
        now = utcnow()
        with self.db.connect() as conn:
            position = conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM run_steps WHERE run_id = ?", (run_id,)).fetchone()[0]
            step_id = conn.execute(
                "INSERT INTO run_steps (run_id, position, tool, category, actor, input, output, error, status, "
                "approval_id, started_at, finished_at, duration_ms, plan_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, position, tool, category, actor, _encode(inputs), _encode(output), error, status,
                 approval_id, started_at, now, duration_ms, plan_id)).lastrowid
            conn.execute("UPDATE runs SET updated_at = ? WHERE id = ?", (now, run_id))
            row = conn.execute("SELECT * FROM run_steps WHERE id = ?", (step_id,)).fetchone()
        return _decode(row, "input", "output")

    def get(self, run_id: int, with_steps: bool = True) -> dict:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"Run {run_id} not found")
            run = _decode(row, "result", "context")
            if with_steps:
                plan = conn.execute("SELECT * FROM run_plan WHERE run_id = ? ORDER BY position", (run_id,)).fetchall()
                run["plan"] = [_decode(item, "inputs") for item in plan]
                steps = conn.execute(
                    "SELECT * FROM run_steps WHERE run_id = ? ORDER BY position", (run_id,)).fetchall()
                run["steps"] = [_decode(step, "input", "output") for step in steps]
        return run

    def list(self, limit: int = 50, status: str | None = None, kind: str | None = None) -> list[dict]:
        clauses, params = [], []
        for column, value in (("status", status), ("kind", kind)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.db.connect() as conn:
            rows = conn.execute(f"SELECT * FROM runs{where} ORDER BY id DESC LIMIT ?",
                                [*params, max(1, min(int(limit), 500))]).fetchall()
        return [_decode(row, "result", "context") for row in rows]

    def history(self, limit: int = 50, tool: str | None = None, status: str | None = None) -> list[dict]:
        """Tool executions, newest first, across all runs."""
        clauses, params = [], []
        if tool:
            clauses.append("tool = ?")
            params.append(tool)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.db.connect() as conn:
            rows = conn.execute(f"SELECT * FROM run_steps{where} ORDER BY id DESC LIMIT ?",
                                [*params, max(1, min(int(limit), 500))]).fetchall()
        return [_decode(row, "input", "output") for row in rows]

    # --- goal runs: context and plan ---------------------------------------
    def update(self, run_id: int, *, status: str | None = None, error=..., result=..., context=...) -> None:
        """Change selected fields of a run; anything not passed is left alone."""
        now = utcnow()
        fields = {"updated_at": now}
        if status is not None:
            if status not in RUN_STATUSES:
                raise ValueError(f"unknown run status: {status}")
            fields["status"] = status
            fields["finished_at"] = None if status in OPEN_STATUSES else now
        if error is not ...:
            fields["error"] = error
        if result is not ...:
            fields["result"] = _encode(result)
        if context is not ...:
            fields["context"] = _encode(context)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(f'{name} = ?' for name in fields)} WHERE id = ?",
                         [*fields.values(), run_id])

    def set_plan(self, run_id: int, steps: list[dict]) -> None:
        now = utcnow()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM run_plan WHERE run_id = ?", (run_id,))
            conn.executemany(
                "INSERT INTO run_plan (run_id, position, description, tool, status, updated_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                [(run_id, number, step["description"], step["tool"], now) for number, step in enumerate(steps, 1)])

    def update_plan_step(self, plan_id: int, **fields) -> None:
        if "status" in fields and fields["status"] not in PLAN_STATUSES:
            raise ValueError(f"unknown plan status: {fields['status']}")
        if "inputs" in fields:
            fields["inputs"] = _encode(fields["inputs"])
        fields["updated_at"] = utcnow()
        with self.db.connect() as conn:
            conn.execute(f"UPDATE run_plan SET {', '.join(f'{name} = ?' for name in fields)} WHERE id = ?",
                         [*fields.values(), plan_id])

    def count_steps(self) -> int:
        with self.db.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM run_steps").fetchone()[0]

    def mark_interrupted(self) -> int:
        """Runs left 'running' by a crash or shutdown are flagged, not hidden."""
        now = utcnow()
        with self.db.connect() as conn:
            return conn.execute(
                "UPDATE runs SET status = 'interrupted', error = 'JARVIS stopped while this run was in progress', "
                "updated_at = ?, finished_at = ? WHERE status = 'running'", (now, now)).rowcount
