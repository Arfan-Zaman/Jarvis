"""Runtime settings stored in the database as JSON values.

Static configuration (ports, paths, provider choice) lives in `.env`; see
`jarvis.config`. This store is for preferences that change while running.
"""

from __future__ import annotations

import json

from ..common import ValidationError, utcnow
from ..db import Database


class SettingsStore:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default=None):
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value, *, category: str = "general", source: str = "user") -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("setting key is required")
        try:
            encoded = json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("setting value must be JSON-serialisable") from exc
        now = utcnow()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, category, source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, category = excluded.category, "
                "source = excluded.source, updated_at = excluded.updated_at",
                (key.strip(), encoded, category, source, now, now),
            )

    def delete(self, key: str) -> bool:
        with self.db.connect() as conn:
            return conn.execute("DELETE FROM settings WHERE key = ?", (key,)).rowcount > 0

    def all(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM settings ORDER BY key").fetchall()
        return [{**dict(row), "value": json.loads(row["value"])} for row in rows]
