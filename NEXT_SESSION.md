# Next session handoff

Read this first. Then `JARVIS_ROADMAP.md` (Phase 3) and `ARCHITECTURE.md`
section 4b (autonomous design).

## Where things stand (2026-11-16)

- Phases 1 and 2 and steps 3.1 to 3.5 and JARVIS Desktop complete. 233 tests passing.
- JARVIS runs on Qwen 3.5 9B in Ollama; talks and acts, remembers, acts on its
  own within the hard lines, uses the web with sources, and now has a voice
  (push-to-talk with whisper.cpp; spoken replies with the macOS voice Daniel).
- Installed with approval: Ollama + qwen3.5:9b, whisper.cpp + ggml-small.en
  (`data/models`). yt-dlp was already present. Claude Code 2.1 is at
  `~/.local/bin/claude`.
- JARVIS Desktop (`desktop/JARVISDesktop.swift`) is installed as a login item
  (`local.jarvis.desktop`): floating orb, double clap then "Jarvis", it starts
  the server itself. Ask the owner whether real claps are detected reliably;
  thresholds are in `ClapDetector`. The HUD work should reuse the orb's states.
- Reference videos (four reels) are in `data/media/reels` with transcripts and
  contact sheets; the roadmap's Phase 3 list is derived from them.
- Remote `origin` is GitHub; push only when the owner asks.

## Exact next task: step 3.6, the living interface (HUD)

No installs needed.

1. An arc-reactor status ring (SVG + CSS, no libraries) in the sidebar and,
   larger, on the Chat page, with states: online, listening, transcribing,
   thinking, working, speaking, offline. Each state is driven by real events
   (recording started, request in flight, run executing, audio playing,
   server unreachable), never decorative animation alone.
2. Show the active model under the ring (from `/api/status`).
3. Live action cards: while a chat request runs an action, poll
   `/api/runs/<id>` (or a new lightweight `/api/runs/active`) and show the
   current step ("Searching the web…", "Reading python.org…", "Adding a
   task…") until it finishes; the run must exist server-side before the card
   appears (start runs asynchronously or expose the active run id).
4. Respect `prefers-reduced-motion`; keep the existing colours and layout.
5. Tests: the active-run endpoint, state mapping, no claims without a run.
6. Verify in the browser at desktop and phone widths.
7. Update README, DEVLOG, ARCHITECTURE, ROADMAP and this file. Commit.

Then 3.7 (sandboxed code runner) and 3.8 (skills built once with Claude Code).

## Rules for the session

- Standard library only. No new installs or downloads without the owner's approval.
- Everything stays in `~/JARVIS`.
- All actions go through `app.tools.execute`; no unrestricted shell, ever.
- Never report something as working unless a test or a real run showed it.
- Real-model checks use a throwaway `JARVIS_DATA_DIR`, not `data/`.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md, JARVIS_ROADMAP.md and
> ARCHITECTURE.md, then implement step 3.6 (the living interface) exactly
> as described. Standard library only, no installs, preserve existing tests,
> test with the real local model, update the docs and commit. Do not push.
> Keep the report short and in plain language.
