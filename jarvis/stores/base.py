"""Generic record store shared by memories, tasks, projects, experiences, agents
and conversations.

Table and column names are class-level constants, never user input, so they
are safe to interpolate into SQL. All values are bound as parameters.
"""

from __future__ import annotations

import sqlite3

from ..common import (
    NotFoundError,
    ValidationError,
    VERIFICATION_STATUSES,
    choice,
    confidence,
    text,
    utcnow,
)
from ..db import Database

# Metadata carried by every stored knowledge item.
META_FIELDS = {
    "source": text("source", required=True, max_len=200),
    "confidence": confidence,
    "verification_status": choice("verification_status", VERIFICATION_STATUSES),
    "category": text("category", required=True, max_len=100),
}
META_DEFAULTS = {
    "source": "user",
    "confidence": 1.0,
    "verification_status": "unverified",
    "category": "general",
}


class Store:
    table = ""
    label = "record"
    fields: dict = {}              # field name -> validator
    defaults: dict = {}
    search_columns: tuple = ()
    filterable: tuple = ("category", "source", "verification_status")
    order_by = "id DESC"

    def __init__(self, db: Database):
        self.db = db

    # --- helpers -----------------------------------------------------------
    def _all_fields(self) -> dict:
        return {**self.fields, **META_FIELDS}

    def _prepare(self, cleaned: dict, existing: dict | None) -> dict:
        """Hook for cross-field rules. `existing` is None on create."""
        return cleaned

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["is_active"] = bool(data["is_active"])
        return data

    def _integrity(self, exc: sqlite3.IntegrityError) -> ValidationError:
        message = str(exc)
        if "UNIQUE" in message:
            return ValidationError(f"A {self.label} with that name already exists")
        if "FOREIGN KEY" in message:
            return ValidationError(f"The {self.label} refers to a record that does not exist")
        return ValidationError(f"The {self.label} was rejected by the database: {message}")

    # --- create / read -----------------------------------------------------
    def create(self, data: dict) -> dict:
        fields = self._all_fields()
        unknown = sorted(set(data) - set(fields))
        if unknown:
            raise ValidationError(f"Unknown field(s) for {self.label}: {', '.join(unknown)}")
        merged = {**META_DEFAULTS, **self.defaults, **data}
        cleaned = {name: validate(merged.get(name)) for name, validate in fields.items()}
        cleaned = self._prepare(cleaned, None)
        now = utcnow()
        cleaned["created_at"] = cleaned["updated_at"] = now
        columns = ", ".join(cleaned)
        marks = ", ".join("?" for _ in cleaned)
        try:
            with self.db.connect() as conn:
                cursor = conn.execute(
                    f"INSERT INTO {self.table} ({columns}) VALUES ({marks})", list(cleaned.values())
                )
                new_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise self._integrity(exc) from exc
        return self.get(new_id)

    def get(self, record_id: int) -> dict:
        with self.db.connect() as conn:
            row = conn.execute(f"SELECT * FROM {self.table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"{self.label.capitalize()} {record_id} not found")
        return self._row(row)

    def _where(self, active, query, filters) -> tuple[str, list]:
        clauses, params = [], []
        if active is not None:
            clauses.append("is_active = ?")
            params.append(1 if active else 0)
        for name, value in filters.items():
            if name not in self.filterable:
                raise ValidationError(f"Cannot filter {self.label}s by {name}")
            if value is None:
                continue
            clauses.append(f"{name} = ?")
            params.append(value)
        if query and self.search_columns:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(
                "(" + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in self.search_columns) + ")"
            )
            params.extend([f"%{escaped}%"] * len(self.search_columns))
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def list(self, active: bool | None = True, query: str | None = None,
             limit: int = 200, offset: int = 0, **filters) -> list[dict]:
        """List records. `active=None` returns archived records too."""
        where, params = self._where(active, query, filters)
        limit = max(1, min(int(limit), 1000))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.table}{where} ORDER BY {self.order_by} LIMIT ? OFFSET ?",
                [*params, limit, max(0, int(offset))],
            ).fetchall()
        return [self._row(row) for row in rows]

    def count(self, active: bool | None = True, **filters) -> int:
        where, params = self._where(active, None, filters)
        with self.db.connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {self.table}{where}", params).fetchone()[0]

    # --- update ------------------------------------------------------------
    def update(self, record_id: int, changes: dict) -> dict:
        existing = self.get(record_id)
        fields = self._all_fields()
        unknown = sorted(set(changes) - set(fields))
        if unknown:
            raise ValidationError(f"Unknown field(s) for {self.label}: {', '.join(unknown)}")
        cleaned = {name: fields[name](value) for name, value in changes.items()}
        cleaned = self._prepare(cleaned, existing)
        if not cleaned:
            return existing
        cleaned["updated_at"] = utcnow()
        assignments = ", ".join(f"{name} = ?" for name in cleaned)
        try:
            with self.db.connect() as conn:
                conn.execute(
                    f"UPDATE {self.table} SET {assignments} WHERE id = ?", [*cleaned.values(), record_id]
                )
        except sqlite3.IntegrityError as exc:
            raise self._integrity(exc) from exc
        return self.get(record_id)

    def _set_active(self, record_id: int, active: bool) -> dict:
        self.get(record_id)
        now = utcnow()
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE {self.table} SET is_active = ?, archived_at = ?, updated_at = ? WHERE id = ?",
                (1 if active else 0, None if active else now, now, record_id),
            )
        return self.get(record_id)

    def archive(self, record_id: int) -> dict:
        """Soft delete: hide the record but keep it recoverable."""
        return self._set_active(record_id, False)

    def restore(self, record_id: int) -> dict:
        return self._set_active(record_id, True)

    def delete(self, record_id: int) -> None:
        """Permanent delete. Callers must go through the safety layer first."""
        with self.db.connect() as conn:
            cursor = conn.execute(f"DELETE FROM {self.table} WHERE id = ?", (record_id,))
        if cursor.rowcount == 0:
            raise NotFoundError(f"{self.label.capitalize()} {record_id} not found")
