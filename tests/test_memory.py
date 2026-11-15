import unittest

from jarvis.common import NotFoundError, ValidationError
from support import JarvisTestCase


class MemoryTests(JarvisTestCase):
    def test_create_and_retrieve(self):
        created = self.app.create("memories", {
            "content": "  The workshop key is in the top drawer  ", "category": "premises",
            "source": "user:chat", "confidence": 0.8, "verification_status": "user_provided"})
        fetched = self.app.get("memories", created["id"])
        self.assertEqual(fetched["content"], "The workshop key is in the top drawer")
        self.assertEqual(fetched["category"], "premises")
        self.assertEqual(fetched["source"], "user:chat")
        self.assertEqual(fetched["confidence"], 0.8)
        self.assertEqual(fetched["verification_status"], "user_provided")
        self.assertTrue(fetched["is_active"])
        self.assertIsNone(fetched["archived_at"])
        self.assertTrue(fetched["created_at"])
        self.assertEqual(fetched["created_at"], fetched["updated_at"])

    def test_defaults_are_conservative(self):
        memory = self.app.create("memories", {"content": "note"})
        self.assertEqual(memory["verification_status"], "unverified")
        self.assertEqual(memory["source"], "user")
        self.assertEqual(memory["category"], "general")

    def test_validation(self):
        for bad in ({"content": "   "}, {}, {"content": "x", "confidence": 1.5},
                    {"content": "x", "confidence": "high"}, {"content": "x", "verification_status": "maybe"},
                    {"content": "x", "source": ""}, {"content": "x", "nonsense": 1},
                    {"content": "x", "project_id": 9999}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.app.create("memories", bad)
        self.assertEqual(self.app.list("memories"), [])

    def test_search_and_filter(self):
        project = self.app.projects.get_by_name("Monsoor Motors")
        self.app.create("memories", {"content": "Alpha note", "category": "a"})
        self.app.create("memories", {"content": "Beta 100% note", "category": "b", "project_id": project["id"]})
        self.assertEqual([m["content"] for m in self.app.list("memories", query="alpha")], ["Alpha note"])
        self.assertEqual([m["content"] for m in self.app.list("memories", category="b")], ["Beta 100% note"])
        self.assertEqual(len(self.app.list("memories", project_id=project["id"])), 1)
        # LIKE wildcards in the search text are treated literally.
        self.assertEqual(len(self.app.list("memories", query="100%")), 1)
        self.assertEqual(self.app.list("memories", query="%"), [self.app.list("memories", query="100%")[0]])
        with self.assertRaises(ValidationError):
            self.app.list("memories", content="x")

    def test_update_changes_timestamp_and_keeps_provenance(self):
        memory = self.app.create("memories", {"content": "old", "source": "user:chat"})
        updated = self.app.update("memories", memory["id"], {"content": "new", "verification_status": "verified"})
        self.assertEqual(updated["content"], "new")
        self.assertEqual(updated["verification_status"], "verified")
        self.assertEqual(updated["source"], "user:chat")
        self.assertEqual(updated["created_at"], memory["created_at"])
        self.assertGreaterEqual(updated["updated_at"], memory["updated_at"])

    def test_archive_hides_and_restore_returns(self):
        memory = self.app.create("memories", {"content": "keep me"})
        archived = self.app.archive("memories", memory["id"])
        self.assertFalse(archived["is_active"])
        self.assertTrue(archived["archived_at"])
        self.assertEqual(self.app.list("memories"), [])
        self.assertEqual(len(self.app.list("memories", active=None)), 1)
        self.assertEqual(len(self.app.list("memories", active=False)), 1)
        restored = self.app.restore("memories", memory["id"])
        self.assertTrue(restored["is_active"])
        self.assertIsNone(restored["archived_at"])
        self.assertEqual(len(self.app.list("memories")), 1)

    def test_delete_requires_approval(self):
        memory = self.app.create("memories", {"content": "delete me"})
        request = self.app.delete("memories", memory["id"])
        self.assertEqual(request["status"], "approval_required")
        # Nothing was deleted by merely asking.
        self.assertEqual(self.app.get("memories", memory["id"])["content"], "delete me")

    def test_delete_after_approval_removes_the_record(self):
        memory = self.app.create("memories", {"content": "delete me"})
        result = self.approved_delete("memories", memory["id"])
        self.assertEqual(result["status"], "deleted")
        with self.assertRaises(NotFoundError):
            self.app.get("memories", memory["id"])
        self.assertEqual(self.app.list("memories", active=None), [])

    def test_missing_memory(self):
        with self.assertRaises(NotFoundError):
            self.app.get("memories", 12345)
        with self.assertRaises(NotFoundError):
            self.app.delete("memories", 12345)
        with self.assertRaises(NotFoundError):
            self.app.archive("memories", 12345)

    def test_deleting_a_project_keeps_its_memories(self):
        project = self.app.create("projects", {"name": "Temp"})
        memory = self.app.create("memories", {"content": "linked", "project_id": project["id"]})
        self.approved_delete("projects", project["id"])
        self.assertIsNone(self.app.get("memories", memory["id"])["project_id"])


if __name__ == "__main__":
    unittest.main()
