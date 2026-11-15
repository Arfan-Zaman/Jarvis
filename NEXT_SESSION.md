# Next session handoff

Read this first. Then `ARCHITECTURE.md` section 4 and `JARVIS_ROADMAP.md`.

## Where things stand (2026-11-16)

- Phases 1 and 2.1 to 2.3 complete. 155 tests passing.
- JARVIS runs on a real local model: Qwen 3.5 9B in the Ollama desktop app,
  configured in `.env` (git-ignored). Chat answers; goals plan, act, get
  reviewed and report honestly. Ollama must be running.
- Remote `origin` is https://github.com/Arfan-Zaman/Jarvis.git and is linked.
  Push with `git push` only when the owner asks.
- The live database upgrades to schema v3 (with a backup) on the next start.

## Exact next task: roadmap step 2.4, contextual memory

No installs needed.

1. Migration 4: an SQLite FTS5 index over memories (content, category) and
   experiences (title, description, lesson), kept in sync with triggers.
   FTS5 is available in this Python build (checked).
2. `jarvis/engine/context.py`: `ContextBuilder.build(goal, project_id=None)`
   returning the most relevant active memories and lessons, ranked (bm25),
   with source, confidence and verification status, within a size budget.
   Prefer verified and higher-confidence items; never include archived ones.
3. Use it in `Engine._recall` (replacing keyword LIKE matching) and in chat, so
   chat answers can draw on stored memories, citing them as "from memory".
4. Upgrade `memory.search` to use the index (keep its inputs the same).
5. Show "context used" (memory ids and text) in the Goals page report.
6. Tests: ranking, archived items excluded, project scoping, size budget,
   index kept in sync on create/update/archive/delete, upgrade from v3, and
   the existing engine tests still passing.
7. Try three real goals and two chat questions that depend on stored memories.
8. Update README, DEVLOG, ARCHITECTURE, ROADMAP and this file. Commit.

## Rules for the session

- Standard library only. No new installs or downloads without the owner's approval.
- Everything stays in `~/JARVIS`.
- All actions go through `app.tools.execute`; the engine never calls stores
  for writes.
- Never report something as working unless a test or a real run showed it.
- Real-model checks use a throwaway `JARVIS_DATA_DIR`, not `data/`.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md, ARCHITECTURE.md and
> JARVIS_ROADMAP.md, then implement roadmap step 2.4 (contextual memory) exactly
> as described. Standard library only, no installs, preserve existing tests,
> test with the real local model, update the docs and commit. Do not push.
> Keep the report short and in plain language.
