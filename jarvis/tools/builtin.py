"""Built-in tools. Each wraps something the orchestrator already does, so the
existing validation, safety checks and audit trail all still apply."""

from __future__ import annotations

from .. import __version__
from ..common import NotFoundError, ValidationError
from ..safety import ActionCategory
from .registry import Tool, ToolRegistry

READ, WRITE = ActionCategory.READ, ActionCategory.WRITE
PRIORITIES = ["low", "normal", "high", "urgent"]
TASK_STATUSES = ["pending", "in_progress", "completed", "cancelled"]
VERIFICATION = ["unverified", "user_provided", "verified", "disputed"]
OUTCOMES = ["success", "failure", "mixed", "unknown"]

S = lambda description, **extra: {"type": "string", "description": description, **extra}    # noqa: E731
I = lambda description, **extra: {"type": "integer", "description": description, **extra}   # noqa: E731
N = lambda description, **extra: {"type": "number", "description": description, **extra}    # noqa: E731
B = lambda description, **extra: {"type": "boolean", "description": description, **extra}   # noqa: E731


def _filters(inputs: dict, *names: str) -> dict:
    return {name: inputs[name] for name in names if name in inputs}


def _project(app, inputs: dict) -> dict:
    if "id" in inputs:
        return app.projects.get(inputs["id"])
    if "name" in inputs:
        project = app.projects.get_by_name(inputs["name"])
        if project is None:
            raise NotFoundError(f"Project named {inputs['name']!r} not found")
        return project
    raise ValidationError("give either 'id' or 'name'")


# --- handlers ---------------------------------------------------------------
def jarvis_info(app, inputs, actor):
    return {"name": "JARVIS", "version": __version__, "environment": app.config.env,
            "ai_connected": app.provider.status().available, "counts": app.counts(),
            "tools": app.tools.names(), "not_built_yet": app.status()["not_built_yet"]}


def system_health(app, inputs, actor):
    status = app.status()
    problems = []
    if not status["database"]["integrity_ok"]:
        problems.append("database integrity check failed")
    if status["database"]["schema_version"] != status["database"]["expected_schema_version"]:
        problems.append("database schema is out of date")
    if not status["backups"]["count"]:
        problems.append("no backups exist yet")
    return {"healthy": not problems, "problems": problems, "ai": status["ai"], "database": status["database"],
            "backups": status["backups"], "safety": status["safety"], "counts": status["counts"]}


def projects_list(app, inputs, actor):
    return app.list("projects", active=None if inputs.get("include_archived") else True)


def projects_get(app, inputs, actor):
    project = _project(app, inputs)
    project["open_tasks"] = [task for task in app.tasks.list(project_id=project["id"])
                             if task["status"] in ("pending", "in_progress")]
    project["memory_count"] = app.memory.count(project_id=project["id"])
    project["experience_count"] = app.experiences.count(project_id=project["id"])
    return project


def tasks_list(app, inputs, actor):
    return app.list("tasks", query=inputs.get("query"), limit=inputs.get("limit", 50),
                    active=None if inputs.get("include_archived") else True,
                    **_filters(inputs, "status", "priority", "project_id"))


def tasks_create(app, inputs, actor):
    return app.create("tasks", {"source": actor, **inputs}, actor)


def tasks_update(app, inputs, actor):
    changes = {key: value for key, value in inputs.items() if key != "id"}
    if not changes:
        raise ValidationError("give at least one field to change")
    return app.update("tasks", inputs["id"], changes, actor)


def tasks_complete(app, inputs, actor):
    return app.complete_task(inputs["id"], lesson=inputs.get("lesson", ""), actor=actor)


def memory_search(app, inputs, actor):
    return app.list("memories", query=inputs.get("query"), limit=inputs.get("limit", 20),
                    **_filters(inputs, "category", "project_id"))


def memory_save(app, inputs, actor):
    # The same fact is not stored twice: an identical active memory is returned instead.
    wanted = " ".join(inputs["content"].split()).lower()
    # Search by the longest word so spacing and case differences still find the match.
    key = max(wanted.split(), key=len) if wanted.split() else wanted
    for existing in app.memory.list(query=key, limit=200):
        if " ".join(existing["content"].split()).lower() == wanted \
                and existing["project_id"] == inputs.get("project_id"):
            return {**existing, "duplicate": True}
    # Anything not saved by the owner is recorded as unverified with its true source.
    return {**app.create("memories", {"source": actor, **inputs}, actor), "duplicate": False}


def experience_record(app, inputs, actor):
    return app.create("experiences", {"source": actor, **inputs}, actor)


def register_builtin(registry: ToolRegistry) -> None:
    for tool in (
        Tool("jarvis.info", "What JARVIS is, its version, what it holds and which tools it has.", READ, jarvis_info),
        Tool("system.health", "Check database integrity, backups, safety mode and AI connection.", READ, system_health),
        Tool("projects.list", "List projects.", READ, projects_list,
             {"include_archived": B("Also return archived projects.")}),
        Tool("projects.get", "Read one project with its open tasks and item counts.", READ, projects_get,
             {"id": I("Project id."), "name": S("Exact project name.")}),
        Tool("tasks.list", "List or search tasks.", READ, tasks_list, {
            "query": S("Text to search for."), "status": S("Filter by status.", enum=TASK_STATUSES),
            "priority": S("Filter by priority.", enum=PRIORITIES), "project_id": I("Filter by project."),
            "limit": I("Maximum number of tasks."), "include_archived": B("Also return archived tasks.")}),
        Tool("tasks.create", "Create a task.", WRITE, tasks_create, {
            "title": S("What needs doing.", required=True), "description": S("Details."),
            "priority": S("Priority.", enum=PRIORITIES), "project_id": I("Project to attach it to."),
            "due_at": S("Due date, YYYY-MM-DD.")}),
        Tool("tasks.update", "Change a task's title, details, status, priority, project or due date.", WRITE,
             tasks_update, {
                 "id": I("Task id.", required=True), "title": S("New title."), "description": S("New details."),
                 "status": S("New status.", enum=TASK_STATUSES), "priority": S("New priority.", enum=PRIORITIES),
                 "project_id": I("New project."), "due_at": S("New due date, YYYY-MM-DD.")}),
        Tool("tasks.complete", "Mark a task as done, optionally recording a lesson learned.", WRITE, tasks_complete,
             {"id": I("Task id.", required=True), "lesson": S("Lesson to store as an experience.")}),
        Tool("memory.search", "Retrieve stored memories, optionally filtered by text, category or project.", READ,
             memory_search, {"query": S("Text to search for."), "category": S("Filter by category."),
                             "project_id": I("Filter by project."), "limit": I("Maximum number of memories.")}),
        Tool("memory.save", "Save a new memory with its category, confidence and verification status.", WRITE,
             memory_save, {
                 "content": S("What to remember.", required=True), "category": S("Category."),
                 "project_id": I("Project to attach it to."), "confidence": N("Confidence from 0 to 1."),
                 "verification_status": S("How well established this is.", enum=VERIFICATION)}),
        Tool("experience.record", "Record what happened, the outcome and the lesson.", WRITE, experience_record, {
            "title": S("What happened.", required=True), "description": S("Details."),
            "outcome": S("How it went.", enum=OUTCOMES), "lesson": S("What to do next time."),
            "category": S("Category."), "project_id": I("Related project."), "task_id": I("Related task.")}),
    ):
        registry.register(tool)
