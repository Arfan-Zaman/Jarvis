"""Skills: install from GitHub keeps only instructions; JARVIS uses the matching skill; installs are checked."""
from __future__ import annotations

import io
import tarfile
import unittest
from unittest import mock

from support import JarvisTestCase

from jarvis.tools import skills


def archive(files: dict) -> tarfile.TarFile:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        for name, text in files.items():
            body = text.encode()
            info = tarfile.TarInfo(f"repo-abc/{name}"); info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    data.seek(0)
    return tarfile.open(fileobj=data, mode="r:gz")


SKILL = "---\nname: car-photo-editor\ndescription: Edit car photos for dealership listings, backgrounds and lighting\n---\n# Steps\nUse soft light."


class SkillTests(JarvisTestCase):
    def test_install_keeps_instructions_and_leaves_scripts_out(self):
        app = self.make_app()
        files = {"skills/car/SKILL.md": SKILL, "skills/car/references/tips.md": "tips",
                 "skills/car/run.sh": "rm -rf ~", "skills/car/tool.py": "import os", "README.md": "repo"}
        with mock.patch.object(skills, "_download", return_value=archive(files)):
            out = skills.skills_install(app, {"source": "https://github.com/someone/repo/tree/main/skills/car"}, "t")
        [done] = out["skills"]
        self.assertEqual((done["name"], done["status"]), ("car-photo-editor", "installed"))
        self.assertEqual(sorted(done["files"]), ["SKILL.md", "references/tips.md"])
        self.assertEqual(sorted(done["left_out"]), ["run.sh", "tool.py"])
        self.assertFalse((skills.skills_dir(app) / "car-photo-editor" / "run.sh").exists())

    def test_the_matching_skill_is_used(self):
        app = self.make_app()
        with mock.patch.object(skills, "_download", return_value=archive({"SKILL.md": SKILL})):
            skills.skills_install(app, {"source": "someone/repo"}, "t")
        found = skills.relevant(app, "Can you edit these car photos for my dealership listings?")
        self.assertEqual(found["name"], "car-photo-editor")
        self.assertIn("Use soft light", found["instructions"])
        self.assertIsNone(skills.relevant(app, "What's the weather like?"))

    def test_installs_ask_first_and_reject_odd_names(self):
        app = self.make_app()
        listed = {t["name"]: t for t in app.tools.list()}
        for tool in ("skills.install", "system.install"):
            self.assertTrue(listed[tool]["requires_approval"])
        for bad in ("-e git+https://x", "pandas; rm -rf ~", "a b"):
            with self.assertRaises(Exception):
                skills.system_install(app, {"manager": "pip", "package": bad}, "t")
        with self.assertRaises(Exception):
            skills.skills_install(app, {"source": "https://evil.example/x"}, "t")


if __name__ == "__main__":
    unittest.main()
