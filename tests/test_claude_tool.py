"""claude.work: the Claude Code bridge. Claude itself is never run here."""

import json
import subprocess
import unittest
from unittest import mock

from jarvis.common import JarvisError
from jarvis.tools import claude


class FakeApp:
    class config:
        workspace_dir = None


def done(stdout, code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


class ClaudeToolTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        FakeApp.config.workspace_dir = self.tmp.name
        self.bin = mock.patch.object(claude, "claude_binary", return_value="/bin/claude")
        self.bin.start()

    def tearDown(self):
        self.bin.stop()
        self.tmp.cleanup()

    def run_tool(self, inputs, stdout, code=0):
        calls = []
        def runner(cmd, **kw):
            calls.append((cmd, kw))
            return done(stdout, code)
        out = claude.claude_work(FakeApp, inputs, "user", runner=runner)
        return out, calls[0]

    def test_read_only_by_default_no_shell_no_mcp(self):
        out, (cmd, kw) = self.run_tool({"task": "explain x"}, json.dumps({"result": "Done.", "num_turns": 2}))
        self.assertEqual(out["result"], "Done.")
        self.assertEqual(kw["cwd"], self.tmp.name)
        allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
        denied = cmd[cmd.index("--disallowedTools") + 1].split(",")
        self.assertNotIn("Write", allowed)
        self.assertIn("Write", denied)
        self.assertIn("Bash", denied)
        self.assertIn("--strict-mcp-config", cmd)

    def test_write_files_allows_edits_in_workspace_only(self):
        _, (cmd, kw) = self.run_tool({"task": "make a page", "write_files": True}, json.dumps({"result": "ok"}))
        allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
        self.assertIn("Write", allowed)
        self.assertNotIn("Bash", allowed)
        self.assertIn("Bash", cmd[cmd.index("--disallowedTools") + 1].split(","))
        self.assertEqual(kw["cwd"], self.tmp.name)

    def test_operate_allows_shell_in_workspace(self):
        calls = []
        def runner(cmd, **kw):
            calls.append((cmd, kw)); return done(json.dumps({"result": "built"}))
        out = claude.claude_operate(FakeApp, {"task": "build it"}, "user", runner=runner)
        cmd, kw = calls[0]
        self.assertEqual(out["result"], "built")
        self.assertIn("Bash", cmd[cmd.index("--allowedTools") + 1].split(","))
        self.assertNotIn("Bash", cmd[cmd.index("--disallowedTools") + 1].split(","))
        self.assertEqual(kw["cwd"], self.tmp.name)

    def test_research_is_read_only_and_keeps_sourced_facts(self):
        calls = []
        result = json.dumps({"facts": [{"fact": "Dealers hold about half of used-car sales.", "url": "https://a.example/x"},
                                       {"fact": "No source here at all, so it is dropped.", "url": ""}]})
        def runner(cmd, **kw):
            calls.append(cmd); return done(json.dumps({"result": "Here: " + result, "total_cost_usd": 0.01}))
        out = claude.claude_research(FakeApp, {"query": "used cars"}, "jarvis:learn", runner=runner)
        cmd = calls[0]
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "WebSearch,WebFetch")
        self.assertIn("Bash", cmd[cmd.index("--disallowedTools") + 1])
        self.assertEqual(out["facts"], [{"fact": "Dealers hold about half of used-car sales.", "url": "https://a.example/x"}])

    def test_errors_are_reported(self):
        with self.assertRaises(JarvisError):
            self.run_tool({"task": "x"}, "not json", code=1)
        with self.assertRaises(JarvisError):
            self.run_tool({"task": "x"}, json.dumps({"is_error": True, "result": "limit reached"}))


if __name__ == "__main__":
    unittest.main()
