"""Core orchestrator.

`Jarvis` wires every subsystem together and is the single entry point used by
the web interface, the command line and (later) agents, voice and automation.
Nothing above this layer touches a store directly, so every change passes
through the safety layer and lands in the audit trail.
"""

from __future__ import annotations

import time

from . import __version__
from .backup import BackupManager
from .common import NotFoundError, ValidationError, utcnow
from .config import Config, load_config
from .db import SCHEMA_VERSION, Database
from .engine import Engine
from .engine.conversation import Conversation
from .logging_setup import get_logger
from .providers import AIProvider, ProviderError, build_provider
from .safety import ActionCategory, SafetyLayer
from .voice import Voice
from .stores.runs import RunStore
from .tools import ToolRegistry, register_builtin, register_claude, register_web
from .stores import (
    AgentStore, ConversationStore, EventLog, ExperienceStore,
    MemoryStore, ProjectStore, SettingsStore, TaskStore,
)

log = get_logger("core")

CORE_AGENT = "jarvis-core"
NO_PROVIDER_NOTICE = (
    "No AI model is connected, so JARVIS cannot answer. Your message has been saved. {detail}"
)

# The only records created automatically. Descriptions are deliberately minimal:
# JARVIS must not invent business information.
INITIAL_PROJECTS = (
    {"name": "Monsoor Motors", "description": "Business workspace."},
    {"name": "Aureus Detailing", "description": "Business workspace."},
)


