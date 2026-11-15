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

## In progress: visual identity and character (owner's spec, 2026-11-16)

The owner supplied a full spec ("JARVIS - VISUAL IDENTITY + CHARACTER SYSTEM")
and a reference board: a dark faceted obsidian mask with slanted hot-pink sensor
eyes, a sidebar, real stat cards, a command bar, state cards (idle, listening,
analysing, planning, executing, success, concerned, resolute, warning, error,
critical), tool activity and a personality panel. **Push to GitHub after every
step** (owner's standing instruction) and keep this file current.

Done:
1. `jarvis/engine/persona.py`: the character (calm executive intelligence,
   challenges weak ideas, never pretends) used by chat and look-up answers;
   fixed outcome phrases ("Completed.", "The operation failed. ... I have not
   marked it as complete.").
2. `Engine.live()` and `GET /api/live`: presence state from real runs only
   (calm, analysing, planning, executing, concerned, resolute, approval,
   awaiting, success, failure).

Next steps, in order:
3. `jarvis/web/static/identity.js` + `identity.css`: original faceted face
   (SVG), sensor eyes (aperture, gaze follows the cursor), neural core (canvas),
   state machine; a Presence home page laid out like the reference with real
   numbers only; a clearly labelled simulated preview of all states.
4. Desktop: show the identity in the floating panel (WKWebView of the
   presence page in desktop mode); wake on the spoken name "Jarvis" (speech
   segments transcribed locally; clap still works).
5. Voice: automatically use the most natural installed English voice
   (Premium/Enhanced) if present.

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
