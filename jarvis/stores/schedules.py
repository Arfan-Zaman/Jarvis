"""Reminders and recurring jobs, and the alerts they raise when they fire.

Times are stored as UTC ISO-8601 strings (the same format as `utcnow`), so
"what is due" is a plain string comparison. `recur` is JSON:
{"days": [0..6 (Monday = 0)], "time": "HH:MM"}, or NULL for a one-off.
"""

from __future__ import annotations

import json

from ..common import NotFoundError, ValidationError, utcnow
from ..db import Database

KINDS = ("reminder", "job")
STATUSES = ("active", "done", "cancelled")


def _row(row) -> dict:
    data = dict(row)
    data["recur"] = json.loads(data["recur"]) if data.get("recur") else None
    return data


class ScheduleStore:
    def __init__(self, db: Database):
        self.db = db

    def create(self, *, kind: str, text: str, next_at: str, recur: dict | None = None, when_text: str = "",
               conversation_id: int | None = None, source: str = "user") -> dict:
        if kind not in KINDS:
            raise ValidationError(f"kind must be one of: {', '.join(KINDS)}")
        text = (text or "").strip()
        if not text:
            raise ValidationError("say what the reminder or job is about")
        now = utcnow()
        with self.db.connect() as conn:
            new_id = conn.execute(
                "INSERT INTO schedules (kind, text, when_text, next_at, recur, conversation_id, source, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, text[:1000], when_text[:200], next_at, json.dumps(recur) if recur else None,
                 conversation_id, source, now, now)).lastrowid
        return self.get(new_id)

    def get(self, schedule_id: int) -> dict:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Reminder {schedule_id} not found")
        return _row(row)

    def list(self, status: str | None = "active", limit: int = 100) -> list[dict]:
        where, params = ("WHERE status = ?", [status]) if status else ("", [])
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM schedules {where} ORDER BY (next_at IS NULL), next_at, id LIMIT ?",
                [*params, max(1, min(int(limit), 500))]).fetchall()
        return [_row(r) for r in rows]

    def due(self, now_utc: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM schedules WHERE status = 'active' AND next_at IS NOT NULL "
                                "AND next_at <= ? ORDER BY next_at, id", (now_utc,)).fetchall()
        return [_row(r) for r in rows]

    def update(self, schedule_id: int, **changes) -> dict:
        allowed = {"next_at", "status", "fire_count", "last_fired_at", "last_result", "job_conversation_id"}
        if set(changes) - allowed:
            raise ValidationError(f"cannot change: {', '.join(sorted(set(changes) - allowed))}")
        if "status" in changes and changes["status"] not in STATUSES:
            raise ValidationError(f"status must be one of: {', '.join(STATUSES)}")
        sets = ", ".join(f"{name} = ?" for name in changes)
        with self.db.connect() as conn:
            changed = conn.execute(f"UPDATE schedules SET {sets}, updated_at = ? WHERE id = ?",
                                   [*changes.values(), utcnow(), schedule_id]).rowcount
        if not changed:
            raise NotFoundError(f"Reminder {schedule_id} not found")
        return self.get(schedule_id)

    def attach(self, schedule_id: int, conversation_id: int) -> None:
        """Remember the conversation a schedule was set in."""
        with self.db.connect() as conn:
            conn.execute("UPDATE schedules SET conversation_id = ? WHERE id = ?", (conversation_id, schedule_id))

    def count(self, status: str = "active") -> int:
        with self.db.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM schedules WHERE status = ?", (status,)).fetchone()[0]

    # --- alerts: what the JARVIS page should say out loud -------------------
    def add_alert(self, schedule_id: int, text: str, fired_at: str) -> dict:
        with self.db.connect() as conn:
            new_id = conn.execute("INSERT INTO schedule_alerts (schedule_id, text, fired_at) VALUES (?, ?, ?)",
                                  (schedule_id, text[:500], fired_at)).lastrowid
            row = conn.execute("SELECT * FROM schedule_alerts WHERE id = ?", (new_id,)).fetchone()
        return dict(row)

    def take_alerts(self, since_utc: str) -> list[dict]:
        """Alerts not yet delivered (and fired after `since_utc`), marked delivered as they are handed out."""
        now = utcnow()
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM schedule_alerts WHERE delivered_at IS NULL AND fired_at >= ? "
                                "ORDER BY id", (since_utc,)).fetchall()
            conn.execute("UPDATE schedule_alerts SET delivered_at = ? WHERE delivered_at IS NULL", (now,))
        return [dict(r) for r in rows]