class Jarvis:
    def __init__(self, config: Config | None = None, provider: AIProvider | None = None):
        self.config = config or load_config()
        self.db = Database(self.config.db_path)
        self.events = EventLog(self.db)
        self.settings = SettingsStore(self.db)
        self.safety = SafetyLayer(self.db, self.events, self.config)
        self.memory = MemoryStore(self.db)
        self.experiences = ExperienceStore(self.db)
        self.tasks = TaskStore(self.db)
        self.projects = ProjectStore(self.db)
        self.agents = AgentStore(self.db)
        self.conversations = ConversationStore(self.db)
        self.backups = BackupManager(self.db, self.config, self.events)
        self.provider = provider or build_provider(self.config)
        self.runs = RunStore(self.db)
        self.tools = ToolRegistry(self)
        register_builtin(self.tools)
        register_web(self.tools)
        register_claude(self.tools)
        self.engine = Engine(self)
        self.voice = Voice(self.config)
        self.conversation = Conversation(self)
        self.started_at = time.time()
        # Record kinds reachable through the generic API below.
        self.stores = {
            "memories": self.memory,
            "experiences": self.experiences,
            "tasks": self.tasks,
            "projects": self.projects,
            "conversations": self.conversations,
        }

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> "Jarvis":
        """Prepare the database. Safe to call on every launch."""
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._backup_before_upgrade()
        self.db.initialize()
        self._seed()
        return self

    def _backup_before_upgrade(self) -> None:
        """Take a safety copy before an existing database is migrated."""
        if not self.config.db_path.exists():
            return
        version = self.db.version()
        if 0 < version < SCHEMA_VERSION:
            self.backups.create(f"pre-upgrade-v{version}", prune=False)

    def announce_startup(self) -> None:
        """Record that the long-running server came up (not every CLI call)."""
        self.events.record("system", "startup",
                           f"JARVIS {__version__} started (schema v{self.db.version()})",
                           details={"ai_provider": self.provider.status().to_dict()})
        interrupted = self.runs.mark_interrupted()
        if interrupted:
            self.events.record("system", "runs.interrupted",
                               f"{interrupted} run(s) were in progress when JARVIS last stopped", level="warning")

    def _seed(self) -> None:
        """One-time creation of the initial records."""
        if self.settings.get("system.seeded"):
            return
        for project in INITIAL_PROJECTS:
            if not self.projects.get_by_name(project["name"]):
                self.projects.create({**project, "category": "business", "source": "user:initial-setup",
                                      "verification_status": "user_provided"})
        if not self.agents.get_by_name(CORE_AGENT):
            self.agents.create({"name": CORE_AGENT, "kind": "core", "status": "active",
                                "description": "Core orchestrator.", "category": "system",
                                "source": "system", "verification_status": "verified"})
        self.settings.set("system.seeded", True, category="system", source="system")
        self.events.record("system", "seed", "Initial projects and core agent created")

    # --- generic record operations ----------------------------------------
    def _store(self, kind: str):
        try:
            return self.stores[kind]
        except KeyError:
            raise NotFoundError(f"Unknown record type: {kind}") from None

    @staticmethod
    def _title(record: dict) -> str:
        value = record.get("title") or record.get("name") or record.get("content") or ""
        return value if len(value) <= 80 else value[:77] + "..."

    def _write(self, action: str, summary: str, actor: str = "user") -> None:
        self.safety.authorize(action, ActionCategory.WRITE, summary, actor=actor)

    def _audit(self, action: str, message: str, record: dict | None = None, actor: str = "user") -> None:
        self.events.record("audit", action, message, actor=actor,
                           details={"id": record["id"]} if record else None)

    def list(self, kind: str, **filters) -> list[dict]:
        return self._store(kind).list(**filters)

    def get(self, kind: str, record_id: int) -> dict:
        store = self._store(kind)
        if kind == "conversations":
            return store.get_with_messages(record_id)
        return store.get(record_id)

    def create(self, kind: str, data: dict, actor: str = "user") -> dict:
        store = self._store(kind)
        self._write(f"{store.label}.create", f"Create {store.label}", actor)
        record = store.create(data)
        self._audit(f"{store.label}.create", f"Created {store.label} #{record['id']}: {self._title(record)}",
                    record, actor)
        return record

    def update(self, kind: str, record_id: int, changes: dict, actor: str = "user") -> dict:
        store = self._store(kind)
        self._write(f"{store.label}.update", f"Update {store.label} #{record_id}", actor)
        record = store.update(record_id, changes)
        self._audit(f"{store.label}.update",
                    f"Updated {store.label} #{record_id} ({', '.join(sorted(changes)) or 'no changes'})",
                    record, actor)
        return record

    def archive(self, kind: str, record_id: int, actor: str = "user") -> dict:
        store = self._store(kind)
        self._write(f"{store.label}.archive", f"Archive {store.label} #{record_id}", actor)
        record = store.archive(record_id)
        self._audit(f"{store.label}.archive", f"Archived {store.label} #{record_id}: {self._title(record)}",
                    record, actor)
        return record

    def restore(self, kind: str, record_id: int, actor: str = "user") -> dict:
        store = self._store(kind)
        self._write(f"{store.label}.restore", f"Restore {store.label} #{record_id}", actor)
        record = store.restore(record_id)
        self._audit(f"{store.label}.restore", f"Restored {store.label} #{record_id}: {self._title(record)}",
                    record, actor)
        return record

    def delete(self, kind: str, record_id: int, approval_id: int | None = None, actor: str = "user") -> dict:
        """Permanently delete a record. Destructive: needs an approval.

        Without `approval_id` nothing is deleted and the pending approval is
        returned. Archiving is the reversible alternative.
        """
        store = self._store(kind)
        record = store.get(record_id)
        decision = self.safety.authorize(
            f"{store.label}.delete", ActionCategory.DESTRUCTIVE,
            f"Permanently delete {store.label} #{record_id}: {self._title(record)}",
            details={"kind": kind, "id": record_id}, actor=actor, approval_id=approval_id,
        )
        if decision.requires_approval:
            return {"status": "approval_required", "approval": decision.approval}
        store.delete(record_id)
        self._audit(f"{store.label}.delete",
                    f"Permanently deleted {store.label} #{record_id}: {self._title(record)}", record, actor)
        return {"status": "deleted", "kind": kind, "id": record_id}

    # --- tasks and learning -----------------------------------------------
    def complete_task(self, task_id: int, lesson: str = "", outcome: str = "success",
                      actor: str = "user") -> dict:
        """Mark a task done. If a lesson is supplied, store it as an experience."""
        self._write("task.complete", f"Complete task #{task_id}", actor)
        task = self.tasks.complete(task_id)
        self._audit("task.complete", f"Completed task #{task_id}: {self._title(task)}", task, actor)
        experience = None
        if lesson and lesson.strip():
            experience = self.create("experiences", {
                "title": f"Task completed: {task['title']}"[:300],
                "outcome": outcome,
                "lesson": lesson,
                "category": "task",
                "source": f"task:{task_id}",
                "project_id": task["project_id"],
                "task_id": task_id,
            }, actor)
        return {"task": task, "experience": experience}

    def reopen_task(self, task_id: int, actor: str = "user") -> dict:
        self._write("task.reopen", f"Reopen task #{task_id}", actor)
        task = self.tasks.reopen(task_id)
        self._audit("task.reopen", f"Reopened task #{task_id}: {self._title(task)}", task, actor)
        return task

    # --- chat --------------------------------------------------------------
    def chat(self, text: str, conversation_id: int | None = None) -> dict:
        """Store the user's message and JARVIS's reply.

        JARVIS decides whether to just answer or to carry out an action through
        the reasoning engine (see `engine/conversation.py`). With no provider, a
        clearly labelled system notice is stored instead.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("message is required")
        self._write("chat.message", "Send chat message")
        if conversation_id is None:
            title = text.strip().splitlines()[0][:60]
            conversation_id = self.conversations.create({"title": title, "source": "user"})["id"]
        user_message = self.conversations.add_message(conversation_id, "user", text)

        status = self.provider.status()
        if not (status.configured and status.available):
            reply = self.conversations.add_message(
                conversation_id, "system", NO_PROVIDER_NOTICE.format(detail=status.detail).strip())
        else:
            try:
                reply = self.conversation.respond(conversation_id, text)
            except ProviderError as exc:
                log.warning("AI provider failed: %s", exc)
                self.events.record("ai", "provider.error", str(exc), level="error")
                reply = self.conversations.add_message(
                    conversation_id, "system", f"The AI provider failed, so there is no answer: {exc}")

        return {
            "conversation": self.conversations.get(conversation_id),
            "user_message": user_message,
            "reply": reply,
            "ai": self.provider.status().to_dict(),
        }

    # --- backups -----------------------------------------------------------
    def create_backup(self, label: str = "manual", actor: str = "user") -> dict:
        self._write("backup.create", "Create database backup", actor)
        return self.backups.create(label)

    def restore_backup(self, name: str, approval_id: int | None = None, actor: str = "user") -> dict:
        """Replace the live database with a backup. Destructive: needs approval."""
        self.backups._resolve(name)
        decision = self.safety.authorize(
            "backup.restore", ActionCategory.DESTRUCTIVE,
            f"Replace the current database with backup {name}",
            details={"backup": name}, actor=actor, approval_id=approval_id,
        )
        if decision.requires_approval:
            return {"status": "approval_required", "approval": decision.approval}
        return {"status": "restored", **self.backups.restore(name)}

    # --- reporting ---------------------------------------------------------
    def counts(self) -> dict:
        return {
            "memories": self.memory.count(),
            "experiences": self.experiences.count(),
            "projects": self.projects.count(),
            "tasks_open": self.tasks.open_count(),
            "tasks_completed": self.tasks.count(status="completed"),
            "conversations": self.conversations.count(),
            "agents": self.agents.count(),
            "events": self.events.count(),
            "tools": len(self.tools.names()),
            "tool_executions": self.runs.count_steps(),
            "pending_approvals": len(self.safety.list_approvals("pending")),
        }

    def status(self) -> dict:
        backups = self.backups.list()
        return {
            "name": "JARVIS",
            "version": __version__,
            "environment": self.config.env,
            "time": utcnow(),
            "uptime_seconds": int(time.time() - self.started_at),
            "ai": self.provider.status().to_dict(),
            "database": {
                "path": str(self.config.db_path),
                "schema_version": self.db.version(),
                "expected_schema_version": SCHEMA_VERSION,
                "size_bytes": self.db.size_bytes(),
                "integrity_ok": self.db.integrity_ok(),
            },
            "safety": self.safety.policy(),
            "voice": self.voice.status(),
            "backups": {"count": len(backups), "latest": backups[0] if backups else None,
                        "keep": self.config.backup_keep},
            "counts": self.counts(),
            "not_built_yet": ["wake word (hands-free voice)", "autonomous agents", "browser automation",
                              "semantic memory search", "external integrations"],
        }

    def dashboard(self) -> dict:
        return {
            "status": self.status(),
            "open_tasks": [task for task in self.tasks.list(limit=50)
                           if task["status"] in ("pending", "in_progress")][:8],
            "recent_events": self.events.list(limit=10),
            "pending_approvals": self.safety.list_approvals("pending"),
            "projects": self.projects.list(),
        }
