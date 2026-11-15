"""Weekly self-review: JARVIS asks Claude Code to propose improvements to its own code.

Once every `JARVIS_REVIEW_DAYS` (default 7) while the server runs and JARVIS is
idle (off with `JARVIS_REVIEW=0`), a review pass:

1. cuts a fresh git worktree under `workspace/self-review/<date>` on a new
   branch `jarvis/self-review-<YYYY-MM-DD>` from `main`,
2. gives Claude Code (headless, no MCP servers, no personal settings) the tail of
   `data/logs/jarvis.log`, recently failed runs and the top of `DEVLOG.md`,
3. lets it make up to three small, safe fixes in that worktree only, keep the
   tests green, commit on that branch and explain each change in `SELF_REVIEW.md`.

Nothing reaches `main` until the owner presses Approve in the UI. Approve merges
the branch with `--no-ff` only after the tests pass on the merged result, and
never pushes. A proposal that touches the safety rules, this file or the
dependency list is discarded automatically.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .logging_setup import get_logger

log = get_logger("selfreview")
ACTOR = "jarvis:self-review"
STATUS_KEY = "selfreview.last"
PROPOSALS_KEY = "selfreview.proposals"
BRANCH_PREFIX = "jarvis/self-review-"
BRANCH_RE = re.compile(r"^jarvis/self-review-\d{4}-\d{2}-\d{2}(?:-\d{1,3})?$")
BASE = "main"
TEST_CMD = ["-m", "unittest", "discover", "-s", "tests"]
# Paths a self-review may never change: the hard lines, this reviewer, dependencies, local config.
PROTECTED = ("jarvis/safety.py", "jarvis/selfreview.py", ".claude/", ".env", "requirements",
             "pyproject.toml", "setup.py", "setup.cfg", ".gitignore")

ALLOWED_TOOLS = ["Read(./**)", "Grep(./**)", "Glob(./**)", "Edit(./**)", "Write(./**)", "MultiEdit(./**)",   # its own worktree only
                 "Bash(python3 -m unittest discover -s tests)", "Bash(python3 -m unittest:*)",
                 "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
                 "Bash(git add:*)", "Bash(git commit:*)"]
DENIED_TOOLS = ["WebSearch", "WebFetch", "Task", "Agent", "NotebookEdit", "KillShell",
                "Bash(git push:*)", "Bash(git merge:*)", "Bash(git checkout:*)", "Bash(git switch:*)",
                "Bash(git reset:*)", "Bash(git rebase:*)", "Bash(git branch:*)", "Bash(git worktree:*)",
                "Bash(git remote:*)", "Bash(git config:*)", "Bash(git -C:*)", "Bash(rm:*)", "Bash(sudo:*)",
                "Bash(curl:*)", "Bash(pip:*)", "Bash(pip3:*)"]

BRIEF = """You are reviewing the code of JARVIS, the owner's personal AI assistant, so it can improve itself.
You are inside a separate git worktree on branch {branch}. The owner will read your work and decide
whether to merge it; nothing you do reaches `main` without their approval.

Find up to 3 concrete, small, safe improvements: bugs visible in the logs or failed runs below,
code paths that fail, or clear code-quality fixes. Prefer fewer, solid changes over many. For each:
implement it, add or adjust a test when it makes sense, and run `python3 -m unittest discover -s tests`
until everything passes.

Then write a short SELF_REVIEW.md at the repository root: one section per change with what you changed,
why (point at the log line, failed run or code that showed the problem) and how you checked it.
Finally `git add` your files and `git commit` on this branch with a clear message.

