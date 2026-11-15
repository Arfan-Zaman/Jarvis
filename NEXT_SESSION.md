# Next session handoff

Read this first. Then `JARVIS_ROADMAP.md` (Phase 3) and `ARCHITECTURE.md` section 4.

## Where things stand (2026-11-16)

- Phases 1 and 2 and step 3.1 complete. 174 tests passing.
- JARVIS runs on Qwen 3.5 9B in the Ollama desktop app (`.env`, git-ignored).
- Chat is one conversation that talks and acts: it routes each message to
  answer or act, runs actions through the reasoning engine, reports them in
  fixed wording from the run log, asks follow-up questions and takes the next
  message as the answer. It knows the date and its real abilities.
- **Owner's direction:** a genuinely intelligent, general JARVIS first. No
  business-specific work yet.
- Remote `origin` is GitHub; push only when the owner asks.

## Exact next task: roadmap step 3.2, memory of you

No installs needed.

1. Migration 5: SQLite FTS5 index over memories (content, category) and
   experiences (title, description, lesson), kept in sync with triggers.
   FTS5 is available in this Python build (checked).
2. `jarvis/engine/context.py`: `ContextBuilder.build(text, project_id=None)`
   returning the most relevant active memories and lessons (bm25), preferring
   verified and higher-confidence items, within a size budget, each with id,
   source and verification status.
3. Use it in chat answers (system prompt: "What you know about the owner",
   with ids) and in `Engine._recall` (replacing LIKE matching). Answers that
   use a memory should say so naturally ("You told me you prefer …").
4. "Shall I remember that?": when the owner states a durable personal fact or
   preference in chat, JARVIS offers to remember it, quoting the exact wording.
   It is saved (source `user:chat`, `user_provided`) only after a yes in the
   next message. Never save silently.
5. `memory.search` uses the index (same inputs).
6. Show "From memory" chips on chat replies listing the memories used.
7. Tests: ranking, archived excluded, size budget, index sync on
   create/update/archive/delete, upgrade from v4, the offer-then-confirm flow
   (yes saves, no or silence does not), preferences used in later answers.
8. Real model on a throwaway `JARVIS_DATA_DIR`: tell it a preference, accept
   the offer, start a new conversation, check it is used and cited.
9. Update README, DEVLOG, ARCHITECTURE, ROADMAP and this file. Commit.

## Rules for the session

- Standard library only. No new installs or downloads without the owner's approval.
- Everything stays in `~/JARVIS`.
- All actions go through the reasoning engine and `app.tools.execute`.
- Never report something as working unless a test or a real run showed it.
- Real-model checks use a throwaway `JARVIS_DATA_DIR`, not `data/`.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md, JARVIS_ROADMAP.md and
> ARCHITECTURE.md, then implement roadmap step 3.2 (memory of you) exactly as
> described. Standard library only, no installs, preserve existing tests, test
> with the real local model, update the docs and commit. Do not push. Keep the
> report short and in plain language.
