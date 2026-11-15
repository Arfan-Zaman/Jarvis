"""Backup and recovery for the SQLite database.

Backups use SQLite's online backup API, so they are consistent even while
JARVIS is running. Restoring always takes a "pre-restore" backup first, so a
restore can itself be undone.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .common import NotFoundError, ValidationError
from .config import Config
from .db import REQUIRED_TABLES, Database
from .stores.events import EventLog

_NAME = re.compile(r"^jarvis-\d{8}-\d{6}-\d{6}-[a-z0-9-]+\.db$")


class BackupManager:
    def __init__(self, db: Database, config: Config, events: EventLog):
        self.db = db
        self.config = config
        self.events = events

    def _resolve(self, name: str) -> Path:
        """Map a backup file name to its path, refusing anything else."""
        if not isinstance(name, str) or not _NAME.match(name):
            raise ValidationError("Not a valid backup name")
        path = self.config.backup_dir / name
        if not path.is_file():
            raise NotFoundError(f"Backup {name} not found")
        return path

    @staticmethod
    def _describe(path: Path) -> dict:
        stat = path.stat()
        return {
            "name": path.name,
            "label": path.stem.split("-", 4)[4],
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        }

    def create(self, label: str = "manual", prune: bool = True) -> dict:
        label = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "manual"
        self.config.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        path = self.config.backup_dir / f"jarvis-{stamp}-{label}.db"
        source = sqlite3.connect(self.db.path, timeout=10)
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        if not self.verify(path):
            path.unlink(missing_ok=True)
            raise RuntimeError("Backup failed verification and was discarded")
        info = self._describe(path)
        self.events.record("backup", "backup.create", f"Backup created: {path.name}", details=info)
        if prune:
            self.prune()
        return info

    @staticmethod
    def verify(path: Path) -> bool:
        """True if the file is an intact JARVIS database."""
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    return False
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
        except sqlite3.Error:
            return False
        return set(REQUIRED_TABLES) <= tables

    def list(self) -> list[dict]:
        if not self.config.backup_dir.is_dir():
            return []
        paths = [path for path in self.config.backup_dir.iterdir() if _NAME.match(path.name)]
        return [self._describe(path) for path in sorted(paths, key=lambda item: item.name, reverse=True)]

    def prune(self) -> int:
        """Delete the oldest backups beyond the configured number to keep."""
        stale = self.list()[self.config.backup_keep:]
        for item in stale:
            (self.config.backup_dir / item["name"]).unlink(missing_ok=True)
        if stale:
            self.events.record("backup", "backup.prune", f"Pruned {len(stale)} old backup(s)")
        return len(stale)

    def restore(self, name: str) -> dict:
        """Replace the live database with a backup.

        The caller MUST have obtained approval from the safety layer first;
        use `Jarvis.restore_backup`, not this method directly.
        """
        path = self._resolve(name)
        if not self.verify(path):
            raise ValidationError(f"Backup {name} is damaged or is not a JARVIS database")
        # No pruning here: it could delete the very backup being restored.
        safety_copy = self.create("pre-restore", prune=False)
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        target = sqlite3.connect(self.db.path, timeout=10)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        self.db.initialize()  # upgrade the schema if the backup is older
        self.events.record("backup", "backup.restore", f"Database restored from {name}", level="warning",
                           details={"restored_from": name, "pre_restore_backup": safety_copy["name"]})
        return {"restored_from": name, "pre_restore_backup": safety_copy["name"]}
