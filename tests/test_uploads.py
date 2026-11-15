"""Uploads: files land only in workspace/uploads, with safe names, and nothing else can be attached."""

from pathlib import Path

from jarvis.common import ValidationError
from jarvis.uploads import check_refs, safe_name, save_upload
from support import JarvisTestCase


class UploadTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app()
        self.uploads = Path(self.app.config.workspace_dir) / "uploads"

    def test_names_cannot_escape_or_hide(self):
        self.assertEqual(safe_name("../../etc/passwd.txt"), "passwd.txt")
        self.assertEqual(safe_name("..\\..\\boot.ini.txt"), "boot-ini.txt")
        self.assertEqual(safe_name(".bashrc.txt"), "bashrc.txt")
        self.assertEqual(safe_name("My Photo (1).JPG"), "My-Photo-1.jpg")

    def test_unsafe_types_are_refused(self):
        for name in ("run.sh", "app.command", "evil.exe", "x.pkg", "noextension", "page.php"):
            with self.assertRaises(ValidationError, msg=name):
                safe_name(name)

    def test_saved_inside_uploads_and_never_overwritten(self):
        first = save_upload(self.app, "../../photo.png", b"\x89PNG data")
        self.assertTrue(first["path"].startswith("uploads/"))
        target = (Path(self.app.config.workspace_dir) / first["path"]).resolve()
        self.assertEqual(target.parent, self.uploads.resolve())
        self.assertEqual(target.read_bytes(), b"\x89PNG data")
        with self.assertRaises(ValidationError):
            save_upload(self.app, "empty.png", b"")

    def test_only_real_uploads_can_be_attached(self):
        saved = save_upload(self.app, "notes.txt", b"hello")
        self.assertEqual(check_refs(self.app, [saved["path"]]), [saved["path"]])
        for bad in ("uploads/../jarvis.db", "../data/jarvis.db", "/etc/passwd", "uploads/missing.txt",
                    "data/jarvis.db", "uploads/sub/x.txt"):
            with self.assertRaises(ValidationError, msg=bad):
                check_refs(self.app, [bad])

    def test_chat_records_the_attachment(self):
        saved = save_upload(self.app, "notes.txt", b"hello")
        with self.assertRaises(ValidationError):
            self.app.chat("look", attachments=["../secrets.txt"])
        result = self.app.chat("What is in this?", attachments=[saved["path"]])
        self.assertIn(f"[Attached: {saved['path']}]", result["user_message"]["content"])
