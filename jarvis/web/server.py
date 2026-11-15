"""Local web interface: a small JSON API plus static files.

Built on the standard library's HTTP server. It binds to loopback only and
rejects requests whose Host or Origin header is not this machine, which blocks
other websites from driving the API through the browser.
"""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..common import JarvisError, NotFoundError, PermissionDenied, ValidationError
from ..logging_setup import get_logger
from ..orchestrator import Jarvis

log = get_logger("web")

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 1_000_000
LOCAL_NAMES = ("127.0.0.1", "localhost", "[::1]")
KINDS = "memories|experiences|tasks|projects|conversations"
INT_FILTERS = ("project_id", "task_id")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; "
                                "base-uri 'none'; form-action 'self'"),
}


@dataclass
class Request:
    params: tuple
    query: dict
    body: dict = field(default_factory=dict)
    raw: bytes = b""            # audio uploads
    content_type: str = ""


@dataclass
class Raw:
    """A non-JSON response, such as audio."""
    data: bytes
    content_type: str


RAW_ROUTES = {"/api/voice/transcribe", "/api/files"}   # these take binary bodies, not JSON


ROUTES: list[tuple[str, re.Pattern, callable]] = []


def route(method: str, pattern: str):
    def register(handler):
        ROUTES.append((method, re.compile(f"^{pattern}$"), handler))
        return handler
    return register


