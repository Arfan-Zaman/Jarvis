"""Pictures on Higgsfield, made through Claude Code.

"Jarvis, make me a picture of ..." is two steps, so the owner always knows the
price before anything is spent:

1. `image.quote` (automatic): Claude Code asks Higgsfield for the balance and the
   price with `generate_image` `get_cost: true`, which submits nothing.
2. `image.generate` (financial: the safety layer asks the owner every time): the
   approved price is passed as `max_credits`. Claude Code checks the price again,
   refuses if it is higher, submits one image with credits (never the trial
   "unlimited" allowance, never a purchase), waits, and returns the image's URL.
   JARVIS downloads it into `workspace/images/` itself.

Claude Code runs headless as in `claude.py`, but its only MCP server is
Higgsfield (from the project's `.mcp.json`) and its only tools are the four
Higgsfield ones below: no shell, no files, no web.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from ..common import JarvisError, ValidationError
from ..safety import ActionCategory
from .claude import NEVER, WRITE_TOOLS, claude_binary
from .registry import Tool, ToolRegistry

MODEL = os.environ.get("JARVIS_IMAGE_MODEL", "gpt_image_2_6")
TIMEOUT = int(os.environ.get("JARVIS_IMAGE_TIMEOUT", "600"))
MAX_BYTES = 40_000_000
QUOTE_TOOLS = ["mcp__higgsfield__balance", "mcp__higgsfield__generate_image"]
GENERATE_TOOLS = QUOTE_TOOLS + ["mcp__higgsfield__jobs_wait", "mcp__higgsfield__show_generation_by_ids"]
MCP_FILE = Path(__file__).resolve().parents[2] / ".mcp.json"
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
RULES = ("You are JARVIS's picture maker. Use ONLY the Higgsfield tools you are given. Never buy "
         "anything, never top up, never change a plan, never set use_unlim to true and never use "
         "use_free_gens. Do not call any tool not named below. ")

QUOTE = RULES + """Steps:
1. Call mcp__higgsfield__balance.
2. Call mcp__higgsfield__generate_image with params = {params} . It contains get_cost: true, so it
   submits NOTHING. Never call generate_image without get_cost: true.
Reply with ONLY one JSON object: {{"balance": <credits number>, "cost": <credits number for this
image>, "plan": "<subscription plan>"}}. Use null for anything the tools did not return."""

GENERATE = RULES + """The owner approved spending at most {max_credits} credits on this ONE image.
Steps:
1. Call mcp__higgsfield__generate_image with params = {quote} (get_cost: true: submits nothing).
   If the cost is more than {max_credits}, STOP and reply {{"error": "cost <n> is above the approved {max_credits}"}}.
2. Otherwise call mcp__higgsfield__generate_image once with params = {params} .
   If it returns unlim_choice, adjustments or anything that is not a submitted job, STOP and reply
   {{"error": "<what it said>"}}. Never submit a second time.
3. Call mcp__higgsfield__jobs_wait with the job id until it is finished (call again while it is not;
   use mcp__higgsfield__show_generation_by_ids if you need the result URL).
4. Call mcp__higgsfield__balance.
Reply with ONLY one JSON object: {{"cost": <credits charged>, "job_id": "<id>", "image_url":
"<https URL of the finished image file>", "balance": <credits left>}}, or {{"error": "..."}}."""


def higgsfield_config(path: Path = MCP_FILE) -> str:
    """An --mcp-config holding only the Higgsfield server from the project's .mcp.json."""
    try:
        server = json.loads(path.read_text())["mcpServers"]["higgsfield"]
    except (OSError, ValueError, KeyError, TypeError):
        raise JarvisError(f"No 'higgsfield' MCP server in {path}") from None
    return json.dumps({"mcpServers": {"higgsfield": server}})


def command(binary: str, prompt: str, allowed: list[str]) -> list[str]:
    blocked = NEVER + WRITE_TOOLS + ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]   # bare names: deny everywhere
    return [binary, "-p", "--output-format", "json", "--permission-mode", "default",
            "--allowedTools", ",".join(allowed), "--disallowedTools", ",".join(dict.fromkeys(blocked)),
            "--strict-mcp-config", "--mcp-config", higgsfield_config(), "--setting-sources", "project",
            "--no-session-persistence", "--", prompt]


