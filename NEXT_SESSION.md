# Next session handoff

Read this first. Then `JARVIS_ROADMAP.md` (Phase 3) and `ARCHITECTURE.md` section 4.

## Where things stand (2026-11-16)

- Phases 1 and 2 complete. 155 tests passing. On GitHub (`origin/main`).
- JARVIS runs on a real local model: Qwen 3.5 9B in the Ollama desktop app,
  configured in `.env` (git-ignored). Chat answers but only talks; actions
  happen through the Goals page and the reasoning engine.
- **Owner's direction:** build a genuinely intelligent, general JARVIS first.
  Do not tailor anything to the businesses yet.

## Exact next task: roadmap step 3.1, one conversation that thinks and acts

No installs needed.

1. Add a router in `jarvis/engine/conversation.py`. For each chat message, ask
   the model (JSON) to choose: `{"mode": "answer"}` for talk and questions, or
   `{"mode": "act", "goal": "<restated goal>"}` when the owner wants something
   done with JARVIS's tools. Include the recent conversation and the live tool
   list. When unsure, answer and offer to act rather than acting.
2. For "act": run `app.engine.start(goal)` and then ask the model for a short,
   natural reply built **only** from the engine's report (status, changes_made,
   question, approval, error). The reply must not claim anything the report
   does not show. Store the run id on the assistant message.
3. Blocked runs: the engine's question becomes JARVIS's reply. The owner's
   next chat message is treated as the answer (`engine.resume(run_id, answer)`)
   when the conversation has a blocked run pending.
4. Approvals: the reply explains what needs approval. Approving still happens
   in the System page (or a button in chat); approval never comes from chat
   text alone.
5. Carry the last ~10 messages as context for both answers and routing.
6. Schema: add `run_id` to `messages` (migration 4). Show a small "Action"
   card in chat linking to the run's plan and changes.
7. Replace the chat system prompt's static ability list with one generated from
   `app.tools.list()`, so JARVIS's self-description is always accurate.
8. Tests with the scripted provider: routing to answer, routing to act,
   blocked then answered in chat, approval surfaced, failure reported honestly,
   no claims beyond the report, bad router output falls back to answer.
9. Try it with the real model on a throwaway `JARVIS_DATA_DIR`: small talk, a
   question, "remind me to …", an ambiguous request, and a follow-up answer.
10. Update README, DEVLOG, ARCHITECTURE, ROADMAP and this file. Commit.

Then step 3.2 (memory of you).

## Rules for the session

- Standard library only. No new installs or downloads without the owner's approval.
- Everything stays in `~/JARVIS`.
- All actions go through the reasoning engine and `app.tools.execute`.
- Never report something as working unless a test or a real run showed it.
- Real-model checks use a throwaway `JARVIS_DATA_DIR`, not `data/`.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md, JARVIS_ROADMAP.md and
> ARCHITECTURE.md, then implement roadmap step 3.1 (one conversation that
> thinks and acts) exactly as described. Standard library only, no installs,
> preserve existing tests, test with the real local model, update the docs and
> commit. Do not push. Keep the report short and in plain language.
