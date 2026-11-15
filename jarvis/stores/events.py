"""System events: the append-only, user-visible audit trail.

There is deliberately no update or delete here.
"""

from __future__ import annotations

import json

from ..common import utcnow
from ..db import Database
from ..logging_setup import get_logger

LEVELS = ("debug", "info", "warning", "error")
_log = get_logger("events")


class EventLog:
    def __init__(self, db: Database):
        self.db = db

    def record(self, category: str, action: str, message: str, *, level: str = "info",
               actor: str = "system", details: dict | None = None) -> dict:
        if level not in LEVELS:
            level = "info"
        event = {
            "created_at": utcnow(),
            "level": level,
            "category": category,
            "action": action,
            "message": message,
            "actor": actor,
            "details": json.dumps(details, default=str, sort_keys=True) if details else None,
        }
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO system_events (created_at, level, category, action, message, actor, details) "
                "VALUES (:created_at, :level, :category, :action, :message, :actor, :details)",
                event,
            )
            event["id"] = cursor.lastrowid
        _log.log({"debug": 10, "info": 20, "warning": 30, "error": 40}[level],
                 "[%s] %s (%s): %s", category, action, actor, message)
        event["details"] = details
        return event

    def list(self, limit: int = 100, category: str | None = None, level: str | None = None) -> list[dict]:
        clauses, params = [], []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if level:
            clauses.append("level = ?")
            params.append(level)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM system_events{where} ORDER BY id DESC LIMIT ?",
                [*params, max(1, min(int(limit), 1000))],
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["details"] = json.loads(event["details"]) if event["details"] else None
            events.append(event)
        return events

    def count(self) -> int:
        with self.db.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM system_events").fetchone()[0]
