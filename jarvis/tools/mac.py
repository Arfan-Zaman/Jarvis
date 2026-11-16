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


KINDS = {"pdf": "com.adobe.pdf", "image": "public.image", "photo": "public.image", "video": "public.movie",
         "audio": "public.audio", "document": "public.content", "spreadsheet": "public.spreadsheet",
         "presentation": "public.presentation", "text": "public.text", "folder": "public.folder", "app": "com.apple.application"}


def find_files(app, inputs, actor):
    """Spotlight search in the owner's home folder: by name or content, optionally in one folder,
    of one kind (pdf, image, video, ...), newest first."""
    query = (inputs.get("query") or "").strip()
    kind = (inputs.get("kind") or "").strip().lower().rstrip("s")
    home = Path.home()
    folder = Path(inputs.get("folder") or "~").expanduser().resolve()
    if folder != home.resolve() and home.resolve() not in folder.parents:
        raise ValidationError("JARVIS searches only inside your home folder")
    if not folder.is_dir():
        raise ValidationError(f"no such folder: {inputs.get('folder')}")
    if not query and not kind:
        raise ValidationError("mac.find_files: give a query, a kind, or both")
    limit = max(1, min(inputs.get("limit", 20), 50))
    clauses = []
    if kind:
        uti = KINDS.get(kind)
        clauses.append(f'kMDItemContentTypeTree == "{uti}"' if uti else f'kMDItemFSName == "*.{kind}"c')
    if query:
        safe = query.replace("\\", " ").replace('"', " ")
        clauses.append(f'(kMDItemFSName == "*{safe}*"cd || kMDItemTextContent == "*{safe}*"cd)')
    found = _run(["mdfind", "-onlyin", str(folder), " && ".join(clauses)], timeout=20).splitlines()
    found = [f for f in found if not HIDDEN.search(f[len(str(home)):])]
    if inputs.get("newest", True):
        def mtime(path):
            try:
                return Path(path).stat().st_mtime
            except OSError:
                return 0
        named = (lambda f: query.lower() in Path(f).name.lower()) if query else (lambda f: True)
        found.sort(key=lambda f: (named(f), mtime(f)), reverse=True)          # name matches first, then newest
    from datetime import datetime
    def info(path):
        try:
            st = Path(path).stat()
            return {"path": path.replace(str(home), "~", 1), "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "size_kb": round(st.st_size / 1024)}
        except OSError:
            return {"path": path.replace(str(home), "~", 1)}
    return {"query": query, "kind": kind or None, "folder": str(folder).replace(str(home), "~", 1),
            "files": [info(f) for f in found[:limit]], "total": len(found)}


def status(app, inputs, actor):
    battery = _run(["pmset", "-g", "batt"]).splitlines()
    disk = _run(["df", "-h", str(Path.home())]).splitlines()
    apps = _run(["osascript", "-e", 'tell application "System Events" to get name of (processes where background only is false)'])
    cols = disk[-1].split() if len(disk) > 1 else []
    gb = lambda v: v.replace("Gi", " GB").replace("Ti", " TB").replace("Mi", " MB")    # noqa: E731
    return {
        "battery": battery[-1].split("\t")[-1].split(" present")[0] if battery else "unknown",
        "disk_free": gb(cols[3]) if len(cols) > 4 else "unknown",
        "disk_used": gb(cols[2]) if len(cols) > 4 else "unknown",
        "disk_total": gb(cols[1]) if len(cols) > 4 else "unknown",
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
        Tool("mac.find_files", "Find files on the owner's Mac (Spotlight), newest first: by name or content, in one "
             "folder (e.g. ~/Downloads, ~/Desktop, ~/Documents), of one kind (pdf, image, video, audio, spreadsheet, "
             "presentation, text, folder, or a file extension). 'The latest PDF in Downloads' = kind pdf, folder ~/Downloads, limit 1.",
             READ, find_files, {"query": S("Words in the name or content (optional)."),
                                "folder": S("Folder to search, like ~/Downloads (default: the whole home folder)."),
                                "kind": S("pdf, image, video, audio, spreadsheet, presentation, text, folder or an extension."),
                                "newest": {"type": "boolean", "description": "Newest first (default true)."},
                                "limit": {"type": "integer", "description": "Most results (up to 50)."}}),
        Tool("mac.status", "Check the Mac: battery, free disk space, network, uptime and open apps.", READ, status),
        Tool("mac.open", "Open a website, an app (by name), or a file or folder in the owner's home folder.", WRITE,
             open_thing, {"target": S("A URL, an app name like Safari, or a path like ~/Downloads/report.pdf.",
                                      required=True)}),
        Tool("mac.notify", "Show a notification on the Mac.", WRITE, notify,
             {"message": S("What it should say.", required=True), "title": S("Its title.")}),
    ):
        registry.register(tool)


def describe_status(data: dict) -> str:
    """One plain spoken answer from mac.status, with the numbers labelled correctly."""
    battery = data.get("battery", "unknown").replace(";", ",").strip()
    return (f"Battery: {battery}. Disk: {data.get('disk_free')} free of {data.get('disk_total')} "
            f"({data.get('disk_used')} used). Wi-Fi address: {data.get('wifi_ip')}.")
