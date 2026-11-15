"""Everyday Mac tools: instant, no approval, nothing destructive.

- mac.find_files: Spotlight search of the owner's home folder (names and contents).
- mac.status: battery, disk space, network address, uptime and the frontmost apps.
- mac.open: open a website, an app, or a file/folder in the owner's home folder.
- mac.notify: show a macOS notification.

Programs are called with argument lists (never a shell), so text from the owner or a
web page cannot be turned into extra commands. Bigger jobs on the Mac go to
`claude.operate`, which asks the owner first.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..common import JarvisError, ValidationError
from ..safety import ActionCategory
from .registry import Tool, ToolRegistry

READ, WRITE = ActionCategory.READ, ActionCategory.WRITE
HIDDEN = re.compile(r"/(\.[^/]+|Library)(/|$)")          # dot-folders and ~/Library stay out of results


def _run(args: list[str], timeout: int = 15) -> str:
    if not shutil.which(args[0]) and not Path(args[0]).exists():
        raise JarvisError(f"{args[0]} is not available on this Mac")
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise JarvisError(f"{args[0]} took too long") from None
    return done.stdout.strip()


def find_files(app, inputs, actor):
    query = inputs["query"].strip()
    if not query:
        raise ValidationError("mac.find_files: 'query' is empty")
    home = str(Path.home())
    limit = max(1, min(inputs.get("limit", 20), 50))
    found = _run(["mdfind", "-onlyin", home, "-name", query]).splitlines()
    if len(found) < limit:                                   # then by contents
        found += [p for p in _run(["mdfind", "-onlyin", home, query]).splitlines() if p not in found]
    clean = [p for p in found if not HIDDEN.search(p[len(home):])][:limit]
    return {"query": query, "files": [p.replace(home, "~", 1) for p in clean], "more": len(found) > len(clean)}


def status(app, inputs, actor):
    battery = _run(["pmset", "-g", "batt"]).splitlines()
    disk = _run(["df", "-h", str(Path.home())]).splitlines()
    apps = _run(["osascript", "-e", 'tell application "System Events" to get name of (processes where background only is false)'])
    return {
        "battery": battery[-1].split("\t")[-1] if battery else "unknown",
        "disk": disk[-1].split()[1:5] if len(disk) > 1 else [],          # size, used, available, capacity
        "disk_columns": ["size", "used", "available", "capacity"],
        "wifi_ip": _run(["ipconfig", "getifaddr", "en0"]) or "not connected",
        "uptime": _run(["uptime"]),
        "open_apps": [a.strip() for a in apps.split(",") if a.strip()][:30],
    }


def open_thing(app, inputs, actor):
    target = inputs["target"].strip()
    if not target:
        raise ValidationError("mac.open: 'target' is empty")
    if re.match(r"^https?://", target):
        _run(["open", target])
        return {"opened": target, "kind": "website"}
    path = Path(target).expanduser()
    if path.exists():
        home = Path.home().resolve()
        if home not in path.resolve().parents and path.resolve() != home:
            raise ValidationError("JARVIS opens files only inside your home folder")
        if path.suffix in (".app", ".command", ".sh", ".pkg", ".dmg") and not inputs.get("app"):
            raise ValidationError("JARVIS does not open installers or scripts this way")
        _run(["open", str(path)])
        return {"opened": str(path).replace(str(home), "~", 1), "kind": "file"}
    if not re.fullmatch(r"[\w .&'+-]{1,60}", target):
        raise ValidationError(f"not a website, a file or an app name: {target}")
    out = subprocess.run(["open", "-a", target], capture_output=True, text=True, timeout=15)
    if out.returncode:
        raise JarvisError(f"couldn't find an app called {target}")
    return {"opened": target, "kind": "app"}


def notify(app, inputs, actor):
    title = inputs.get("title", "JARVIS")[:80]
    message = inputs["message"][:240]
    # values are passed as arguments to the script, never spliced into its source
    script = 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run'
    _run(["osascript", "-e", script, title, message])
    return {"shown": True}


def register_mac(registry: ToolRegistry) -> None:
    S = lambda d, **x: {"type": "string", "description": d, **x}    # noqa: E731
    for tool in (
        Tool("mac.find_files", "Find files and folders on the owner's Mac by name or content (Spotlight).", READ,
             find_files, {"query": S("What to look for.", required=True),
                          "limit": {"type": "integer", "description": "Most results (up to 50)."}}),
        Tool("mac.status", "Check the Mac: battery, free disk space, network, uptime and open apps.", READ, status),
        Tool("mac.open", "Open a website, an app (by name), or a file or folder in the owner's home folder.", WRITE,
             open_thing, {"target": S("A URL, an app name like Safari, or a path like ~/Downloads/report.pdf.",
                                      required=True)}),
        Tool("mac.notify", "Show a notification on the Mac.", WRITE, notify,
             {"message": S("What it should say.", required=True), "title": S("Its title.")}),
    ):
        registry.register(tool)
