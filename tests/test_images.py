"""image.quote / image.generate: pictures on Higgsfield. Claude and Higgsfield are never run here."""

import json
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from jarvis.common import JarvisError
from jarvis.providers.scripted import ScriptedProvider
from jarvis.tools import images
from support import JarvisTestCase

PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeApp:
    class config:
        workspace_dir = None


def done(result, code=0):
    return subprocess.CompletedProcess([], code, stdout=json.dumps({"result": result, "is_error": False}), stderr="")


class ImageToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        FakeApp.config.workspace_dir = self.tmp.name
        self.bin = mock.patch.object(images, "claude_binary", return_value="/bin/claude")
        self.bin.start()

    def tearDown(self):
        self.bin.stop()
        self.tmp.cleanup()

    def runner(self, result):
        self.calls = []
        def run(cmd, **kw):
            self.calls.append((cmd, kw))
            return done(result)
        return run

    def flag(self, cmd, name):
        return cmd[cmd.index(name) + 1]

    def test_only_higgsfield_no_shell_no_files_no_other_mcp(self):
        run = self.runner('{"balance": 1200, "cost": 6, "plan": "plus"}')
        images.image_quote(FakeApp, {"prompt": "a red fox"}, "user", runner=run)
        cmd, kw = self.calls[0]
        self.assertEqual(json.loads(self.flag(cmd, "--mcp-config")),
                         {"mcpServers": {"higgsfield": {"type": "http", "url": "https://mcp.higgsfield.ai/mcp"}}})
        self.assertEqual(self.flag(cmd, "--allowedTools"), "mcp__higgsfield__balance,mcp__higgsfield__generate_image")
        blocked = self.flag(cmd, "--disallowedTools").split(",")
        for tool in ("Bash", "Write", "Edit", "Read", "WebFetch", "WebSearch", "Task"):
            self.assertIn(tool, blocked)
        for option in ("--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(option, cmd)
        self.assertEqual(self.flag(cmd, "--setting-sources"), "project")
        self.assertEqual(kw["cwd"], self.tmp.name)
        self.assertFalse(any(k.startswith("CLAUDE_CODE_") for k in kw["env"]))

    def test_quote_asks_for_cost_only_and_reports_it(self):
        run = self.runner('Here: {"balance": 1200, "cost": 6, "plan": "plus"}')
        out = images.image_quote(FakeApp, {"prompt": "a red fox", "aspect_ratio": "16:9"}, "user", runner=run)
        self.assertEqual((out["cost"], out["balance"], out["affordable"], out["model"]), (6, 1200, True, "gpt_image_2_6"))
        prompt = self.flag(self.calls[0][0], "-p")
        self.assertIn('"get_cost": true', prompt)
        self.assertIn('"aspect_ratio": "16:9"', prompt)
        self.assertNotIn('"use_unlim": true', prompt)

    def test_quote_without_a_cost_is_an_error(self):
        with self.assertRaises(JarvisError):
            images.image_quote(FakeApp, {"prompt": "x"}, "user", runner=self.runner('{"balance": 0}'))

    def test_generate_caps_the_cost_downloads_and_saves(self):
        run = self.runner('{"cost": 6, "job_id": "j1", "image_url": "https://cdn.example/a.png", "balance": 1194}')
        fetched = []
        def fetch(url):
            fetched.append(url)
            return PNG, "image/png"
        out = images.image_generate(FakeApp, {"prompt": "A red fox, at dusk!", "max_credits": 6}, "user",
                                    runner=run, fetch=fetch)
        cmd = self.calls[0][0]
        self.assertEqual(self.flag(cmd, "--allowedTools").split(","), images.GENERATE_TOOLS)
        prompt = self.flag(cmd, "-p")
        self.assertIn("at most 6 credits", prompt)
        self.assertIn('"use_unlim": false', prompt)
        self.assertIn('"model": "gpt_image_2_6"', prompt)
        self.assertIn('"quality": "high"', prompt)
        self.assertIn('"resolution": "2k"', prompt)
        self.assertEqual(fetched, ["https://cdn.example/a.png"])
        path = Path(out["path"])
        self.assertEqual(path.parent, Path(self.tmp.name) / "images")
        self.assertTrue(path.name.endswith("-a-red-fox-at-dusk.png"))
        self.assertEqual(path.read_bytes(), PNG)
        self.assertEqual((out["cost"], out["balance"], out["note"]), (6, 1194, None))
        self.assertEqual(out["file_url"], f"/api/files/images/{path.name}")

    def test_generate_flags_a_charge_above_the_approved_cost(self):
        run = self.runner('{"cost": 9, "image_url": "https://cdn.example/a.png", "balance": 1}')
        out = images.image_generate(FakeApp, {"prompt": "fox", "max_credits": 6}, "user", runner=run,
                                    fetch=lambda url: (PNG, "image/png"))
        self.assertIn("above the approved 6", out["note"])

    def test_generate_reports_higgsfield_refusal_and_bad_links(self):
        with self.assertRaisesRegex(JarvisError, "above the approved"):
            images.image_generate(FakeApp, {"prompt": "fox", "max_credits": 6}, "user",
                                  runner=self.runner('{"error": "cost 9 is above the approved 6"}'))
        with self.assertRaisesRegex(JarvisError, "downloading it failed"):
            images.image_generate(FakeApp, {"prompt": "fox", "max_credits": 6}, "user",
                                  runner=self.runner('{"cost": 6, "image_url": "http://plain/a.png"}'))

    def test_download_is_https_only(self):
        with mock.patch.object(urllib.request, "urlopen") as urlopen:
            with self.assertRaises(JarvisError):
                images.download("file:///etc/passwd")
            urlopen.assert_not_called()

    def test_slug(self):
        self.assertEqual(images.slug("A Red Fox, at dusk! In snow and more words"), "a-red-fox-at-dusk-in")
        self.assertEqual(images.slug("!!!"), "image")


def fake_higgsfield(app, prompt, allowed, runner):
    if allowed == images.QUOTE_TOOLS:
        return {"balance": 1200, "cost": 6, "plan": "plus"}
    return {"cost": 6, "job_id": "j1", "image_url": "https://cdn.example/a.png", "balance": 1194}


class ImageRegistryAndChatTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        patches = [mock.patch.object(images, "_ask_claude", side_effect=fake_higgsfield),
                   mock.patch.object(images, "download", return_value=(PNG, "image/png"))]
        self.ask, self.fetch = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def test_generate_always_needs_the_owners_approval_with_the_cost(self):
        result = self.app.tools.execute("image.generate", {"prompt": "fox", "max_credits": 6})
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(result["permission"], "financial")
        self.assertEqual(result["approval"]["details"]["inputs"]["max_credits"], 6)
        self.assertEqual(self.ask.call_count, 0)              # nothing ran, nothing spent
        quote = self.app.tools.execute("image.quote", {"prompt": "fox"})
        self.assertTrue(quote["ok"], quote)                   # pricing needs no approval

    def chat_app(self, router):
        self.app = self.make_app(provider=ScriptedProvider([router]))
        return self.app

    def test_chat_quotes_then_makes_the_picture_on_yes(self):
        app = self.chat_app({"mode": "image", "prompt": "a red fox at dusk", "aspect_ratio": "16:9"})
        first = app.chat("Jarvis, make me a picture of a red fox at dusk, wide")
        reply, cid = first["reply"], first["conversation"]["id"]
        self.assertIn("6 Higgsfield credits", reply["content"])
        self.assertIn("1200", reply["content"])
        self.assertEqual(self.ask.call_count, 1)              # only the quote so far
        self.fetch.assert_not_called()
        second = app.chat("yes", cid)["reply"]
        self.assertEqual(self.ask.call_count, 2)
        self.assertIn("6 credits, 1194 left", second["content"])
        saved = Path(second["content"].split("Saved to ")[1].strip())
        self.assertEqual(saved.parent, app.config.workspace_dir / "images")
        self.assertEqual(saved.read_bytes(), PNG)
        self.assertEqual(app.runs.get(reply["run_id"], with_steps=False)["status"], "completed")

    def test_chat_no_spends_nothing(self):
        app = self.chat_app({"mode": "answer"})               # the router missed it; the wording catches it
        first = app.chat("Can you make me a picture of a lighthouse?")
        self.assertIn("Shall I make it?", first["reply"]["content"])
        second = app.chat("no", first["conversation"]["id"])["reply"]
        self.assertIn("nothing spent", second["content"])
        self.assertEqual(self.ask.call_count, 1)
        approval = app.runs.get(first["reply"]["run_id"])["steps"][-1]["approval_id"]
        self.assertEqual(app.safety.get_approval(approval)["status"], "denied")

    def test_chat_says_plainly_when_the_account_has_no_credits(self):
        self.ask.side_effect = lambda app, prompt, allowed, runner: {"balance": 0, "cost": 6, "plan": "free"}
        app = self.chat_app({"mode": "image", "prompt": "a fox"})
        reply = app.chat("make me a picture of a fox")["reply"]
        self.assertIn("has 0 (free)", reply["content"])
        self.assertIn("Nothing was spent", reply["content"])
        self.assertEqual(app.safety.list_approvals(status="pending"), [])


class WorkspaceFileRouteTests(JarvisTestCase):
    def call(self, path):
        from jarvis.web import server
        handler = next(h for m, p, h in server.ROUTES if m == "GET" and p.match(path))
        match = next(p.match(path) for m, p, h in server.ROUTES if m == "GET" and p.match(path))
        return handler(self.app, server.Request(match.groups(), {}))

    def test_serves_workspace_images_and_refuses_anything_outside(self):
        from jarvis.common import NotFoundError, PermissionDenied
        folder = self.app.config.workspace_dir / "images"
        folder.mkdir(parents=True)
        (folder / "fox.png").write_bytes(PNG)
        (folder / "page.html").write_text("<script>alert(1)</script>")
        raw = self.call("/api/files/images/fox.png")
        self.assertEqual((raw.data, raw.content_type), (PNG, "image/png"))
        self.assertEqual(self.call("/api/files/images/page.html").content_type, "application/octet-stream")
        (self.root / "secret.txt").write_text("no")
        for path in ("/api/files/../secret.txt", "/api/files/%2e%2e/secret.txt", "/api/files/images/../../secret.txt"):
            with self.assertRaises(PermissionDenied):
                self.call(path)
        with self.assertRaises(NotFoundError):
            self.call("/api/files/images/missing.png")


if __name__ == "__main__":
    unittest.main()
