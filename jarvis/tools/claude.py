"""Claude Code as JARVIS's heavy-lifting mind.

The local model is small; hard work (coding, deep research, analysis, long
writing, planning) is handed to Claude Code (`claude -p`) and the answer comes
back as JARVIS's own. The hard lines still hold:

- no shell: Bash is disallowed, so Claude Code cannot run commands;
- files: only inside JARVIS's workspace (`workspace/`), and only when the
  caller asks for `write_files`; otherwise it can only read and search the web;
- no MCP servers or plugins (they could spend money or message people);
- no saved session; a hard time limit.

It runs through `ToolRegistry.execute` like every other tool, so it is logged,
validated and checked by the safety layer.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ..common import JarvisError, ValidationError
from ..safety import ActionCategory
from .registry import Tool, ToolRegistry

TIMEOUT = int(os.environ.get("JARVIS_CLAUDE_TIMEOUT", "900"))
READ_TOOLS = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]
WRITE_TOOLS = ["Edit", "Write", "MultiEdit", "NotebookEdit"]
NEVER = ["Bash", "BashOutput", "KillShell", "Task", "Agent"]
BRIEF = ("You are working as the deep mind of JARVIS, a personal assistant. Do the task fully and "
         "well. You cannot run shell commands. {files} Reply with the finished result itself "
         "(the answer, the analysis, or a summary of the files you made and where), concise and "
         "ready to show the owner. Say plainly if something could not be done or verified.")


def claude_binary() -> str | None:
    found = os.environ.get("JARVIS_CLAUDE_BIN") or shutil.which("claude")
    if found:
        return found
    default = Path.home() / ".local" / "bin" / "claude"
    return str(default) if default.exists() else None


def command(binary: str, task: str, write_files: bool) -> list[str]:
    allowed = READ_TOOLS + (WRITE_TOOLS if write_files else [])
    files = ("You may create and edit files, but only inside the current directory."
             if write_files else "Do not create or change any files.")
    return [binary, "-p", task, "--output-format", "json",
            "--permission-mode", "acceptEdits" if write_files else "default",
            "--allowedTools", ",".join(allowed),
            "--disallowedTools", ",".join(NEVER + ([] if write_files else WRITE_TOOLS)),
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence",
            "--append-system-prompt", BRIEF.format(files=files)]


def claude_work(app, inputs, actor, runner=subprocess.run):
    task = inputs["task"].strip()
    if not task:
        raise ValidationError("claude.work: 'task' is empty")
    binary = claude_binary()
    if not binary:
        raise JarvisError("Claude Code is not installed (set JARVIS_CLAUDE_BIN or put `claude` on PATH)")
    workspace = Path(app.config.workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
    try:
        done = runner(command(binary, task, bool(inputs.get("write_files"))), cwd=str(workspace),
                      capture_output=True, text=True, timeout=TIMEOUT, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise JarvisError(f"Claude Code did not finish within {TIMEOUT // 60} minutes") from None
    try:
        reply = json.loads(done.stdout)
    except (json.JSONDecodeError, TypeError):
        detail = (done.stderr or done.stdout or "").strip()[-400:]
        raise JarvisError(f"Claude Code failed (exit {done.returncode}): {detail or 'no output'}") from None
    if reply.get("is_error") or done.returncode:
        raise JarvisError(f"Claude Code reported an error: {str(reply.get('result') or reply)[:400]}")
    return {"result": reply.get("result", ""), "workspace": str(workspace),
            "turns": reply.get("num_turns"), "duration_ms": reply.get("duration_ms"),
            "cost_usd": reply.get("total_cost_usd")}


def register_claude(registry: ToolRegistry) -> None:
    registry.register(Tool(
        "claude.work",
        "Hand a hard job to Claude Code, a far stronger mind: writing or fixing code, deep research "
        "across the web, analysis, long or careful writing, plans and explanations that need real "
        "reasoning. Returns the finished result. Set write_files to let it create files in JARVIS's "
        "workspace folder. It cannot run commands.",
        ActionCategory.WORKSPACE, claude_work,
        {"task": {"type": "string", "description": "The complete, self-contained task.", "required": True},
         "write_files": {"type": "boolean", "description": "Allow creating files in the workspace folder."}}))
