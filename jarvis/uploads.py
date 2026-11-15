"""Files and photos the owner gives JARVIS.

Security: the name is reduced to a safe file name (no folders, no "..", no hidden
files), only common document, image, audio, video and data types are accepted,
the size is capped, and the file is written with exclusive create inside
`workspace/uploads/`. Nothing uploaded is ever executed; Claude Code may read it
(it can view images and PDFs) when the owner asks about it.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .common import ValidationError

MAX_UPLOAD_BYTES = 25_000_000
ALLOWED = {
    "png", "jpg", "jpeg", "gif", "webp", "heic", "bmp", "tiff", "svg",
    "pdf", "txt", "md", "csv", "tsv", "json", "xml", "html", "rtf",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "pages", "numbers", "key",
    "mp3", "m4a", "wav", "aac", "mp4", "mov", "webm",
    "py", "js", "ts", "css", "sql", "yaml", "yml", "log",
}
FOLDER = "uploads"
_REF = re.compile(r"^uploads/[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def safe_name(name: str) -> str:
    base = Path(str(name).replace("\\", "/")).name
    stem, dot, ext = base.rpartition(".")
    ext = ext.lower() if dot else ""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem if dot else base).strip("-._")[:60] or "file"
    if ext not in ALLOWED:
        raise ValidationError(f"JARVIS does not accept .{ext or '(no extension)'} files")
    return f"{stem}.{ext}"


def save_upload(app, name: str, data: bytes) -> dict:
    if not data:
        raise ValidationError("the file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError("that file is too large")
    folder = Path(app.config.workspace_dir) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    final = f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_name(name)}"
    target = folder / final
    with open(target, "xb") as handle:          # never overwrite anything
        handle.write(data)
    app.events.record("files", "file.upload", f"Owner uploaded {final} ({len(data)} bytes)", actor="user")
    return {"path": f"{FOLDER}/{final}", "name": final, "size": len(data)}


def check_refs(app, refs: list[str]) -> list[str]:
    """Only files that really were uploaded (no other paths) may be attached to a message."""
    root = (Path(app.config.workspace_dir) / FOLDER).resolve()
    clean = []
    for ref in refs:
        if not _REF.match(ref):
            raise ValidationError(f"not an uploaded file: {ref}")
        path = (Path(app.config.workspace_dir) / ref).resolve()
        if path.parent != root or not path.is_file():
            raise ValidationError(f"no such uploaded file: {ref}")
        clean.append(ref)
    return clean
