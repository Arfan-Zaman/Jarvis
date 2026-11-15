import unittest

from jarvis.common import NotFoundError, PermissionDenied, ValidationError
from support import JarvisTestCase


class BackupTests(JarvisTestCase):
    overrides = {"backup_keep": 3}

    def restore(self, name):
        request = self.app.restore_backup(name)
        self.assertEqual(request["status"], "approval_required")
        self.app.safety.approve(request["approval"]["id"])
        return self.app.restore_backup(name, approval_id=request["approval"]["id"])

    def test_create_list_and_verify(self):
        info = self.app.create_backup("Before Change!")
        self.assertEqual(info["label"], "before-change")
        self.assertGreater(info["size_bytes"], 0)
        self.assertEqual([item["name"] for item in self.app.backups.list()], [info["name"]])
        self.assertTrue(self.app.backups.verify(self.app.config.backup_dir / info["name"]))
        self.assertEqual(self.app.status()["backups"]["latest"]["name"], info["name"])

    def test_damaged_file_fails_verification(self):
        junk = self.app.config.backup_dir / "junk.db"
        junk.parent.mkdir(parents=True, exist_ok=True)
        junk.write_bytes(b"this is not a database")
        self.assertFalse(self.app.backups.verify(junk))

    def test_old_backups_are_pruned(self):
        names = [self.app.create_backup(f"n{i}")["name"] for i in range(5)]
        self.assertEqual([item["name"] for item in self.app.backups.list()], names[:1:-1])

    def test_restore_requires_approval(self):
        info = self.app.create_backup()
        self.app.create("memories", {"content": "added after the backup"})
        self.assertEqual(self.app.restore_backup(info["name"])["status"], "approval_required")
        self.assertEqual(len(self.app.list("memories")), 1)  # nothing was restored

    def test_restore_round_trip(self):
        self.app.create("memories", {"content": "original"})
        info = self.app.create_backup("good")
        self.app.create("memories", {"content": "later change"})
        self.approved_delete("projects", self.app.projects.get_by_name("Monsoor Motors")["id"])

        result = self.restore(info["name"])
        self.assertEqual(result["status"], "restored")
        self.assertEqual([m["content"] for m in self.app.list("memories")], ["original"])
        self.assertIsNotNone(self.app.projects.get_by_name("Monsoor Motors"))
        self.assertTrue(self.app.db.integrity_ok())

        # The state from just before the restore was saved and can be brought back.
        self.assertIn("pre-restore", result["pre_restore_backup"])
        self.restore(result["pre_restore_backup"])
        self.assertEqual(sorted(m["content"] for m in self.app.list("memories")), ["later change", "original"])
        self.assertIsNone(self.app.projects.get_by_name("Monsoor Motors"))

    def test_restoring_the_oldest_backup_survives_pruning(self):
        oldest = self.app.create_backup("oldest")["name"]
        self.app.create_backup("b")
        self.app.create_backup("c")
        self.assertEqual(self.restore(oldest)["restored_from"], oldest)

    def test_invalid_or_missing_backup_names(self):
        for name in ("../../etc/passwd", "jarvis.db", "", None):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self.app.restore_backup(name)
        with self.assertRaises(NotFoundError):
            self.app.restore_backup("jarvis-20200101-000000-000000-gone.db")

    def test_unapproved_restore_is_refused(self):
        info = self.app.create_backup()
        request = self.app.restore_backup(info["name"])
        with self.assertRaises(PermissionDenied):
            self.app.restore_backup(info["name"], approval_id=request["approval"]["id"])


if __name__ == "__main__":
    unittest.main()
