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


def command(binary: str, task: str, write_files: bool, shell: bool = False) -> list[str]:
    allowed = READ_TOOLS + (WRITE_TOOLS if write_files or shell else []) + (["Bash"] if shell else [])
    files = ("You may create and edit files, but only inside the current directory."
             if write_files or shell else "Do not create or change any files.")
    if shell:
        files += (" You may run shell commands, but only inside the current directory: never touch "
                  "files elsewhere, never use sudo, never delete outside it, never send messages or spend money.")
    never = [t for t in NEVER if not (shell and t in ("Bash", "BashOutput", "KillShell"))]
    return [binary, "-p", task, "--output-format", "json",
            "--permission-mode", "acceptEdits" if write_files or shell else "default",
            "--allowedTools", ",".join(allowed),
            "--disallowedTools", ",".join(never + ([] if write_files or shell else WRITE_TOOLS)),
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence",
            "--append-system-prompt", BRIEF.format(files=files)]


def claude_work(app, inputs, actor, runner=subprocess.run, shell=False):
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
        done = runner(command(binary, task, bool(inputs.get("write_files")), shell), cwd=str(workspace),
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


def claude_operate(app, inputs, actor, runner=subprocess.run):
    return claude_work(app, inputs, actor, runner=runner, shell=True)


def register_claude(registry: ToolRegistry) -> None:
    registry.register(Tool(
        "claude.operate",
        "Hand a job to Claude Code with full power inside JARVIS's workspace folder: it can run "
        "commands, install packages there, build and test software, and create files. Always asks the "
        "owner first. Use only when the job truly needs running commands; otherwise use claude.work.",
        ActionCategory.SYSTEM, claude_operate,
        {"task": {"type": "string", "description": "The complete, self-contained task.", "required": True}}))
    registry.register(Tool(
        "claude.work",
        "Hand a hard job to Claude Code, a far stronger mind: writing or fixing code, deep research "
        "across the web, analysis, long or careful writing, plans and explanations that need real "
        "reasoning. Returns the finished result. Set write_files to let it create files in JARVIS's "
        "workspace folder. It cannot run commands.",
        ActionCategory.WORKSPACE, claude_work,
        {"task": {"type": "string", "description": "The complete, self-contained task.", "required": True},
         "write_files": {"type": "boolean", "description": "Allow creating files in the workspace folder."}}))
