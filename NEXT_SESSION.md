# Next session handoff

Read this first. Then `ARCHITECTURE.md` section 4 and `JARVIS_ROADMAP.md`.

## Where things stand (2026-11-15)

- Phase 1, 2.1 and 2.2 complete and committed on `main`. 149 tests passing.
- The reasoning engine plans and runs goals through the tools, but has only
  been run with a scripted stand-in. No real AI model is connected.
- Remote `origin` is https://github.com/Arfan-Zaman/Jarvis.git. Nothing has
  been pushed; push only when the owner asks.
- The live database upgrades to schema v3 (with a `pre-upgrade-v2` backup) the
  next time JARVIS starts.

## Exact next task: roadmap step 2.3, connect one local model

**Needs the owner's approval first** (decision D1): installing Ollama and
downloading one small model, roughly 2 to 5 GB. Ask before installing.

1. Confirm free disk space and memory, then propose one small instruction-
   following model that fits in 16 GB and is good at JSON output. Get approval.
2. Install Ollama (official installer or Homebrew) and pull that one model.
   Do not set Ollama to start at login unless the owner agrees.
3. Set `JARVIS_AI_PROVIDER=ollama` and `JARVIS_AI_MODEL=<model>` in `.env`.
4. Verify `OllamaProvider` against the real server: status, chat, errors.
   Ask Ollama for JSON output (`"format": "json"`) when the engine calls it.
5. Run three real goals end to end (one-step task, multi-step with a project,
   one that should block for information). Record what worked and failed.
6. Tune `PROTOCOL` in `jarvis/engine/engine.py` only where the real model
   misbehaves. Keep all existing tests passing; add tests for any changes.
7. Update README, DEVLOG, ARCHITECTURE, ROADMAP and this file. Commit.

If the owner does not approve the install, do step 2.4 instead (full-text
memory search and the context builder); it needs no installs.

## Rules for the session

- No paid APIs. No installs or downloads without the owner's approval.
- Everything stays in `~/JARVIS`, except the Ollama install the owner approves.
- All actions go through `app.tools.execute`; the engine never calls stores.
- Never report something as working unless a test or a real run showed it.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md, ARCHITECTURE.md and
> JARVIS_ROADMAP.md, then do roadmap step 2.3: recommend one small local model
> for my Mac, and once I approve, install Ollama and that model, connect it,
> and run real goals end to end. Preserve existing tests, update the docs and
> commit. Do not push. Keep the report short and in plain language.