def _ask_claude(app, prompt: str, allowed: list[str], runner) -> dict:
    binary = claude_binary()
    if not binary:
        raise JarvisError("Claude Code is not installed (set JARVIS_CLAUDE_BIN or put `claude` on PATH)")
    workspace = Path(app.config.workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
    try:
        done = (runner or subprocess.run)(command(binary, prompt, allowed), cwd=str(workspace), capture_output=True, text=True,
                      timeout=TIMEOUT, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise JarvisError(f"Higgsfield did not finish within {TIMEOUT // 60} minutes") from None
    try:
        reply = json.loads(done.stdout)
    except (json.JSONDecodeError, TypeError):
        detail = (done.stderr or done.stdout or "").strip()[-300:]
        raise JarvisError(f"Claude Code failed (exit {done.returncode}): {detail or 'no output'}") from None
    if reply.get("is_error") or done.returncode:
        raise JarvisError(f"Claude Code reported an error: {str(reply.get('result') or reply)[:300]}")
    text = str(reply.get("result", ""))
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start:end + 1]) if start >= 0 else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise JarvisError(f"Higgsfield gave no clear answer: {text[:300]}")
    if data.get("error"):
        raise JarvisError(f"Higgsfield: {str(data['error'])[:300]}")
    return data


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _params(inputs: dict, get_cost: bool) -> dict:
    prompt = inputs["prompt"].strip()
    if not prompt:
        raise ValidationError("image: 'prompt' is empty")
    params = {"model": inputs.get("model") or MODEL, "prompt": prompt[:4000],
              "aspect_ratio": inputs.get("aspect_ratio") or "1:1", "quality": inputs.get("quality") or "high",
              "resolution": inputs.get("resolution") or "2k", "count": 1}
    return {**params, "get_cost": True} if get_cost else {**params, "use_unlim": False}


def image_quote(app, inputs, actor, runner=None):
    """The price and the balance. Submits nothing and spends nothing."""
    data = _ask_claude(app, QUOTE.format(params=json.dumps(_params(inputs, True))), QUOTE_TOOLS, runner)
    cost, balance = _number(data.get("cost")), _number(data.get("balance"))
    if cost is None:
        raise JarvisError("Higgsfield did not say what this picture would cost")
    return {"cost": cost, "balance": balance, "plan": data.get("plan"),
            "affordable": balance is not None and balance >= cost, "model": inputs.get("model") or MODEL}


def slug(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:6]
    return ("-".join(words) or "image")[:40].strip("-") or "image"


def download(url: str) -> tuple[bytes, str]:
    if not url.startswith("https://"):
        raise JarvisError("Higgsfield returned no https image link")
    request = urllib.request.Request(url, headers={"User-Agent": "jarvis-image/1"})
    with urllib.request.urlopen(request, timeout=120) as response:   # noqa: S310 - https only
        data = response.read(MAX_BYTES + 1)
        kind = response.headers.get_content_type()
    if len(data) > MAX_BYTES:
        raise JarvisError("The image is too large to download")
    return data, kind


def image_generate(app, inputs, actor, runner=None, fetch=None):
    """Make one picture for at most `max_credits` (the approved price) and save it."""
    limit = inputs["max_credits"]
    if limit <= 0:
        raise ValidationError("image.generate: 'max_credits' must be the quoted cost (above 0)")
    prompt = GENERATE.format(max_credits=limit, quote=json.dumps(_params(inputs, True)),
                             params=json.dumps(_params(inputs, False)))
    data = _ask_claude(app, prompt, GENERATE_TOOLS, runner)
    cost, balance = _number(data.get("cost")), _number(data.get("balance"))
    url = str(data.get("image_url") or "")
    over = f" WARNING: Higgsfield charged {cost}, above the approved {limit}." if cost is not None and cost > limit else ""
    try:
        body, kind = (fetch or download)(url)
    except (OSError, ValueError, JarvisError) as exc:   # credits are already spent: keep the link
        raise JarvisError(f"The picture was made ({cost} credits, {balance} left) but downloading it "
                          f"failed: {exc}. Link: {url[:300]}") from None
    if not kind.startswith("image/"):
        raise JarvisError(f"Higgsfield's link was not an image ({kind}): {url[:200]}")
    folder = Path(app.config.workspace_dir) / "images"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(inputs['prompt'])}.{EXTENSIONS.get(kind, 'png')}"
    target.write_bytes(body)
    return {"path": str(target), "file_url": f"/api/files/images/{target.name}", "image_url": url,
            "job_id": data.get("job_id"), "cost": cost, "approved_max": limit, "balance": balance,
            "note": over.strip() or None}


IMAGE_INPUTS = {
    "prompt": {"type": "string", "description": "What the picture should show.", "required": True},
    "aspect_ratio": {"type": "string", "description": "Shape, such as 1:1, 16:9 or 9:16.", "default": "1:1"},
    "quality": {"type": "string", "description": "Image quality.", "default": "high"},
    "resolution": {"type": "string", "description": "Image resolution.", "default": "2k"},
    "model": {"type": "string", "description": "Higgsfield model id.", "default": MODEL},
}


def register_images(registry: ToolRegistry) -> None:
    registry.register(Tool(
        "image.quote",
        "Find out what one Higgsfield picture would cost in credits and how many credits are left. "
        "Spends nothing. Always do this before image.generate.",
        ActionCategory.WEB_READ, image_quote, dict(IMAGE_INPUTS)))
    registry.register(Tool(
        "image.generate",
        "Make a picture on Higgsfield and save it in JARVIS's workspace. Spends credits, so the owner "
        "is asked every time. max_credits must be the cost image.quote returned.",
        ActionCategory.FINANCIAL, image_generate,
        {**IMAGE_INPUTS, "max_credits": {"type": "number", "required": True,
                                         "description": "The approved credit cost from image.quote; never exceeded."}}))
