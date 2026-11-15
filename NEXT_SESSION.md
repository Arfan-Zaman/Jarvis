# Next session handoff

Read this first. Then `JARVIS_ROADMAP.md` (Phase 3) and `ARCHITECTURE.md` section 4.

## Where things stand (2026-11-16)

- Phases 1 and 2 and steps 3.1 and 3.2 complete. 192 tests passing.
- JARVIS runs on Qwen 3.5 9B in the Ollama desktop app (`.env`, git-ignored).
- Chat talks and acts, reports actions truthfully from the run log, asks
  follow-up questions, and remembers the owner: ranked full-text memory in
  every answer, "From memory" citations, "remember …" saves at once, passing
  personal facts are offered and saved only on "yes".
- **Owner's direction:** a genuinely intelligent, general JARVIS first. No
  business-specific work yet.
- Remote `origin` is GitHub; push only when the owner asks.

## Exact next task: steps 3.3 and 3.4, personality and everyday tools

No installs needed.

### 3.3 Personality (small)
1. One shared JARVIS voice in `jarvis/engine/persona.py`, used by chat answers,
   look-up answers and fixed action wording: calm, concise, lightly dry; honours
   stored preferences (name to use, answer length) from memory.
2. Self-description already comes from the live tool list (3.1); add a test
   that a newly registered tool appears in "what can you do".

### 3.4 Everyday tools (read/write internal only, through the tool registry)
3. `time.now` (read): local date, time, weekday, timezone.
4. `calc.evaluate` (read): safe arithmetic and percentages using `ast`, never
   `eval`; units for length, weight, temperature, volume.
5. Reminders: tasks gain an optional `due_at` with a time (`YYYY-MM-DD HH:MM`);
   `reminders.due` (read) lists overdue and due-today items. No background
   notifications yet (Phase 3.5 briefings will surface them).
6. Notes: `notes.save` / `notes.search` (memories with category `note`, so they
   use the same index and safety).
7. Inbox files: `files.list` and `files.read` (read) confined to
   `data/inbox/` via `SafetyLayer.authorize_path`; text and Markdown only,
   size-capped. Show the inbox path on the System page.
8. Tests for every tool: valid and invalid inputs, path escapes refused, `eval`
   never used, permissions, run log entries.
9. Real model on a throwaway `JARVIS_DATA_DIR`: "what time is it", "what's 17.5%
   of 2,340", "convert 5 miles to km", "remind me at 3pm tomorrow to …", "what's
   due today", "summarise the file in my inbox".
10. Update README, DEVLOG, ARCHITECTURE, ROADMAP and this file. Commit.

## Rules for the session

- Standard library only. No new installs or downloads without the owner's approval.
- Everything stays in `~/JARVIS`.
- All actions go through the reasoning engine and `app.tools.execute`.
- Never report something as working unless a test or a real run showed it.
- Real-model checks use a throwaway `JARVIS_DATA_DIR`, not `data/`.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md, JARVIS_ROADMAP.md and
> ARCHITECTURE.md, then implement steps 3.3 and 3.4 (personality and everyday
> tools) exactly as described. Standard library only, no installs, preserve
> existing tests, test with the real local model, update the docs and commit.
> Do not push. Keep the report short and in plain language.
