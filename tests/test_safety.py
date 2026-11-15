import unittest

from jarvis.common import PermissionDenied
from jarvis.safety import ActionCategory
from support import JarvisTestCase

HIGH_IMPACT = (ActionCategory.DESTRUCTIVE, ActionCategory.EXTERNAL_COMMUNICATION,
               ActionCategory.FINANCIAL, ActionCategory.SYSTEM)


class SafetyTests(JarvisTestCase):
    def audit(self):
        return self.app.events.list(category="audit")

    def request(self, category=ActionCategory.DESTRUCTIVE, details=None, action="thing.do"):
        return self.app.safety.authorize(action, category, "Do the thing", details=details or {"id": 1})

    # --- read / write ------------------------------------------------------
    def test_reads_are_allowed(self):
        self.assertTrue(self.app.safety.authorize("memory.read", ActionCategory.READ, "Read").allowed)

    def test_writes_are_allowed_and_audited(self):
        self.app.create("memories", {"content": "audited"})
        self.assertIn("memory.create", [event["action"] for event in self.audit()])

    def test_unknown_category_is_refused(self):
        with self.assertRaises(PermissionDenied):
            self.app.safety.authorize("x", "teleport", "?")
        self.assertEqual(self.audit()[0]["level"], "warning")

    # --- approvals ---------------------------------------------------------
    def test_every_high_impact_category_needs_approval(self):
        for category in HIGH_IMPACT:
            with self.subTest(category=category.value):
                decision = self.request(category)
                self.assertFalse(decision.allowed)
                self.assertTrue(decision.requires_approval)
                self.assertEqual(decision.approval["status"], "pending")
                self.assertEqual(decision.approval["category"], category.value)

    def test_financial_and_external_actions_never_run_silently(self):
        for category in (ActionCategory.FINANCIAL, ActionCategory.EXTERNAL_COMMUNICATION):
            with self.subTest(category=category.value):
                self.assertFalse(self.request(category, action="payment.send").allowed)

    def test_unapproved_approval_cannot_be_used(self):
        pending = self.request().approval
        with self.assertRaises(PermissionDenied):
            self.app.safety.authorize("thing.do", ActionCategory.DESTRUCTIVE, "Do the thing",
                                      details={"id": 1}, approval_id=pending["id"])

    def test_approved_action_is_allowed_exactly_once(self):
        approval = self.request().approval
        self.app.safety.approve(approval["id"])
        again = lambda: self.app.safety.authorize("thing.do", ActionCategory.DESTRUCTIVE, "Do the thing",
                                                  details={"id": 1}, approval_id=approval["id"])
        self.assertTrue(again().allowed)
        self.assertEqual(self.app.safety.get_approval(approval["id"])["status"], "used")
        with self.assertRaises(PermissionDenied):
            again()

    def test_approval_is_bound_to_the_exact_action(self):
        approval = self.request(details={"id": 1}).approval
        self.app.safety.approve(approval["id"])
        with self.assertRaises(PermissionDenied):  # different target
            self.app.safety.authorize("thing.do", ActionCategory.DESTRUCTIVE, "Do the thing",
                                      details={"id": 2}, approval_id=approval["id"])
        with self.assertRaises(PermissionDenied):  # different action
            self.app.safety.authorize("other.do", ActionCategory.DESTRUCTIVE, "Do the thing",
                                      details={"id": 1}, approval_id=approval["id"])
        # The mismatched attempts did not burn the approval.
        self.assertEqual(self.app.safety.get_approval(approval["id"])["status"], "approved")

    def test_denied_approval_blocks_the_action(self):
        approval = self.request().approval
        self.app.safety.deny(approval["id"])
        with self.assertRaises(PermissionDenied):
            self.app.safety.authorize("thing.do", ActionCategory.DESTRUCTIVE, "Do the thing",
                                      details={"id": 1}, approval_id=approval["id"])
        with self.assertRaises(PermissionDenied):  # a decision is final
            self.app.safety.approve(approval["id"])

    def test_expired_approval_blocks_the_action(self):
        approval = self.request().approval
        self.app.safety.approve(approval["id"])
        self.sql("UPDATE approvals SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (approval["id"],))
        with self.assertRaises(PermissionDenied):
            self.app.safety.authorize("thing.do", ActionCategory.DESTRUCTIVE, "Do the thing",
                                      details={"id": 1}, approval_id=approval["id"])
        self.assertEqual(self.app.safety.list_approvals("pending"), [])

    def test_missing_approval_is_refused(self):
        with self.assertRaises(PermissionDenied):
            self.app.safety.authorize("thing.do", ActionCategory.DESTRUCTIVE, "Do the thing",
                                      details={"id": 1}, approval_id=987)

    def test_only_the_human_can_decide(self):
        approval = self.request().approval
        for decide in (self.app.safety.approve, self.app.safety.deny):
            with self.assertRaises(PermissionDenied):
                decide(approval["id"], decided_by="agent:helper")
        self.assertEqual(self.app.safety.get_approval(approval["id"])["status"], "pending")

    def test_approval_lifecycle_is_audited(self):
        approval = self.request().approval
        self.app.safety.approve(approval["id"])
        self.app.safety.authorize("thing.do", ActionCategory.DESTRUCTIVE, "Do the thing",
                                  details={"id": 1}, approval_id=approval["id"])
        messages = " | ".join(event["message"] for event in self.audit())
        self.assertIn("requested", messages)
        self.assertIn("approved by user", messages)
        self.assertIn("Authorised with approval", messages)

    def test_events_cannot_be_edited_or_removed_through_the_api(self):
        self.assertFalse(hasattr(self.app.events, "delete"))
        self.assertFalse(hasattr(self.app.events, "update"))

    # --- file-system permissions ------------------------------------------
    def test_path_permissions(self):
        safety, config = self.app.safety, self.app.config
        inside = config.data_dir / "notes.txt"
        self.assertEqual(safety.authorize_path(inside, write=True), inside)
        self.assertEqual(safety.authorize_path(config.root / "README.md", write=False), config.root / "README.md")
        with self.assertRaises(PermissionDenied):  # project files are read-only
            safety.authorize_path(config.root / "README.md", write=True)
        for outside in ("/etc/hosts", config.data_dir / ".." / ".." / "escape.txt", "~/Documents/x.txt"):
            for write in (True, False):
                with self.subTest(path=str(outside), write=write), self.assertRaises(PermissionDenied):
                    safety.authorize_path(outside, write=write)

    def test_symlink_cannot_escape_the_data_dir(self):
        link = self.app.config.data_dir / "link"
        link.symlink_to("/etc")
        with self.assertRaises(PermissionDenied):
            self.app.safety.authorize_path(link / "hosts", write=True)


class ReadOnlyModeTests(JarvisTestCase):
    def test_read_only_mode_refuses_all_changes(self):
        memory = self.app.create("memories", {"content": "written before lockdown"})
        locked = self.make_app(allow_writes="false")
        self.assertEqual(len(locked.list("memories")), 1)  # reading still works
        blocked = (
            lambda: locked.create("memories", {"content": "nope"}),
            lambda: locked.update("memories", memory["id"], {"content": "nope"}),
            lambda: locked.archive("memories", memory["id"]),
            lambda: locked.delete("memories", memory["id"]),
            lambda: locked.complete_task(1),
            lambda: locked.chat("hello"),
            lambda: locked.create_backup(),
            lambda: locked.safety.authorize_path(locked.config.data_dir / "x", write=True),
        )
        for attempt in blocked:
            with self.assertRaises(PermissionDenied):
                attempt()
        self.assertEqual(locked.get("memories", memory["id"])["content"], "written before lockdown")
        self.assertTrue(locked.status()["safety"]["read_only"])


if __name__ == "__main__":
    unittest.main()
