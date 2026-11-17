"""Agent mode (the Code page), the owner's terminal and website preview."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from jarvis.coder import is_read_only
from jarvis.providers.base import AIProvider, ProviderResponse, ProviderStatus

from support import JarvisTestCase


class Scripted(AIProvider):
    """Plays back agent actions, one per model call."""
    name = "scripted"
    is_local = True

    def __init__(self, actions):
        self.actions, self.seen = list(actions), []

    def status(self):
        return ProviderStatus(name=self.name, kind="local", configured=True, available=True, model="test", detail="")

    def generate(self, messages, json_output=False, on_token=None):
        self.seen.append(messages[-1].content)
        action = self.actions.pop(0) if self.actions else {"action": "done", "input": {"summary": "out of script"}}
        return ProviderResponse(text=json.dumps(action), provider=self.name, model="test")


def wait(coder, session_id, until=("completed", "failed", "stopped", "waiting_owner", "waiting_approval"), seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        session = coder.get(session_id)
        if session["status"] in until:
            return session
        time.sleep(0.05)
    raise AssertionError(f"session still {coder.get(session_id)['status']}")


class AgentModeTest(JarvisTestCase):
    def agent(self, actions):
        provider = Scripted(actions)
        self.app.provider = provider
        return provider

    def test_builds_files_in_the_workspace_without_asking(self):
        self.agent([
            {"thought": "plan", "action": "todo", "input": {"items": [{"content": "write page", "status": "in_progress"}]}},
            {"action": "write", "input": {"path": "sites/demo/index.html", "content": "<h1>Hello</h1>\n"}},
            {"action": "edit", "input": {"path": "sites/demo/index.html", "old": "Hello", "new": "Aureus"}},
            {"action": "read", "input": {"path": "sites/demo/index.html"}},
            {"action": "done", "input": {"summary": "Built the page."}},
        ])
        session = wait(self.app.coder, self.app.coder.start("build a page")["id"])
        self.assertEqual(session["status"], "completed")
        page = Path(self.app.config.workspace_dir) / "sites" / "demo" / "index.html"
        self.assertEqual(page.read_text(), "<h1>Aureus</h1>\n")
        results = [s for s in session["steps"] if s["kind"] == "result"]
        self.assertTrue(all(r["ok"] for r in results), results)
        self.assertIn("+<h1>Aureus</h1>", next(r["diff"] for r in results if r.get("tool") == "code.edit"))
        self.assertEqual(session["todos"][0]["content"], "write page")
        self.assertEqual(session["summary"], "Built the page.")

    def test_paths_cannot_leave_the_folder(self):
        self.agent([{"action": "read", "input": {"path": "../../etc/passwd"}},
                    {"action": "write", "input": {"path": "/tmp/x.txt", "content": "no"}},
                    {"action": "done", "input": {"summary": "x"}}])
        session = wait(self.app.coder, self.app.coder.start("escape")["id"])
        results = [s for s in session["steps"] if s["kind"] == "result"]
        self.assertFalse(any(r["ok"] for r in results))
        self.assertTrue(all("outside" in r["text"] for r in results), results)

    def test_commands_wait_for_the_approve_button(self):
        self.agent([{"action": "run", "input": {"command": "echo built > made.txt"}},
                    {"action": "done", "input": {"summary": "ran it"}}])
        session = wait(self.app.coder, self.app.coder.start("run something")["id"], until=("waiting_approval",))
        card = [s for s in session["steps"] if s["kind"] == "approval"][-1]
        self.assertIn("echo built", card["text"])
        made = Path(self.app.config.workspace_dir) / "made.txt"
        self.assertFalse(made.exists())                      # nothing ran before the click
        self.app.safety.approve(card["approval_id"])
        session = wait(self.app.coder, session["id"], until=("completed", "failed"))
        self.assertEqual(session["status"], "completed")
        self.assertEqual(made.read_text().strip(), "built")

    def test_denied_command_does_not_run(self):
        self.agent([{"action": "run", "input": {"command": "echo no > denied.txt"}},
                    {"action": "done", "input": {"summary": "fine"}}])
        session = wait(self.app.coder, self.app.coder.start("x")["id"], until=("waiting_approval",))
        self.app.safety.deny([s for s in session["steps"] if s["kind"] == "approval"][-1]["approval_id"])
        session = wait(self.app.coder, session["id"], until=("completed", "failed"))
        self.assertFalse((Path(self.app.config.workspace_dir) / "denied.txt").exists())
        self.assertIn("did not approve", [s for s in session["steps"] if s["kind"] == "result"][-1]["text"])

    def test_read_only_commands_run_at_once_and_others_need_approval(self):
        self.assertTrue(is_read_only("ls -la"))
        self.assertTrue(is_read_only("git status"))
        self.assertTrue(is_read_only("python3 --version"))
        for risky in ("rm -rf x", "ls; rm x", "cat a > b", "find . -delete", "git push", "python3 x.py", "echo $(id)"):
            self.assertFalse(is_read_only(risky), risky)
        out = self.app.tools.execute("shell.look", {"command": "ls"}, actor="test")
        self.assertTrue(out["ok"], out)
        refused = self.app.tools.execute("shell.look", {"command": "rm -rf x"}, actor="test")
        self.assertFalse(refused["ok"])
        self.assertEqual(self.app.tools.execute("shell.run", {"command": "ls"}, actor="test")["status"], "approval_required")

    def test_owner_folders_need_approval_for_every_write(self):
        self.assertEqual(self.app.tools.get("code.write_home").category.value, "system")
        self.assertEqual(self.app.tools.get("code.edit_home").category.value, "system")
        result = self.app.tools.execute("code.write", {"folder": str(Path.home()), "path": "jarvis-test.txt", "content": "x"},
                                        actor="test")
        self.assertFalse(result["ok"])
        self.assertIn("workspace", result["error"])
        self.assertFalse((Path.home() / "jarvis-test.txt").exists())

    def test_ask_waits_for_the_owner_and_follow_up_continues(self):
        provider = self.agent([{"action": "ask", "input": {"question": "Which colour?"}},
                               {"action": "done", "input": {"summary": "Used gold."}}])
        session = wait(self.app.coder, self.app.coder.start("make it pretty")["id"], until=("waiting_owner",))
        self.assertEqual(session["steps"][-1]["text"], "Which colour?")
        self.app.coder.send(session["id"], "gold")
        session = wait(self.app.coder, session["id"], until=("completed",))
        self.assertIn("OWNER: gold", provider.seen[-1])

    def test_sessions_survive_a_restart(self):
        self.agent([{"action": "done", "input": {"summary": "ok"}}])
        session = wait(self.app.coder, self.app.coder.start("small job")["id"])
        again = self.make_app()
        self.assertEqual(again.coder.get(session["id"])["summary"], "ok")

    def test_preview_serves_only_the_asked_site(self):
        site = Path(self.app.config.workspace_dir) / "sites" / "demo"
        site.mkdir(parents=True)
        (site / "index.html").write_text("<p>hi</p>")
        (Path(self.app.config.workspace_dir) / "secret.txt").write_text("private")
        import jarvis.coder as coder
        old = coder.PREVIEW_PORT
        coder.PREVIEW_PORT = 18766 + (int(time.time() * 1000) % 500)
        try:
            out = self.app.tools.execute("site.preview", {"path": "sites/demo"}, actor="test")
            self.assertTrue(out["ok"], out)
            import urllib.error
            import urllib.request
            self.assertIn("hi", urllib.request.urlopen(out["output"]["url"], timeout=5).read().decode())
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(out["output"]["url"].replace("sites/demo/", "secret.txt"), timeout=5)
            caught.exception.close()
        finally:
            server = self.app.coder.preview.server
            if server:
                server.shutdown()
                server.server_close()
            coder.PREVIEW_PORT = old

    def test_chat_starts_agent_mode_for_build_requests(self):
        self.agent([{"action": "done", "input": {"summary": "ok"}}])
        result = self.app.chat("build me a website for Aureus Detailing")
        self.assertIn("agent mode", result["reply"]["content"])
        self.assertTrue(self.app.coder.list())


class TerminalTest(JarvisTestCase):
    def test_runs_commands_follows_cd_and_logs_them(self):
        term = self.app.terminal
        term.cwd = str(self.root)
        job = term.run("mkdir -p sub && cd sub && echo hello")
        end = time.time() + 10
        while term.view(job["id"])["status"] == "running" and time.time() < end:
            time.sleep(0.05)
        view = term.view(job["id"])
        self.assertEqual(view["output"].strip(), "hello")
        self.assertEqual(Path(term.cwd).resolve(), (self.root / "sub").resolve())
        self.assertTrue(any(e["action"] == "terminal.run" for e in self.app.events.list(limit=20)))

    def test_secrets_are_not_in_the_environment(self):
        import os
        os.environ["JARVIS_BOOST_KEY"] = "gsk_not_for_commands"
        try:
            term = self.app.terminal
            term.cwd = str(self.root)
            job = term.run("env")
            end = time.time() + 10
            while term.view(job["id"])["status"] == "running" and time.time() < end:
                time.sleep(0.05)
            self.assertNotIn("gsk_not_for_commands", term.view(job["id"])["output"])
        finally:
            del os.environ["JARVIS_BOOST_KEY"]


if __name__ == "__main__":
    unittest.main()