def _int(value, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be a whole number") from None


def _list_filters(query: dict) -> dict:
    filters = {}
    for key, value in query.items():
        if key == "q":
            filters["query"] = value
        elif key == "active":
            if value not in ("true", "false", "all"):
                raise ValidationError("active must be true, false or all")
            filters["active"] = {"true": True, "false": False, "all": None}[value]
        elif key in ("limit", "offset") or key in INT_FILTERS:
            filters[key] = _int(value, key)
        else:
            filters[key] = value
    return filters


def _destructive(result: dict):
    """202 means 'not done: waiting for the human to approve'."""
    return (202 if result["status"] == "approval_required" else 200), result


# --- status ---------------------------------------------------------------
@route("GET", "/api/status")
def _status(app: Jarvis, req: Request):
    return app.status()


@route("GET", "/api/dashboard")
def _dashboard(app: Jarvis, req: Request):
    return app.dashboard()


# --- tasks (specific routes first) ----------------------------------------
@route("POST", r"/api/tasks/(\d+)/complete")
def _task_complete(app: Jarvis, req: Request):
    return app.complete_task(int(req.params[0]), lesson=req.body.get("lesson", ""),
                             outcome=req.body.get("outcome", "success"))


@route("POST", r"/api/tasks/(\d+)/reopen")
def _task_reopen(app: Jarvis, req: Request):
    return app.reopen_task(int(req.params[0]))


# --- generic records ------------------------------------------------------
@route("GET", f"/api/({KINDS})")
def _list(app: Jarvis, req: Request):
    return {"items": app.list(req.params[0], **_list_filters(req.query))}


@route("POST", f"/api/({KINDS})")
def _create(app: Jarvis, req: Request):
    return 201, app.create(req.params[0], req.body)


@route("GET", rf"/api/({KINDS})/(\d+)")
def _get(app: Jarvis, req: Request):
    return app.get(req.params[0], int(req.params[1]))


@route("PATCH", rf"/api/({KINDS})/(\d+)")
def _update(app: Jarvis, req: Request):
    return app.update(req.params[0], int(req.params[1]), req.body)


@route("DELETE", rf"/api/({KINDS})/(\d+)")
def _delete(app: Jarvis, req: Request):
    approval = req.query.get("approval_id")
    return _destructive(app.delete(req.params[0], int(req.params[1]),
                                   approval_id=_int(approval, "approval_id") if approval else None))


@route("POST", rf"/api/({KINDS})/(\d+)/(archive|restore)")
def _archive(app: Jarvis, req: Request):
    action = app.archive if req.params[2] == "archive" else app.restore
    return action(req.params[0], int(req.params[1]))


# --- chat -----------------------------------------------------------------
@route("POST", "/api/chat")
def _chat(app: Jarvis, req: Request):
    conversation_id = req.body.get("conversation_id")
    if conversation_id is not None:
        conversation_id = _int(conversation_id, "conversation_id")
    attachments = req.body.get("attachments") or []
    if not isinstance(attachments, list) or not all(isinstance(a, str) for a in attachments):
        raise ValidationError("attachments must be a list of uploaded file paths")
    return app.chat(req.body.get("message", ""), conversation_id, attachments=attachments[:10])


# --- tools and run log ----------------------------------------------------
@route("GET", "/api/tools")
def _tools(app: Jarvis, req: Request):
    return {"items": app.tools.list(req.query.get("permission"))}


@route("POST", r"/api/tools/([a-z0-9_.]+)/execute")
def _tool_execute(app: Jarvis, req: Request):
    approval, run = req.body.get("approval_id"), req.body.get("run_id")
    result = app.tools.execute(
        req.params[0], req.body.get("inputs"),
        approval_id=_int(approval, "approval_id") if approval is not None else None,
        run_id=_int(run, "run_id") if run is not None else None)
    return (202 if result["status"] == "approval_required" else 200), result


@route("GET", "/api/learn")
def _learn_status(app: Jarvis, req: Request):
    """Continuous learning: on or off, how often, the last pass and recent topics."""
    return app.learner.status()


@route("POST", "/api/learn/run")
def _learn_now(app: Jarvis, req: Request):
    """Start one learning pass now, in the background; poll GET /api/learn for the result."""
    import threading
    threading.Thread(target=app.learner.once, name="jarvis-learn-now", daemon=True).start()
    return {"started": True}


@route("GET", "/api/self-review")
def _selfreview_status(app: Jarvis, req: Request):
    """Weekly self-review: on or off, the last pass, and proposal branches waiting for the owner."""
    return app.selfreview.status()


@route("POST", "/api/self-review/run")
def _selfreview_now(app: Jarvis, req: Request):
    """Start a self-review pass now, in the background; poll GET /api/self-review."""
    import threading
    threading.Thread(target=app.selfreview.once, name="jarvis-selfreview-now", daemon=True).start()
    return {"started": True}


@route("POST", r"/api/self-review/(jarvis(?:/|%2F)self-review-[0-9-]+)/(approve|reject)")
def _selfreview_decide(app: Jarvis, req: Request):
    # Owner action: requests to this server come from the human at the keyboard. No tool exposes this.
    from urllib.parse import unquote
    branch = unquote(req.params[0])
    try:
        result = app.selfreview.approve(branch) if req.params[1] == "approve" else app.selfreview.reject(branch)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None
    return (200 if result.get("ok") else 409), result


@route("GET", "/api/live")
def _live(app: Jarvis, req: Request):
    """JARVIS's current state for the face and core, derived from real runs."""
    return app.engine.live()


IDENTITY_ASSETS = ("base.png", "listening.png", "analysing.png", "planning.png", "executing.png",
                   "concerned.png", "resolute.png", "approval.png", "success.png", "warning.png",
                   "error.png", "critical.png", "idle.mp4", "thinking.mp4", "executing.mp4")


@route("GET", "/api/identity/assets")
def _identity_assets(app: Jarvis, req: Request):
    """Which rendered character files exist, so the face uses art only where it is present."""
    folder = STATIC_DIR / "identity"
    return {"base": "/static/identity/",
            "files": [name for name in IDENTITY_ASSETS if (folder / name).is_file()]}


@route("GET", r"/api/files/(.+)")
def _workspace_file(app: Jarvis, req: Request):
    """A file JARVIS made (such as a generated picture). Only files inside the workspace."""
    from urllib.parse import unquote
    workspace = Path(app.config.workspace_dir).resolve()
    target = (workspace / unquote(req.params[0])).resolve()
    if not target.is_relative_to(workspace) or target == workspace:
        raise PermissionDenied("Only files inside JARVIS's workspace can be served")
    if not target.is_file():
        raise NotFoundError("No such file in the workspace")
    kind = mimetypes.guess_type(target.name)[0] or ""
    # Never run workspace HTML, SVG or scripts on JARVIS's own origin: only plain pictures show inline.
    safe = kind in ("image/png", "image/jpeg", "image/webp", "image/gif", "text/plain")
    return Raw(target.read_bytes(), kind if safe else "application/octet-stream")


@route("GET", "/api/runs")
def _runs(app: Jarvis, req: Request):
    return {"items": app.runs.list(limit=_int(req.query.get("limit", 50), "limit"),
                                   status=req.query.get("status"), kind=req.query.get("kind"))}


@route("POST", "/api/runs")
def _run_start(app: Jarvis, req: Request):
    """Submit a goal. Runs until it completes, fails, is blocked or needs approval."""
    return 201, app.engine.start(req.body.get("goal", ""))


@route("GET", r"/api/runs/(\d+)")
def _run(app: Jarvis, req: Request):
    run = app.runs.get(int(req.params[0]))
    if run["kind"] == "goal":
        run["report"] = app.engine.report(run["id"])
    return run


@route("POST", r"/api/runs/(\d+)/(resume|cancel)")
def _run_control(app: Jarvis, req: Request):
    run_id = int(req.params[0])
    if req.params[1] == "cancel":
        return app.engine.cancel(run_id)
    return app.engine.resume(run_id, answer=req.body.get("answer"))


@route("GET", "/api/executions")
def _executions(app: Jarvis, req: Request):
    return {"items": app.runs.history(limit=_int(req.query.get("limit", 50), "limit"),
                                      tool=req.query.get("tool"), status=req.query.get("status"))}


# --- voice ----------------------------------------------------------------
@route("GET", "/api/voice/status")
def _voice_status(app: Jarvis, req: Request):
    return app.voice.status()


@route("POST", "/api/voice/transcribe")
def _voice_transcribe(app: Jarvis, req: Request):
    """Body: the recorded audio itself. Returns the words heard; nothing is stored."""
    return {"text": app.voice.transcribe(req.raw, req.content_type or "application/octet-stream")}


@route("POST", "/api/files")
def _upload(app: Jarvis, req: Request):
    """Body: the file itself; ?name= its original name. Stored inertly in the workspace, never run."""
    from ..uploads import save_upload
    return 201, save_upload(app, req.query.get("name", "file"), req.raw)


@route("POST", "/api/voice/speak")
def _voice_speak(app: Jarvis, req: Request):
    return Raw(app.voice.speak(req.body.get("text", "")), "audio/mp4")


# --- system ---------------------------------------------------------------
@route("GET", "/api/agents")
def _agents(app: Jarvis, req: Request):
    return {"items": app.agents.list(active=None)}


@route("GET", "/api/events")
def _events(app: Jarvis, req: Request):
    return {"items": app.events.list(limit=_int(req.query.get("limit", 100), "limit"),
                                     category=req.query.get("category"))}


@route("GET", "/api/approvals")
def _approvals(app: Jarvis, req: Request):
    return {"items": app.safety.list_approvals(req.query.get("status"))}


@route("POST", r"/api/approvals/(\d+)/(approve|deny)")
def _decide(app: Jarvis, req: Request):
    # Requests to this server come from the human at the keyboard.
    decide = app.safety.approve if req.params[1] == "approve" else app.safety.deny
    return decide(int(req.params[0]))


@route("GET", "/api/backups")
def _backups(app: Jarvis, req: Request):
    return {"items": app.backups.list()}


@route("POST", "/api/backups")
def _backup_create(app: Jarvis, req: Request):
    return 201, app.create_backup(req.body.get("label", "manual"))


class Handler(BaseHTTPRequestHandler):
    server_version = "JARVIS"

    def log_message(self, format, *args):  # noqa: A002 - signature set by the base class
        log.debug("%s %s", self.address_string(), format % args)

    # --- responses ---------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload):
        self._send(status, json.dumps(payload, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str):
        self._json(status, {"error": message})

    # --- request checks ----------------------------------------------------
    def _is_local_request(self) -> bool:
        host = self.headers.get("Host", "")
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        if name not in LOCAL_NAMES:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in (f"http://{host}",)

    def _read_raw(self) -> bytes:
        from ..uploads import MAX_UPLOAD_BYTES
        from ..voice import MAX_AUDIO_BYTES
        length = _int(self.headers.get("Content-Length") or 0, "Content-Length")
        limit = MAX_UPLOAD_BYTES if urlparse(self.path).path == "/api/files" else MAX_AUDIO_BYTES
        if length > limit:
            raise ValidationError(f"that file is too large (the limit is {limit // 1_000_000} MB)")
        return self.rfile.read(length) if length else b""

    def _read_body(self) -> dict:
        length = _int(self.headers.get("Content-Length") or 0, "Content-Length")
        if length > MAX_BODY_BYTES:
            raise ValidationError("request body is too large")
        if length == 0:
            return {}
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise ValidationError("request body must be application/json")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            raise ValidationError("request body is not valid JSON") from None
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")
        return body

    # --- dispatch ----------------------------------------------------------
    def _handle(self):
        if not self._is_local_request():
            return self._error(403, "JARVIS only accepts requests from this machine")
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            if self.command not in ("GET", "HEAD"):
                return self._error(405, "method not allowed")
            return self._static(url.path)
        try:
            raw = self._read_raw() if self.command == "POST" and url.path in RAW_ROUTES else b""
            body = self._read_body() if self.command in ("POST", "PATCH", "DELETE") and not raw \
                and url.path not in RAW_ROUTES else {}
            query = {key: values[-1] for key, values in parse_qs(url.query).items()}
            path_known = False
            for method, pattern, handler in ROUTES:
                match = pattern.match(url.path)
                if not match:
                    continue
                path_known = True
                if method != self.command:
                    continue
                result = handler(self.server.app, Request(match.groups(), query, body, raw,
                                                          self.headers.get("Content-Type", "")))
                if isinstance(result, Raw):
                    return self._send(200, result.data, result.content_type)
                status, payload = result if isinstance(result, tuple) else (200, result)
                return self._json(status, payload)
            return self._error(405 if path_known else 404,
                               "method not allowed" if path_known else "not found")
        except ValidationError as exc:
            self._error(400, str(exc))
        except NotFoundError as exc:
            self._error(404, str(exc))
        except PermissionDenied as exc:
            self._error(403, str(exc))
        except JarvisError as exc:
            self._error(400, str(exc))
        except Exception:  # noqa: BLE001 - last line of defence for a request
            log.exception("Unhandled error for %s %s", self.command, self.path)
            self._error(500, "Internal error. See data/logs/jarvis.log.")

    def _static(self, path: str):
        name = "index.html" if path in ("", "/") else path.removeprefix("/static/")
        target = (STATIC_DIR / name).resolve()
        if (path not in ("", "/") and not path.startswith("/static/")) \
                or STATIC_DIR not in target.parents or not target.is_file():
            return self._error(404, "not found")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type.endswith(("javascript", "json")):
            content_type += "; charset=utf-8"
        self._send(200, target.read_bytes(), content_type, cache="no-cache")

    do_GET = do_HEAD = do_POST = do_PATCH = do_DELETE = _handle


class JarvisServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, app: Jarvis, host: str, port: int):
        self.app = app
        super().__init__((host, port), Handler)


def create_server(app: Jarvis, host: str | None = None, port: int | None = None) -> JarvisServer:
    return JarvisServer(app, host or app.config.host, app.config.port if port is None else port)
