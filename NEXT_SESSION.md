# Next session handoff

Read this first. Then `ARCHITECTURE.md` sections 4.2a to 4.4 for the design.

## Where things stand (2026-11-15)

- Phase 1 and Phase 2.1 are complete and committed on `main`. 114 tests passing.
- JARVIS has 11 tools, one execution engine, and a run log. See README "Tools".
- No AI model connected. Nothing installed. No remote.
- The live database in `data/` upgrades from schema v1 to v2 (with a
  `pre-upgrade-v1` backup) the next time JARVIS starts.

## Exact next task: roadmap step 2.2, the reasoning engine

Build the loop that turns a goal into tool calls. No installs, no real model:
test it with a scripted stand-in provider.

1. Create `jarvis/engine/engine.py` with `Engine.run(goal, actor, allowed)`:
   open a run with `kind="goal"`, then loop: build the prompt (goal, tool specs
   from `app.tools.list()`, steps so far), ask `app.provider.generate`, parse
   one JSON step: `{"tool": name, "inputs": {...}}` or `{"final": "text"}`.
2. Execute tool steps with `app.tools.execute(..., run_id=run_id)`; feed the
   structured result back into the next prompt.
3. Invalid model output: retry once, then fail the run with a clear error.
4. Limits: maximum steps, maximum tool failures. Hitting one fails the run.
5. `approval_required`: set the run to `waiting_approval` and stop. Add
   `Engine.resume(run_id, approval_id)` to continue from that step.
6. The report is built from the stored `run_steps` (what succeeded, failed,
   was refused), not from the model's text. The model's final text is included
   and labelled as the model's words.
7. With no provider available, refuse to start and say so. Never fake a run.
8. Expose `app.engine`, add `POST /api/runs` (start) and
   `POST /api/runs/<id>/resume`.
9. Tests with a scripted provider: single-step goal, multi-step goal, bad
   output then recovery, bad output twice, step limit, failing tool, approval
   pause and resume, allow-list respected, no provider, report matches the log.
10. Run all tests, update README, DEVLOG, ARCHITECTURE, NEXT_SESSION, commit.

Then step 2.3 (connect a real local model), which needs the owner's approval
to install Ollama and download one model.

## Rules for the session

- Standard library only. No installs until step 2.3 and the owner's approval.
- Everything stays in `~/JARVIS`.
- All actions go through `app.tools.execute`; the engine never calls stores.
- Never report something as working unless a test or a real run showed it.
- Do not start step 2.3 or later without being asked.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md and ARCHITECTURE.md, then implement
> roadmap step 2.2 (the reasoning engine, tested with a scripted stand-in
> model) exactly as described. Standard library only, no installs, preserve
> existing tests, run all tests, update the docs, and commit. Be
> token-efficient and give me a short plain-language report.
