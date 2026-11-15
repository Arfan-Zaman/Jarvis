"""Shared test helpers. Every test gets its own throwaway database."""

from __future__ import annotations

import os
os.environ.setdefault("JARVIS_BRAIN", "local")      # tests never call the real Claude
os.environ.setdefault("JARVIS_EMBED_MODEL", "no-embeddings-in-tests")   # nor the real embedding model

import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jarvis.config import load_config
from jarvis.orchestrator import Jarvis

# Keep test output quiet: JARVIS logs go nowhere during tests.
_logger = logging.getLogger("jarvis")
_logger.addHandler(logging.NullHandler())
_logger.propagate = False


def make_config(root: Path, **overrides):
    """A config rooted in `root` that ignores the real environment and .env."""
    environ = {f"JARVIS_{key.upper()}": str(value) for key, value in overrides.items()}
    return load_config(root=root, env_file=root / "no-such.env", environ=environ)


class JarvisTestCase(unittest.TestCase):
    overrides: dict = {}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.app = self.make_app(**self.overrides)

    def make_app(self, provider=None, **overrides) -> Jarvis:
        return Jarvis(make_config(self.root, **overrides), provider=provider).start()

    def sql(self, statement: str, params=()):
        conn = sqlite3.connect(self.app.config.db_path)
        try:
            rows = conn.execute(statement, params).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def approved_delete(self, kind: str, record_id: int) -> dict:
        """Run the full two-step destructive flow as the human would."""
        request = self.app.delete(kind, record_id)
        self.assertEqual(request["status"], "approval_required")
        self.app.safety.approve(request["approval"]["id"])
        return self.app.delete(kind, record_id, approval_id=request["approval"]["id"])
