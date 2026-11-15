import sqlite3
import unittest

from jarvis.db import REQUIRED_TABLES, SCHEMA_VERSION, Database
from support import JarvisTestCase

KNOWLEDGE_TABLES = ("memories", "experiences", "tasks", "projects", "agents", "conversations")
METADATA_COLUMNS = {"created_at", "updated_at", "source", "confidence",
                    "verification_status", "category", "is_active", "archived_at"}


class DatabaseInitTests(JarvisTestCase):
    def test_all_required_tables_exist(self):
        tables = set(self.app.db.tables())
        for table in ("memories", "experiences", "tasks", "projects", "agents",
                      "conversations", "system_events", "settings"):
            self.assertIn(table, tables)
        self.assertTrue(set(REQUIRED_TABLES) <= tables)

    def test_schema_version_and_integrity(self):
        self.assertEqual(self.app.db.version(), SCHEMA_VERSION)
        self.assertTrue(self.app.db.integrity_ok())

    def test_knowledge_tables_carry_metadata(self):
        for table in KNOWLEDGE_TABLES:
            columns = {row[1] for row in self.sql(f"PRAGMA table_info({table})")}
            self.assertTrue(METADATA_COLUMNS <= columns, f"{table} is missing {METADATA_COLUMNS - columns}")

    def test_initialize_is_idempotent(self):
        self.app.create("memories", {"content": "survives a restart"})
        again = self.make_app()
        self.assertEqual(again.db.version(), SCHEMA_VERSION)
        self.assertEqual([m["content"] for m in again.list("memories")], ["survives a restart"])

    def test_foreign_keys_are_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.app.db.connect() as conn:
                conn.execute(
                    "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (999, 'user', 'x', 'now')")

    def test_failed_transaction_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with self.app.db.connect() as conn:
                conn.execute("INSERT INTO settings (key, value, created_at, updated_at) VALUES ('k', '1', 'n', 'n')")
                raise RuntimeError("boom")
        self.assertIsNone(self.app.settings.get("k"))

    def test_refuses_database_from_a_newer_version(self):
        self.sql(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        with self.assertRaises(RuntimeError):
            Database(self.app.config.db_path).initialize()


class SeedTests(JarvisTestCase):
    def test_only_the_two_initial_projects_exist(self):
        projects = self.app.list("projects")
        self.assertEqual(sorted(p["name"] for p in projects), ["Aureus Detailing", "Monsoor Motors"])
        for project in projects:
            self.assertEqual(project["description"], "Business workspace.")
            self.assertEqual(project["category"], "business")
            self.assertEqual(project["verification_status"], "user_provided")

    def test_no_other_knowledge_is_invented(self):
        self.assertEqual(self.app.list("memories"), [])
        self.assertEqual(self.app.list("experiences"), [])
        self.assertEqual(self.app.list("tasks"), [])
        self.assertEqual([a["name"] for a in self.app.agents.list()], ["jarvis-core"])

    def test_seeding_happens_once(self):
        monsoor = self.app.projects.get_by_name("Monsoor Motors")
        self.approved_delete("projects", monsoor["id"])
        restarted = self.make_app()
        self.assertEqual([p["name"] for p in restarted.list("projects")], ["Aureus Detailing"])


if __name__ == "__main__":
    unittest.main()
