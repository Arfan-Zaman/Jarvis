"""Claude Code as JARVIS's heavy-lifting mind.

The local model is small; hard work (coding, deep research, analysis, long
writing, planning) is handed to Claude Code (`claude -p`) and the answer comes
back as JARVIS's own. The hard lines still hold:

- no shell: Bash is disallowed, so Claude Code cannot run commands;
- files: only inside JARVIS's workspace (`workspace/`), and only when the
  caller asks for `write_files`; otherwise it can only read and search the web;
- no MCP servers, plugins or the owner's personal hooks (`--setting-sources project`):
  they could spend money, message people, or block tools;
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
# Path-scoped rules: a bare "Read" would let Claude read ANY file on the Mac (tested), so a
# poisoned page or upload could make it read ~/.ssh and send it out. "./**" = the workspace only.
READ_TOOLS = ["Read(./**)", "Grep(./**)", "Glob(./**)", "WebSearch", "WebFetch"]
WRITE_TOOLS = ["Edit", "Write", "MultiEdit", "NotebookEdit"]          # names, for denying
WRITE_ALLOW = ["Edit(./**)", "Write(./**)", "MultiEdit(./**)", "NotebookEdit(./**)"]
PLAYWRIGHT_MCP = "@playwright/mcp@0.0.85"                             # pinned, not @latest
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
    allowed = READ_TOOLS + (WRITE_ALLOW if write_files or shell else []) + (["Bash"] if shell else [])
    files = ("You may create and edit files, but only inside the current directory."
             if write_files or shell else "Do not create or change any files.")
    if shell:
        files += (" You may run shell commands, but only inside the current directory: never touch "
                  "files elsewhere, never use sudo, never delete outside it, never send messages or spend money.")
    never = [t for t in NEVER if not (shell and t in ("Bash", "BashOutput", "KillShell"))]
    return [binary, "-p", "--output-format", "json",
            "--permission-mode", "acceptEdits" if write_files or shell else "default",
            "--allowedTools", ",".join(allowed),
            "--disallowedTools", ",".join(never + ([] if write_files or shell else WRITE_TOOLS)),
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "project",
            "--no-session-persistence",
            "--append-system-prompt", BRIEF.format(files=files), "--", task]


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
    # A shell can do anything the owner's account can (read any file, call JARVIS's own API),
    # and Claude Code has no OS sandbox switch here, so this stays off unless deliberately enabled.
    if os.environ.get("JARVIS_OPERATE") != "1":
        raise JarvisError("Full-power mode (claude.operate) is off. It gives Claude Code a shell that can reach "
                          "everything on this Mac; turn it on only if you accept that: JARVIS_OPERATE=1 in .env.")
    return claude_work(app, inputs, actor, runner=runner, shell=True)


RESEARCH = ("Search the web for: {query}\n"
            "Read the best sources. Reply with ONLY one JSON object: "
            '{{"facts": [{{"fact": "...", "url": "..."}}]}} with up to {count} durable, specific, useful '
            "facts, each with the exact URL of the page it came from. No facts you did not read.")


def claude_research(app, inputs, actor, runner=subprocess.run):
    """Full-web research through Claude Code's own web search (the owner's plan; no key, no
    scraping). Read-only: web search and page reading only, on the small fast model."""
    binary = claude_binary()
    if not binary:
        raise JarvisError("Claude Code is not installed")
    query = inputs["query"].strip()
    if not query:
        raise ValidationError("claude.research: 'query' is empty")
    prompt = RESEARCH.format(query=query, count=inputs.get("count", 3))    # no personal context leaves the Mac
    cmd = [binary, "-p", "--output-format", "json", "--model", os.environ.get("JARVIS_RESEARCH_MODEL", "haiku"),
           "--allowedTools", "WebSearch,WebFetch", "--disallowedTools", ",".join(NEVER + WRITE_TOOLS + ["Read", "Grep", "Glob"]),
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "project",
           "--no-session-persistence", "--", prompt]
    workspace = Path(app.config.workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
    try:
        done = runner(cmd, cwd=str(workspace), capture_output=True, text=True, timeout=300, env=env,
                      stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise JarvisError("Claude Code research did not finish within 5 minutes") from None
    try:
        reply = json.loads(done.stdout)
    except (json.JSONDecodeError, TypeError):
        raise JarvisError(f"Claude Code research failed (exit {done.returncode})") from None
    if reply.get("is_error") or done.returncode:
        raise JarvisError(f"Claude Code reported an error: {str(reply.get('result') or reply)[:300]}")
    text = reply.get("result", "")
    start, end = text.find("{"), text.rfind("}")
    try:
        facts = json.loads(text[start:end + 1]).get("facts", []) if start >= 0 else []
    except json.JSONDecodeError:
        facts = []
    clean = [{"fact": str(f.get("fact", "")).strip()[:400], "url": str(f.get("url", "")).strip()}
             for f in facts if isinstance(f, dict) and str(f.get("url", "")).startswith(("http://", "https://"))]
    return {"query": query, "facts": [f for f in clean if len(f["fact"]) >= 15], "cost_usd": reply.get("total_cost_usd")}


BROWSE_RULES = (
    "You are operating a web browser for JARVIS's owner through the Playwright tools. Do the task, then "
    "reply with what you found or did, plainly, with the URLs you used. Hard rules: never buy, pay, "
    "donate or subscribe; never enter passwords, card, bank or ID numbers or personal details; never send "
    "messages, post, comment or submit forms that send something to someone; never accept terms or "
    "create accounts; never download or run files. If the task needs any of that, or a sign-in, stop "
    "and say exactly what is needed. Never solve CAPTCHAs or get around bot checks: stop and report.")


def _npx() -> str | None:
    found = shutil.which("npx")
    if found:
        return found
    for candidate in sorted(Path.home().glob(".nvm/versions/node/*/bin/npx"), reverse=True):
        return str(candidate)
    return None


def claude_browse(app, inputs, actor, runner=subprocess.run):
    """Claude Code drives a real browser (Playwright, a private signed-out profile). Asks first."""
    binary, npx = claude_binary(), _npx()
    if not binary:
        raise JarvisError("Claude Code is not installed")
    if not npx:
        raise JarvisError("Node's npx is not installed, so the browser tool cannot start")
    task = inputs["task"].strip()
    if not task:
        raise ValidationError("claude.browse: 'task' is empty")
    servers = {"mcpServers": {"playwright": {"type": "stdio", "command": npx,
                                             "args": [PLAYWRIGHT_MCP, "--isolated"]}}}
    cmd = [binary, "-p", "--output-format", "json",
           "--allowedTools", "mcp__playwright,WebSearch,WebFetch",
           "--disallowedTools", ",".join(NEVER + WRITE_TOOLS + ["Read", "Grep", "Glob", "mcp__playwright__browser_file_upload"]),
           "--strict-mcp-config", "--mcp-config", json.dumps(servers), "--setting-sources", "project",
           "--no-session-persistence", "--append-system-prompt", BROWSE_RULES, "--", task]
    workspace = Path(app.config.workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
    env["PATH"] = f"{Path(npx).parent}:{env.get('PATH', '')}"
    try:
        done = runner(cmd, cwd=str(workspace), capture_output=True, text=True, timeout=TIMEOUT, env=env,
                      stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise JarvisError(f"The browser task did not finish within {TIMEOUT // 60} minutes") from None
    try:
        reply = json.loads(done.stdout)
    except (json.JSONDecodeError, TypeError):
        raise JarvisError(f"The browser task failed (exit {done.returncode})") from None
    if reply.get("is_error") or done.returncode:
        raise JarvisError(f"Claude Code reported an error: {str(reply.get('result') or reply)[:400]}")
    return {"result": reply.get("result", ""), "turns": reply.get("num_turns"), "cost_usd": reply.get("total_cost_usd")}


def register_claude(registry: ToolRegistry) -> None:
    registry.register(Tool(
        "claude.browse",
        "Use a real web browser like a person would: open sites, search, click, read, fill search boxes, "
        "compare pages, check something on a live website. A private signed-out browser; it never buys, "
        "signs in, sends or posts. Asks the owner first.",
        ActionCategory.SYSTEM, claude_browse,
        {"task": {"type": "string", "description": "The complete browsing task.", "required": True}}))
    registry.register(Tool(
        "claude.research",
        "Research a question on the whole live web through Claude Code's web search and return "
        "short facts, each with its source URL. Read-only.",
        ActionCategory.WEB_READ, claude_research,
        {"query": {"type": "string", "description": "What to research.", "required": True},
         "why": {"type": "string", "description": "Why it matters, to focus the research."},
         "count": {"type": "integer", "description": "How many facts (1 to 5)."}}))
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
