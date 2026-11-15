"""Weekly self-review: proposals on a branch, merged only by the owner. Claude is never run here."""

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

from jarvis import selfreview
from jarvis.tools import claude
from support import JarvisTestCase

GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


class BranchNameTests(JarvisTestCase):
    def test_branch_naming(self):
        self.assertEqual(selfreview.branch_name("2026-11-16", []), "jarvis/self-review-2026-11-16")
        self.assertEqual(selfreview.branch_name("2026-11-16", ["jarvis/self-review-2026-11-16"]),
                         "jarvis/self-review-2026-11-16-2")
        self.assertEqual(selfreview.branch_name("2026-11-16", ["jarvis/self-review-2026-11-16",
                                                               "jarvis/self-review-2026-11-16-2"]),
                         "jarvis/self-review-2026-11-16-3")

    def test_only_self_review_branches_count(self):
        for good in ("jarvis/self-review-2026-11-16", "jarvis/self-review-2026-11-16-2"):
            self.assertTrue(selfreview.is_proposal(good))
        for bad in ("main", "jarvis/self-review-", "jarvis/self-review-2026-11-16;rm", "feature/x",
                    "jarvis/self-review-2026-11-16/../main", "", None):
            self.assertFalse(selfreview.is_proposal(bad))

    def test_protected_paths(self):
        self.assertEqual(selfreview.touches_protected(["jarvis/safety.py", "jarvis/learner.py", "requirements.txt"]),
                         ["jarvis/safety.py", "requirements.txt"])

    def test_command_never_allows_push_or_free_shell(self):
        cmd = selfreview.claude_command("/bin/claude", "p", "jarvis/self-review-2026-11-16")
        allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
        denied = cmd[cmd.index("--disallowedTools") + 1]
        self.assertNotIn("Bash", allowed)                        # Bash only with a fixed command prefix
        self.assertTrue(all(t.startswith(("Bash(python3 -m unittest", "Bash(git ")) for t in allowed if "Bash" in t))
        self.assertIn("Bash(git push:*)", denied)
        for flag in ("--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "project")


class SelfReviewTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, GIT_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bin = mock.patch.object(claude, "claude_binary", return_value="/bin/claude")
        self.bin.start()
        self.addCleanup(self.bin.stop)
        repo = self.root
        (repo / ".gitignore").write_text("/data/\n/workspace/\n")
        (repo / "jarvis").mkdir(exist_ok=True)
        (repo / "jarvis" / "thing.py").write_text("X = 1\n")
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "start")
        self.tests_ok = True
        self.calls = []
        self.review = selfreview.SelfReview(self.app, repo=repo, runner=self.fake_claude,
                                            tests=lambda cwd: (self.tests_ok, "ran"))
        self.edit = {"jarvis/thing.py": "X = 2\n"}

    def fake_claude(self, cmd, cwd, **kw):
        """Pretend to be Claude Code: edit files in the worktree and commit them."""
        self.calls.append((cmd, cwd, kw))
        for name, text in self.edit.items():
            (Path(cwd) / name).parent.mkdir(parents=True, exist_ok=True)
            (Path(cwd) / name).write_text(text)
        if self.edit:
            (Path(cwd) / "SELF_REVIEW.md").write_text("# Self-review\n\n1. Fixed X.\n")
            git(cwd, "add", "-A")
            git(cwd, "commit", "-q", "-m", "fix X")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": "Changed X."}), stderr="")

    def test_pass_creates_branch_and_worktree_from_main(self):
        out = self.review.once()
        self.assertTrue(out["ok"], out)
        branch = out["branch"]
        self.assertTrue(selfreview.is_proposal(branch))
        cmd, cwd, kw = self.calls[0]
        self.assertTrue(Path(cwd).is_relative_to(self.root / "workspace" / "self-review"))
        self.assertFalse(any(k.startswith("CLAUDE_CODE_") for k in kw["env"]))
        self.assertEqual(git(self.root, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual((self.root / "jarvis" / "thing.py").read_text(), "X = 1\n")     # main untouched
        items = self.review.status()["proposals"]
        self.assertEqual([p["branch"] for p in items], [branch])
        self.assertIn("Fixed X", items[0]["self_review"])
        self.assertIn("thing.py", items[0]["diff_stat"])

    def test_second_pass_same_day_gets_new_branch(self):
        first = self.review.once()["branch"]
        second = self.review.once()["branch"]
        self.assertEqual(second, first + "-2")

    def test_nothing_changed_leaves_no_branch(self):
        self.edit = {}
        out = self.review.once()
        self.assertTrue(out["ok"])
        self.assertIsNone(out["branch"])
        self.assertEqual(self.review.branches(), [])

    def test_protected_change_is_discarded(self):
        self.edit = {"jarvis/safety.py": "ALLOW_EVERYTHING = True\n"}
        out = self.review.once()
        self.assertFalse(out["ok"])
        self.assertIn("jarvis/safety.py", out["error"])
        self.assertEqual(self.review.branches(), [])

    def test_approve_merges_no_ff_and_does_not_push(self):
        branch = self.review.once()["branch"]
        before = git(self.root, "rev-parse", "main")
        out = self.review.approve(branch)
        self.assertTrue(out["ok"], out)
        self.assertIn("not pushed", out["message"])
        self.assertEqual((self.root / "jarvis" / "thing.py").read_text(), "X = 2\n")
        parents = git(self.root, "rev-list", "--parents", "-n", "1", "main").split()
        self.assertEqual(len(parents), 3)                  # a real merge commit
        self.assertEqual(parents[1], before)
        self.assertEqual(self.review.branches(), [])
        self.assertIsNone(self.review.worktree_of(branch))

    def test_approve_refuses_when_tests_fail(self):
        branch = self.review.once()["branch"]
        before = git(self.root, "rev-parse", "main")
        self.tests_ok = False
        out = self.review.approve(branch)
        self.assertFalse(out["ok"])
        self.assertIn("Tests fail", out["error"])
        self.assertEqual(git(self.root, "rev-parse", "main"), before)
        self.assertEqual(self.review.branches(), [branch])      # still there to look at

    def test_approve_and_reject_only_act_on_self_review_branches(self):
        git(self.root, "branch", "feature")
        for action in (self.review.approve, self.review.reject):
            for name in ("main", "feature", "jarvis/self-review-2026-01-01"):
                with self.assertRaises(ValueError):
                    action(name)
        self.assertIn("feature", git(self.root, "branch", "--list", "feature"))

    def test_reject_deletes_branch_and_worktree(self):
        branch = self.review.once()["branch"]
        path = self.review.worktree_of(branch)
        out = self.review.reject(branch)
        self.assertTrue(out["ok"])
        self.assertEqual(self.review.branches(), [])
        self.assertFalse(path.exists())
        self.assertEqual((self.root / "jarvis" / "thing.py").read_text(), "X = 1\n")

    def test_due_after_interval(self):
        self.assertTrue(self.review.due())
        self.review.once()
        self.assertFalse(self.review.due())


class SelfReviewWebTests(SelfReviewTests):
    """The owner's routes. Inherits the repo setup; runs only the web checks below."""

    def setUp(self):
        super().setUp()
        import threading
        from jarvis.web import create_server
        self.app.selfreview = self.review
        self.server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            conn.request(method, path)
            response = conn.getresponse()
            return response.status, json.loads(response.read() or b"{}")
        finally:
            conn.close()

    def test_routes(self):
        branch = self.review.once()["branch"]
        status, data = self.call("GET", "/api/self-review")
        self.assertEqual(status, 200)
        self.assertEqual([p["branch"] for p in data["proposals"]], [branch])
        self.assertEqual(self.call("POST", "/api/self-review/main/approve")[0], 404)
        self.assertEqual(self.call("POST", "/api/self-review/jarvis/self-review-2001-01-01/approve")[0], 400)
        status, data = self.call("POST", f"/api/self-review/{branch}/approve")
        self.assertEqual(status, 200, data)
        self.assertEqual((self.root / "jarvis" / "thing.py").read_text(), "X = 2\n")


# keep the inherited repo tests from running twice
for _name in [n for n in dir(SelfReviewTests) if n.startswith("test_")]:
    setattr(SelfReviewWebTests, _name, None)