Hard rules:
- Work only inside the current directory. Never push, never switch branches, never touch `main`.
- Never change jarvis/safety.py, approval categories, permission checks or any safety rule or hard line.
- Never change jarvis/selfreview.py. Never add dependencies or edit requirements/pyproject/setup files.
- Python standard library only. Keep each change small and easy to review.
- If you find nothing worth changing, change nothing and say so.
"""


def enabled() -> bool:
    return os.environ.get("JARVIS_REVIEW", "1") != "0"


def interval_days() -> float:
    try:
        return max(1.0, float(os.environ.get("JARVIS_REVIEW_DAYS", "7")))
    except ValueError:
        return 7.0


def timeout_seconds() -> int:
    try:
        return max(60, int(os.environ.get("JARVIS_REVIEW_TIMEOUT", "1800")))
    except ValueError:
        return 1800


def is_proposal(branch: str) -> bool:
    """Only branches JARVIS made for a self-review may be approved or rejected."""
    return bool(BRANCH_RE.match(branch or ""))


def branch_name(day: str, existing) -> str:
    """`jarvis/self-review-<day>`, or `-2`, `-3`... when that day already has one."""
    existing = set(existing)
    name, n = f"{BRANCH_PREFIX}{day}", 1
    while name in existing:
        n += 1
        name = f"{BRANCH_PREFIX}{day}-{n}"
    return name


def touches_protected(paths) -> list[str]:
    return [p for p in paths if any(p == rule or p.startswith(rule) for rule in PROTECTED)]


def claude_command(binary: str, prompt: str, branch: str) -> list[str]:
    return [binary, "-p", "--output-format", "json",
            "--permission-mode", "acceptEdits",
            "--allowedTools", ",".join(ALLOWED_TOOLS),
            "--disallowedTools", ",".join(DENIED_TOOLS),
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "project",
            "--no-session-persistence",
            "--append-system-prompt", BRIEF.format(branch=branch), "--", prompt]


def run_tests(cwd: Path) -> tuple[bool, str]:
    try:
        done = subprocess.run([sys.executable, *TEST_CMD], cwd=str(cwd), capture_output=True, text=True,
                              timeout=900, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, "the test suite did not finish within 15 minutes"
    return done.returncode == 0, ((done.stderr or "") + (done.stdout or ""))[-2000:]


class SelfReview:
    def __init__(self, app, repo: Path | str | None = None, runner=subprocess.run, tests=run_tests):
        self.app = app
        self.repo = Path(repo or app.config.root)
        self.runner = runner          # runs Claude Code (tests inject a fake)
        self.tests = tests            # runs the test suite in a directory -> (ok, output)
        self._stop = threading.Event()
        self._pass = threading.Lock()
        self._git_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # --- git ---------------------------------------------------------------
    @property
    def root(self) -> Path:
        return Path(self.app.config.workspace_dir) / "self-review"

    def git(self, *args, cwd: Path | None = None, check: bool = True) -> str:
        done = subprocess.run(["git", *args], cwd=str(cwd or self.repo), capture_output=True, text=True,
                              timeout=300, stdin=subprocess.DEVNULL)
        if check and done.returncode:
            raise RuntimeError(f"git {' '.join(args[:3])} failed: {(done.stderr or done.stdout).strip()[:300]}")
        return done.stdout.strip()

    def branches(self) -> list[str]:
        out = self.git("for-each-ref", "--format=%(refname:short)", f"refs/heads/{BRANCH_PREFIX}*")
        return sorted((b for b in out.splitlines() if is_proposal(b)), reverse=True)

    def worktree_of(self, branch: str) -> Path | None:
        path = None
        for line in self.git("worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                path = Path(line[9:])
            elif line == f"branch refs/heads/{branch}" and path is not None:
                return path
        return None

    def _remove_worktree(self, path: Path | None) -> None:
        if path is None:
            return
        path = Path(path)
        if self.root.resolve() not in path.resolve().parents:   # only ever remove our own worktrees
            raise RuntimeError(f"refusing to remove a worktree outside {self.root}")
        self.git("worktree", "remove", "--force", str(path), check=False)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        self.git("worktree", "prune", check=False)

    # --- inputs for the review --------------------------------------------
    def inputs(self) -> str:
        parts = []
        log_file = Path(self.app.config.log_dir) / "jarvis.log"
        try:
            tail = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            parts.append("## Recent jarvis.log (tail)\n" + "\n".join(tail)[-12000:])
        except OSError:
            parts.append("## Recent jarvis.log\n(no log file)")
        try:
            failed = self.app.runs.list(limit=15, status="failed")
        except Exception:  # noqa: BLE001
            failed = []
        lines = [f"- run {r.get('id')} [{r.get('kind')}] {str(r.get('goal', ''))[:160]} -> "
                 f"{str(r.get('error') or '')[:300]} ({r.get('created_at', '')})" for r in failed]
        parts.append("## Recently failed runs\n" + ("\n".join(lines) or "(none)"))
        try:
            devlog = (self.repo / "DEVLOG.md").read_text(encoding="utf-8")[:6000]
            parts.append("## Recent DEVLOG.md\n" + devlog)
        except OSError:
            pass
        return "\n\n".join(parts)

    # --- one review pass ---------------------------------------------------
    def once(self) -> dict:
        """Run one review pass now. Never raises; the outcome is kept in settings."""
        if not self._pass.acquire(blocking=False):
            return {"ok": False, "error": "A self-review pass is already running."}
        started = time.monotonic()
        try:
            outcome = self._review()
        except Exception as exc:  # noqa: BLE001 - a review must never take JARVIS down
            log.exception("Self-review pass failed")
            outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
        finally:
            self._pass.release()
        outcome["seconds"] = round(time.monotonic() - started)
        outcome["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        outcome["epoch"] = time.time()
        self.app.settings.set(STATUS_KEY, outcome, category="self-review", source="jarvis")
        self.app.events.record("system", "selfreview.pass", outcome.get("summary") or
                               f"Self-review did not finish: {outcome.get('error')}", actor=ACTOR,
                               level="info" if outcome["ok"] else "warning", details=outcome)
        return outcome

    def _review(self) -> dict:
        from .tools.claude import claude_binary
        binary = claude_binary()
        if not binary:
            return {"ok": False, "error": "Claude Code is not installed (set JARVIS_CLAUDE_BIN)."}
        with self._git_lock:
            self.git("rev-parse", "--verify", f"refs/heads/{BASE}")
            branch = branch_name(time.strftime("%Y-%m-%d"), self.branches())
            path = self.root / branch[len(BRANCH_PREFIX):]
            self.root.mkdir(parents=True, exist_ok=True)
            self.git("worktree", "add", "-b", branch, str(path), BASE)
        prompt = ("Review JARVIS and propose up to 3 small improvements, following your brief.\n\n"
                  + self.inputs())
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
        try:
            try:
                done = self.runner(claude_command(binary, prompt, branch), cwd=str(path), capture_output=True,
                                   text=True, timeout=timeout_seconds(), env=env, stdin=subprocess.DEVNULL)
                reply_text, failed = done.stdout or "", bool(done.returncode)
            except subprocess.TimeoutExpired:
                reply_text, failed = "", True
                log.warning("Self-review: Claude Code timed out; keeping whatever it committed")
            import json
            try:
                result = str(json.loads(reply_text).get("result", ""))
            except (ValueError, AttributeError):
                result = (reply_text or "")[-2000:]
            return self._finish(branch, path, result, failed)
        except Exception:
            self._discard(branch, path)
            raise

    def _finish(self, branch: str, path: Path, result: str, failed: bool = False) -> dict:
        # commit anything left uncommitted so the proposal is complete and reviewable
        if self.git("status", "--porcelain", cwd=path):
            if not (path / "SELF_REVIEW.md").exists() and result.strip():
                (path / "SELF_REVIEW.md").write_text(f"# Self-review {branch}\n\n{result.strip()}\n", encoding="utf-8")
            self.git("add", "-A", cwd=path)
            self.git("commit", "-m", f"Self-review: uncommitted changes from {branch}", cwd=path)
        commits = int(self.git("rev-list", "--count", f"{BASE}..{branch}") or 0)
        if not commits:
            self._discard(branch, path)
            if failed:
                return {"ok": False, "branch": None, "error": f"Claude Code failed: {result[-300:] or 'no output'}"}
            return {"ok": True, "branch": None, "summary": "Self-review found nothing worth changing.",
                    "result": result[:1500]}
        changed = self.git("diff", "--name-only", f"{BASE}...{branch}").splitlines()
        blocked = touches_protected(changed)
        if blocked:
            self._discard(branch, path)
            return {"ok": False, "branch": None, "error": "Proposal discarded: it changed protected files "
                    + ", ".join(blocked), "result": result[:1500]}
        if not (path / "SELF_REVIEW.md").exists():
            (path / "SELF_REVIEW.md").write_text(f"# Self-review {branch}\n\n{result.strip() or '(no notes)'}\n",
                                                 encoding="utf-8")
            self.git("add", "SELF_REVIEW.md", cwd=path)
            self.git("commit", "-m", "Self-review notes", cwd=path)
        tests_ok, output = self.tests(path)
        proposals = self.app.settings.get(PROPOSALS_KEY, {}) or {}
        proposals[branch] = {"tests_ok": tests_ok, "tests_output": output[-1500:], "files": changed,
                             "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.app.settings.set(PROPOSALS_KEY, proposals, category="self-review", source="jarvis")
        return {"ok": True, "branch": branch, "tests_ok": tests_ok, "files": changed,
                "summary": f"Self-review proposed {len(changed)} changed file(s) on {branch}"
                           f" (tests {'pass' if tests_ok else 'FAIL'}); waiting for your approval.",
                "result": result[:1500]}

    def _discard(self, branch: str, path: Path | None) -> None:
        with self._git_lock:
            try:
                self._remove_worktree(path or self.worktree_of(branch))
            finally:
                if is_proposal(branch):
                    self.git("branch", "-D", branch, check=False)

    # --- owner decisions (from the UI only) --------------------------------
    def _check(self, branch: str) -> None:
        if not is_proposal(branch):
            raise ValueError(f"{branch!r} is not a self-review branch; only jarvis/self-review-* can be approved")
        if branch not in self.branches():
            raise ValueError(f"no self-review branch named {branch}")

    def approve(self, branch: str) -> dict:
        """Merge a proposal into main with --no-ff once the merged result passes the tests. Never pushes."""
        self._check(branch)
        with self._git_lock:
            current = self.git("rev-parse", "--abbrev-ref", "HEAD")
            if current != BASE:
                return {"ok": False, "error": f"{self.repo} is on {current!r}, not {BASE}; switch it to {BASE} first."}
            if self.git("status", "--porcelain", "--untracked-files=no"):
                return {"ok": False, "error": f"{self.repo} has uncommitted changes; commit or stash them first."}
            trial = self.root / f"_approve-{int(time.time())}"
            self.root.mkdir(parents=True, exist_ok=True)
            self.git("worktree", "add", "--detach", str(trial), BASE)
            try:
                merged = subprocess.run(["git", "merge", "--no-ff", "-m", f"Merge self-review {branch}", branch],
                                        cwd=str(trial), capture_output=True, text=True, timeout=300)
                if merged.returncode:
                    return {"ok": False, "error": f"{branch} does not merge cleanly into {BASE}; reject it "
                            "or resolve it by hand."}
                tests_ok, output = self.tests(trial)
                if not tests_ok:
                    return {"ok": False, "error": "Tests fail on the merged result; not merging.",
                            "tests_output": output[-1500:]}
                sha = self.git("rev-parse", "HEAD", cwd=trial)
            finally:
                self._remove_worktree(trial)
            self.git("merge", "--ff-only", sha)                       # main becomes the tested --no-ff merge
            self._remove_worktree(self.worktree_of(branch))
            self.git("branch", "-D", branch, check=False)
        self._forget(branch)
        message = f"Merged {branch} into {BASE} (not pushed). Push when ready: git push origin {BASE}"
        self.app.events.record("system", "selfreview.approve", message, actor="user", details={"branch": branch,
                                                                                               "commit": sha})
        return {"ok": True, "branch": branch, "commit": sha, "message": message}

    def reject(self, branch: str) -> dict:
        """Delete a proposal's worktree and branch."""
        self._check(branch)
        self._discard(branch, None)
        self._forget(branch)
        self.app.events.record("system", "selfreview.reject", f"Rejected and deleted {branch}", actor="user",
                               details={"branch": branch})
        return {"ok": True, "branch": branch, "message": f"Deleted {branch}."}

    def _forget(self, branch: str) -> None:
        proposals = self.app.settings.get(PROPOSALS_KEY, {}) or {}
        if proposals.pop(branch, None) is not None:
            self.app.settings.set(PROPOSALS_KEY, proposals, category="self-review", source="jarvis")

    # --- status --------------------------------------------------------------
    def proposals(self) -> list[dict]:
        known = self.app.settings.get(PROPOSALS_KEY, {}) or {}
        items = []
        for branch in self.branches():
            notes = self.git("show", f"{branch}:SELF_REVIEW.md", check=False)
            stat = self.git("diff", "--stat", f"{BASE}...{branch}", check=False)
            path = self.worktree_of(branch)
            items.append({"branch": branch, "self_review": notes[:8000], "diff_stat": stat[-4000:],
                          "worktree": str(path) if path else None, **(known.get(branch) or {})})
        return items

    def status(self) -> dict:
        try:
            items, error = self.proposals(), None
        except Exception as exc:  # noqa: BLE001 - e.g. not a git repository
            items, error = [], str(exc)[:300]
        return {"enabled": enabled(), "interval_days": interval_days(), "running": self._pass.locked(),
                "daemon": bool(self._thread and self._thread.is_alive()),
                "last": self.app.settings.get(STATUS_KEY), "proposals": items, "error": error}

    # --- background loop ---------------------------------------------------
    def due(self) -> bool:
        last = self.app.settings.get(STATUS_KEY) or {}
        return time.time() - float(last.get("epoch") or 0) >= interval_days() * 86400

    def idle(self) -> bool:
        try:
            return self.app.engine.live().get("state") == "calm"
        except Exception:  # noqa: BLE001
            return False

    def start(self) -> "SelfReview":
        if not enabled() or self._thread:
            return self
        self._thread = threading.Thread(target=self._run, name="jarvis-selfreview", daemon=True)
        self._thread.start()
        log.info("Self-review on: a pass every %g days when idle", interval_days())
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        if self._stop.wait(300):          # let startup and the first learning pass settle
            return
        while not self._stop.is_set():
            if self.due() and self.idle():
                self.once()
            self._stop.wait(1800)
