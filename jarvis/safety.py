"""Safety and permission layer.

Every action JARVIS takes is classified into a category:

    read                    always allowed
    web_read                always allowed: searching and reading public web pages
    write                   allowed unless read-only mode is on; audited
    workspace               allowed unless read-only mode is on: writing and running
                            things inside JARVIS's own workspace folder; audited
    destructive             needs explicit human approval, every time
    external_communication  needs explicit human approval, every time
    financial               needs explicit human approval, every time
    system                  needs explicit human approval, every time

High-impact actions follow a two-step protocol:

1. `authorize(...)` without an approval creates a *pending approval* and
   returns a decision with `requires_approval=True`. Nothing is executed.
2. A human approves it (`approve`). The caller then repeats `authorize(...)`
   with the approval id. The approval is bound to the exact action and details
   (a fingerprint), expires after a short time, and can be used only once.

Anything unrecognised is refused (fail closed). Every request, approval,
denial and refusal is written to the audit trail.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .common import NotFoundError, PermissionDenied, utcnow
from .config import Config
from .db import Database
from .stores.events import EventLog

HUMAN = "user"


class ActionCategory(str, Enum):
    READ = "read"
    WEB_READ = "web_read"
    WRITE = "write"
    WORKSPACE = "workspace"
    DESTRUCTIVE = "destructive"
    EXTERNAL_COMMUNICATION = "external_communication"
    FINANCIAL = "financial"
    SYSTEM = "system"


AUTOMATIC = (ActionCategory.READ, ActionCategory.WEB_READ, ActionCategory.WRITE, ActionCategory.WORKSPACE)
APPROVAL_REQUIRED = frozenset({
    ActionCategory.DESTRUCTIVE,
    ActionCategory.EXTERNAL_COMMUNICATION,
    ActionCategory.FINANCIAL,
    ActionCategory.SYSTEM,
})


@dataclass(frozen=True)
class Decision:
    allowed: bool
    requires_approval: bool = False
    reason: str = ""
    approval: dict | None = None


def fingerprint(action: str, category: str, details: dict | None) -> str:
    payload = json.dumps([action, category, details or {}], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SafetyLayer:
    def __init__(self, db: Database, events: EventLog, config: Config):
        self.db = db
        self.events = events
        self.config = config

    # --- the gate ----------------------------------------------------------
    def authorize(self, action: str, category, summary: str, *, details: dict | None = None,
                  actor: str = HUMAN, approval_id: int | None = None) -> Decision:
        """Decide whether `action` may run now.

        Returns an allowed Decision, or one with `requires_approval=True`.
        Raises PermissionDenied when the action is refused outright.
        """
        try:
            category = ActionCategory(category)
        except ValueError:
            self._refuse(action, str(category), actor, "unknown action category", details)

        if category is ActionCategory.READ:
            return Decision(True, reason="read access")
        if category is ActionCategory.WEB_READ:      # reading the public web changes nothing here
            return Decision(True, reason="web read access")

        if not self.config.allow_writes:
            self._refuse(action, category.value, actor,
                         "JARVIS is in read-only mode (JARVIS_ALLOW_WRITES=false)", details)

        if category in (ActionCategory.WRITE, ActionCategory.WORKSPACE):
            return Decision(True, reason=f"{category.value} access")

        if category not in APPROVAL_REQUIRED:  # defensive: new categories fail closed
            self._refuse(action, category.value, actor, "no policy for this category", details)

        print_ = fingerprint(action, category.value, details)
        if approval_id is None:
            approval = self._request(action, category, summary, details, print_, actor)
            return Decision(False, requires_approval=True,
                            reason=f"{category.value} actions need explicit approval", approval=approval)

        self._consume(approval_id, print_, action, category.value, actor, details)
        self.events.record("audit", action, f"Authorised with approval #{approval_id}: {summary}",
                           actor=actor, details={"category": category.value, "approval_id": approval_id,
                                                 **(details or {})})
        return Decision(True, reason=f"approved (#{approval_id})")

    def _refuse(self, action, category, actor, reason, details):
        self.events.record("audit", action, f"Refused: {reason}", level="warning", actor=actor,
                           details={"category": category, **(details or {})})
        raise PermissionDenied(f"{action} refused: {reason}")

    # --- approvals ---------------------------------------------------------
    def _request(self, action, category, summary, details, print_, actor) -> dict:
        now = utcnow()
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO approvals (action, category, summary, details, fingerprint, status, "
                "requested_by, requested_at, expires_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (action, category.value, summary,
                 json.dumps(details, sort_keys=True, default=str) if details else None,
                 print_, actor, now, utcnow(self.config.approval_ttl_minutes)),
            )
            approval_id = cursor.lastrowid
        self.events.record("audit", action, f"Approval #{approval_id} requested: {summary}", actor=actor,
                           details={"category": category.value, "approval_id": approval_id, **(details or {})})
        return self.get_approval(approval_id)

    def _expire_stale(self) -> None:
        now = utcnow()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = 'denied', decided_by = 'system:expired', decided_at = ? "
                "WHERE status IN ('pending', 'approved') AND expires_at < ?",
                (now, now),
            )

    def _consume(self, approval_id, print_, action, category, actor, details) -> None:
        self._expire_stale()
        try:
            approval = self.get_approval(approval_id)
        except NotFoundError:
            self._refuse(action, category, actor, f"approval #{approval_id} does not exist", details)
        if approval["fingerprint"] != print_:
            self._refuse(action, category, actor,
                         f"approval #{approval_id} was granted for a different action", details)
        with self.db.connect() as conn:
            used = conn.execute(
                "UPDATE approvals SET status = 'used', used_at = ? WHERE id = ? AND status = 'approved'",
                (utcnow(), approval_id),
            ).rowcount
        if not used:
            self._refuse(action, category, actor,
                         f"approval #{approval_id} is {approval['status']}, not approved "
                         "(it may be undecided, denied, expired or already used)", details)

    def _decide(self, approval_id: int, status: str, decided_by: str) -> dict:
        if decided_by != HUMAN:
            self.events.record("audit", "approval.decide",
                               f"Refused: {decided_by!r} tried to decide approval #{approval_id}",
                               level="warning", actor=decided_by, details={"approval_id": approval_id})
            raise PermissionDenied("Only the human user can approve or deny actions")
        self._expire_stale()
        approval = self.get_approval(approval_id)
        with self.db.connect() as conn:
            changed = conn.execute(
                "UPDATE approvals SET status = ?, decided_by = ?, decided_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, decided_by, utcnow(), approval_id),
            ).rowcount
        if not changed:
            raise PermissionDenied(
                f"Approval #{approval_id} is already {approval['status']} and cannot be changed"
            )
        self.events.record("audit", approval["action"],
                           f"Approval #{approval_id} {status} by {decided_by}: {approval['summary']}",
                           actor=decided_by, details={"approval_id": approval_id})
        return self.get_approval(approval_id)

    def approve(self, approval_id: int, decided_by: str = HUMAN) -> dict:
        return self._decide(approval_id, "approved", decided_by)

    def deny(self, approval_id: int, decided_by: str = HUMAN) -> dict:
        return self._decide(approval_id, "denied", decided_by)

    def get_approval(self, approval_id: int) -> dict:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Approval {approval_id} not found")
        return self._approval(row)

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[dict]:
        self._expire_stale()
        where, params = ("", [])
        if status:
            where, params = " WHERE status = ?", [status]
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM approvals{where} ORDER BY id DESC LIMIT ?", [*params, limit]
            ).fetchall()
        return [self._approval(row) for row in rows]

    @staticmethod
    def _approval(row) -> dict:
        approval = dict(row)
        approval["details"] = json.loads(approval["details"]) if approval["details"] else None
        return approval

    # --- file-system permissions ------------------------------------------
    def authorize_path(self, path: Path | str, *, write: bool, actor: str = "system") -> Path:
        """Confine file access: reads to the project, writes to the data and workspace dirs.

        Symlinks are resolved first, so a link cannot be used to escape.
        """
        resolved = Path(path).expanduser().resolve()
        roots = [self.config.data_dir, self.config.workspace_dir] if write \
            else [self.config.root, self.config.data_dir, self.config.workspace_dir]
        if write and not self.config.allow_writes:
            self._refuse("file.write", "write", actor, "JARVIS is in read-only mode", {"path": str(resolved)})
        if not any(resolved == root or root in resolved.parents for root in roots):
            mode = "write" if write else "read"
            self._refuse(f"file.{mode}", mode, actor, f"{resolved} is outside the permitted area",
                         {"path": str(resolved)})
        return resolved

    def policy(self) -> dict:
        return {
            "read_only": not self.config.allow_writes,
            "automatic": [category.value for category in AUTOMATIC],
            "approval_required_for": sorted(category.value for category in APPROVAL_REQUIRED),
            "workspace": str(self.config.workspace_dir),
            "approval_ttl_minutes": self.config.approval_ttl_minutes,
            "external_ai_allowed": self.config.allow_external_ai,
        }
