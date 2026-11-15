# JARVIS development log

Newest entries first. Record what changed, why, and what was verified.

## 2026-11-15 — Phase 2.1: tools, execution engine, run log

### Built
- `jarvis/tools/registry.py`: `Tool` and `ToolRegistry`. One `execute` path:
  find tool, check allow-list, validate inputs, ask the safety layer, run,
  record, return a structured result. It never raises for a failed tool.
- `jarvis/tools/builtin.py`: 11 tools (6 read, 5 write) wrapping existing
  orchestrator methods, so validation and audit still apply.
- `jarvis/stores/runs.py` and schema v2: `runs` and `run_steps`.
- API: `/api/tools`, `/api/tools/<name>/execute`, `/api/runs`, `/api/executions`.
- Command line: `tools` and `tool`. System page: tools and recent executions.

### Decisions
- A tool's permission level is its existing safety category, so there is one
  permission system, not two.
- A direct tool call creates its own single-step run, so nothing executes
  without a log entry. Goal runs (Phase 2.2) will hold many steps.
- Memories saved by a tool record the real caller as the source and default to
  "unverified".
- An existing database is backed up (`pre-upgrade-v1`) before migrating.
- `REQUIRED_TABLES` stays at the version 1 set so older backups remain
  restorable.
- No destructive built-in tools yet; the approval path is tested with
  test-only tools.

### Verified
- 114 tests passing (90 existing, 24 new): registration, discovery, each
  built-in tool, invalid inputs, unknown tools, allow-list, crash containment,
  read-only mode, approval flow for all four sensitive categories, run log
  contents and retrieval, restart survival, interrupted runs, v1 upgrade, API.
- Real run on a throwaway database: CLI tool calls (success, bad input,
  unknown tool) and the System page panels. No console errors.

### Not done
- The live database in `data/` is still schema v1. It upgrades, with a backup,
  the next time JARVIS starts.
- No model, so nothing chooses tools yet.

## 2026-11-15 — Milestone 1: core foundation

### Environment at the time
- macOS 26.6.2, Apple M5, 16 GB memory, 258 GB free disk.
- Python 3.14.7 (Miniconda), SQLite 3.53.2, Git 2.50.1, Node 24.16.0 (unused).
- Nothing was installed for this milestone.

### Decisions
- **Standard library only.** The web server, database access, configuration,
  and tests all use what ships with Python. No virtual environment is needed
  and there is nothing to break on upgrade. Revisit only when a feature
  genuinely needs a dependency.
- **SQLite, one short-lived connection per operation**, WAL mode, foreign keys
  enforced. Simple and safe with the threaded web server.
- **Schema migrations** are an append-only list in `jarvis/db.py`, tracked with
  SQLite's `user_version`.
- **One generic store** (`stores/base.py`) gives every knowledge table the same
  metadata, validation, search, archive and delete behaviour.
- **Everything goes through the orchestrator.** The web API and command line
  never touch a store directly, so the safety layer and audit trail cannot be
  bypassed by accident.
- **Two-step approvals** for high-impact actions: request, human approves,
  then execute. Approvals are fingerprinted to the exact action, expire, and
  are single-use.
- **Archive is the default way to remove something.** Permanent deletion is
  classed as destructive and needs approval.
- **No fake AI.** With no provider, chat stores a `system` message, never an
  `assistant` one.
- **Loopback only.** The config rejects non-local hosts, and the server rejects
  foreign `Host` and `Origin` headers.
- **Seed data** is limited to the two business workspaces and the core agent,
  created once and never re-created if the user removes them.

### Built
Core orchestrator, AI provider abstraction, memory, experience/learning, task
manager, project manager, safety/permission layer, configuration manager,
logging, backup/recovery, the SQLite data model, the local web interface, and
the command line.

### Verified
- `python3 -m unittest discover -s tests`: 90 tests, all passing.
- Browser check against a throwaway database: dashboard, saving a memory, the
  permanent-delete confirmation, adding and completing a task, chat with no
  provider, the System page, and phone-width layout on all seven pages. No
  console errors.
- Command line check: serve, stop, status, backup, backups, restore (confirmed,
  cancelled, and invalid name).

### Fixed along the way
- A pre-restore backup could prune the very backup being restored. Pruning is
  now skipped for that backup, with a test.
- Forms lost their default values after saving.
- The page overflowed sideways at phone width.
- A slow page load could overwrite a newer one after quick navigation.
- A startup event was being logged by every command, not only by the server.

### Known gaps
- Ollama adapter tested only against a simulated server.
- The Claude Code preview launcher refused to start the server from
  `.claude/launch.json` (it reported the port as in use when it was not), so
  the browser check ran the server from a shell instead. The launch entry is
  kept but unverified.
- See "Current limitations" in the README.

### Next
Milestone 2: connect one local model (see README).
