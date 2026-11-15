"""The concrete record stores: memory, experience/learning, tasks, projects,
agents."""

from __future__ import annotations

import re

from ..common import ValidationError, choice, optional_id, optional_timestamp, text, utcnow
from .base import Store

TASK_STATUSES = ("pending", "in_progress", "completed", "cancelled")
TASK_PRIORITIES = ("low", "normal", "high", "urgent")
PROJECT_STATUSES = ("active", "paused", "completed")
OUTCOMES = ("success", "failure", "mixed", "unknown")
AGENT_STATUSES = ("idle", "active", "disabled")


class MemoryStore(Store):
    """Memory system: discrete facts and notes JARVIS should retain."""

    table = "memories"
    label = "memory"
    fields = {
        "content": text("content", required=True),
        "project_id": optional_id("project_id"),
    }
    search_columns = ("content", "category", "source")
    filterable = Store.filterable + ("project_id",)


class ExperienceStore(Store):
    """Experience/learning system: what happened, how it went, what to do next
    time. Lessons are retrieved by keyword for now; no model is involved."""

    table = "experiences"
    label = "experience"
    fields = {
        "title": text("title", required=True, max_len=300),
        "description": text("description"),
        "outcome": choice("outcome", OUTCOMES),
        "lesson": text("lesson"),
        "project_id": optional_id("project_id"),
        "task_id": optional_id("task_id"),
    }
    defaults = {"outcome": "unknown"}
    search_columns = ("title", "description", "lesson", "category")
    filterable = Store.filterable + ("project_id", "task_id", "outcome")

    def lessons(self, query: str | None = None, limit: int = 20) -> list[dict]:
        """Active experiences that carry a lesson, optionally matching `query`."""
        return [item for item in self.list(query=query, limit=1000) if item["lesson"]][:limit]


class TaskStore(Store):
    """Task manager."""

    table = "tasks"
    label = "task"
    fields = {
        "title": text("title", required=True, max_len=300),
        "description": text("description"),
        "status": choice("status", TASK_STATUSES),
        "priority": choice("priority", TASK_PRIORITIES),
        "project_id": optional_id("project_id"),
        "due_at": optional_timestamp("due_at"),
    }
    defaults = {"status": "pending", "priority": "normal"}
    search_columns = ("title", "description", "category")
    filterable = Store.filterable + ("project_id", "status", "priority")
    order_by = (
        "CASE status WHEN 'in_progress' THEN 0 WHEN 'pending' THEN 1 WHEN 'completed' THEN 2 ELSE 3 END, "
        "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
        "id DESC"
    )

    def _prepare(self, cleaned, existing):
        # Keep completed_at in step with status.
        if "status" in cleaned:
            was_completed = bool(existing and existing["status"] == "completed")
            if cleaned["status"] == "completed" and not was_completed:
                cleaned["completed_at"] = utcnow()
            elif cleaned["status"] != "completed":
                cleaned["completed_at"] = None
        return cleaned

    def complete(self, task_id: int) -> dict:
        return self.update(task_id, {"status": "completed"})

    def reopen(self, task_id: int) -> dict:
        return self.update(task_id, {"status": "pending"})

    def open_count(self) -> int:
        return self.count(status="pending") + self.count(status="in_progress")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValidationError("name must contain letters or numbers")
    return slug


class ProjectStore(Store):
    """Project manager: workspaces that tasks, memories and experiences attach to."""

    table = "projects"
    label = "project"
    fields = {
        "name": text("name", required=True, max_len=200),
        "description": text("description"),
        "status": choice("status", PROJECT_STATUSES),
    }
    defaults = {"status": "active"}
    search_columns = ("name", "description", "category")
    filterable = Store.filterable + ("status",)
    order_by = "name COLLATE NOCASE ASC"

    def _prepare(self, cleaned, existing):
        if "name" in cleaned:
            cleaned["slug"] = slugify(cleaned["name"])
        return cleaned

    def get_by_name(self, name: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
        return self._row(row) if row else None


class AgentStore(Store):
    """Registry of agents. Only the core orchestrator exists today; this is
    where future agents will be registered."""

    table = "agents"
    label = "agent"
    fields = {
        "name": text("name", required=True, max_len=100),
        "kind": text("kind", required=True, max_len=50),
        "description": text("description"),
        "status": choice("status", AGENT_STATUSES),
        "capabilities": text("capabilities"),
    }
    defaults = {"kind": "core", "status": "idle"}
    search_columns = ("name", "description")
    filterable = Store.filterable + ("status", "kind")
    order_by = "id ASC"

    def get_by_name(self, name: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
        return self._row(row) if row else None
