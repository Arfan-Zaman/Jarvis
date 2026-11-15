# Next session handoff

Read this first. Then `ARCHITECTURE.md` section 4 for the design.

## Where things stand (2026-11-15)

- Phase 1 complete, committed as `926ee32` on `main`. 90 tests passing.
- Live database is healthy: 2 projects, 1 agent, nothing else stored.
- No AI model connected. Nothing installed. No remote.
- Phase 2 is designed in `ARCHITECTURE.md`; no Phase 2 code exists yet.
- The three planning documents may be uncommitted; check `git status`.

## Exact next task: roadmap step 2.1

Build the tool registry and run log. No installs, no model needed.

1. Add migration 2 in `jarvis/db.py`: tables `runs` and `run_steps`
   (fields in `ARCHITECTURE.md` 4.2). Do not edit migration 1.
2. Create `jarvis/tools/registry.py`: a `Tool` (name, description, input
   rules, safety category, function) and a `ToolRegistry` with `register`,
   `get`, `list` and `execute`.
3. `execute` must validate inputs, go through `SafetyLayer.authorize`, return
   an approval request for high-impact tools, and record the call.
4. Create `jarvis/tools/builtin.py` wrapping existing orchestrator methods:
   search memory, save memory, create task, complete task, record experience,
   list projects.
5. Add a `RunStore` for `runs` and `run_steps`, and expose `tools` and `runs`
   on the `Jarvis` orchestrator.
6. Tests: registration, unknown tool refused, bad input refused, write tool
   audited, high-impact tool pauses for approval, read-only mode refuses,
   every call recorded as a run step.
7. Run all tests, update `README.md` and `DEVLOG.md`, commit.

Then step 2.2: the reasoning engine, tested with a scripted stand-in model.

## Rules for the session

- Standard library only. No installs until step 2.3 and the owner's approval.
- Everything stays in `~/JARVIS`. Do not touch `data/`.
- All actions go through the orchestrator and safety layer.
- Never report something as working unless a test or a real run showed it.
- Keep it small; do not start step 2.3 or later without being asked.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md and ARCHITECTURE.md, then implement
> roadmap step 2.1 (tool registry, run log, built-in tools) exactly as
> described. Standard library only, no installs, preserve existing tests, run
> all tests, update README and DEVLOG, and commit. Be token-efficient and give
> me a short plain-language report.
