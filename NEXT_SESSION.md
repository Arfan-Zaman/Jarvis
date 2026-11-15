# Next session handoff

Read this first. Then `JARVIS_ROADMAP.md` (Phase 3) and `ARCHITECTURE.md`
section 4b (autonomous design).

## Latest (2026-11-16): nanobot swarm face is live

`base.png` (version 1) is in place and the presence face is now a live particle
swarm built from it (see DEVLOG). The Higgsfield project connector is still on
the old account; generation works through the owner's Chrome (Claude in Chrome)
on the new account, 6.5 credits per 2K image. Never buy add-ons ("Unlimited").
Owner's next wishes: a Tony Stark style HUD dashboard and a far more capable
JARVIS (delegate hard work to Claude Code at `~/.local/bin/claude`).

## Earlier: art-mode session handoff

The previous session hit its usage limit. Exact state:

**Done and pushed** (commit `eff4e35` and the commit with this note):
- Art mode in `jarvis/web/static/identity.js` + `identity.css`: when rendered
  files exist in `jarvis/web/static/identity/`, the vector face hides and the
  state's still (or loop) crossfades in; live eye glow (colour/intensity/opening
  from the `STATES` table), voice level on the eyes while speaking, subtle
  cursor parallax, canvas core as a halo. A state without its own still uses
  `base.png`; with no files at all the old vector face is used. Mapping is the
  `ART` table; eye positions are `ART_EYES` (guesses, tune to the real render).
- `GET /api/identity/assets` (server.py) lists which of the fixed file names
  exist. Test added in `tests/test_web.py`. 240 tests pass.
- Verified in the browser with temporary placeholder PNGs (deleted): Presence
  and desktop views switch to art mode, crossfade and base fallback work, no
  files gives the vector face, no console errors.
- `.claude/launch.json` has `jarvis-throwaway` (port 8777, throwaway
  `JARVIS_DATA_DIR`) for safe checks. The owner's real server was restarted on
  port 8765 with the new code.

**Blocked: the art itself is not generated yet.**
- The project Higgsfield connector (`.mcp.json`, server name `higgsfield`,
  211 tools, the only one that can generate) is still signed in to the owner's
  OLD account: 0 credits, free plan. Re-authenticating in `/mcp` kept returning
  the old account, most likely because the normal browser was still signed in
  to the old account. Fix: sign out of higgsfield.ai in the normal browser,
  then `/mcp` -> `higgsfield` -> Clear authentication -> Authenticate -> sign
  in with the NEW account (Google). Check with the `balance` tool: the new
  account showed 1,210 credits, Plus plan.
- The claude.ai connector "Higgsfield AI" is on the new account but is
  read-only (7 tools, no generation). Do not try to generate with it.
- Browser route (fallback): higgsfield.ai in the built-in browser pane was stuck
  on a Cloudflare "Verify you are human" box (Claude must not tick it; the owner
  must) and the email sign-in. The owner's Chrome was not signed in. The owner
  is signed in to the new account in Safari; the pane's cookie import (only
  higgsfield.ai) would carry that over. On the website, GPT Image 2 at 2K/high
  costs 6.5 credits per image (Black Friday price).

**Quote already given (connector prices, credits):** base 2K high 2.75; 11
stills about 30; 3 x 5 s loops 105 at 720p or 240 at 1080p (Seedance 2.5,
omni_reference, base.png as start image, no audio). Owner approval is still
needed before spending; generate the base first, show it, wait for approval.

**Next steps:**
1. Get a generating route on the new account (above). Confirm the balance.
2. Generate `base.png` (prompt in "Owner feedback" below; gpt_image_2_6,
   resolution 2k, quality high, 1:1), show it, wait for approval.
3. Generate the 11 state stills with base as `image_references`, same framing;
   then the loops if approved. Download to `jarvis/web/static/identity/` with
   the exact names.
4. Tune `ART_EYES` to the real eye positions; check `#presence` and `#desktop`
   on the throwaway server; run `python3 -m unittest discover -s tests`;
   update DEVLOG.md; commit and push to `origin main`.

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
- Remote `origin` is GitHub; the owner now wants a push after every step.

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

3. Done: `jarvis/web/static/identity.js` + `identity.css` and the Presence
   home page (`#presence`, default) and desktop view (`#desktop`). Details below
   kept for reference.

Next steps, in order:
3. (done) `jarvis/web/static/identity.js` + `identity.css`: original faceted face
   (SVG), sensor eyes (aperture, gaze follows the cursor), neural core (canvas),
   state machine; a Presence home page laid out like the reference with real
   numbers only; a clearly labelled simulated preview of all states.
4. Desktop: show the identity in the floating panel (WKWebView of the
   presence page in desktop mode); wake on the spoken name "Jarvis" (speech
   segments transcribed locally; clap still works).
5. Voice: automatically use the most natural installed English voice
   (Premium/Enhanced) if present.

## Owner feedback (2026-11-16): the face must look like the reference render

The code-drawn SVG/canvas face (`identity.js`) works and is state-correct, but
the owner rejected its look as a "cheap render". The reference board is a
photoreal, cinematic 3D character. **Switch the identity to rendered art**,
keeping the existing state machine, `/api/live` wiring and honesty rules:

1. **Art assets** (generated by the owner in Higgsfield, or by Claude if the
   Higgsfield connector is authorised; it costs the owner's credits, so quote
   first). Put them in `jarvis/web/static/identity/`:
   - `base.png` (2048x2048, pure black background, face centred)
   - one still per state, same framing, generated with `base.png` as the
     reference: `listening.png analysing.png planning.png executing.png
     concerned.png resolute.png approval.png success.png warning.png
     error.png critical.png`
   - seamless 5 s loops (H.264 MP4, 1080x1080, camera locked): `idle.mp4`
     (eyes breathe), `thinking.mp4` (faint light moving through the plates),
     `executing.mp4` (energy along the edge lines)
2. **Engine change** in `identity.js`: an "art mode" that crossfades the
   state's still/loop, adds real-time glow (eye bloom intensity and colour from
   the state table), cursor parallax (subtle 3D tilt), the voice level on the
   eyes while speaking, and the canvas core as a halo behind. Fall back to the
   current vector face when an asset is missing. Never show a state that the
   real system did not report (simulated preview stays labelled).
   **Status:** engine done (art mode in `identity.js`, endpoint
   `GET /api/identity/assets`); waiting for the art files. After adding them,
   adjust `ART_EYES` (eye centres and slant) to the real render.
3. **Later:** a true 3D head (Higgsfield `generate_3d` to GLB) rendered with
   three.js (PBR obsidian, emissive eyes, bloom), turning toward the cursor.

Prompts (original character; do NOT name or imitate Ultron or other IP):

- Base: "Front-facing portrait of an original artificial intelligence, no
  human features, no body: a sculpted mask of black obsidian and dark gunmetal
  armour plates with sharp angular facets and a central vertical crest,
  perfectly symmetrical, narrow slanted glowing hot-pink magenta sensor eyes
  with white-hot cores, thin glowing magenta light lines tracing the brow and
  cheek plates, emerging from pure black darkness, magenta rim light, faint
  volumetric haze, cinematic, ultra-detailed photoreal 3D render, centred,
  pure black background, no text, no logo." Negative: human skin, mouth,
  cartoon, toy robot, text, watermark, helmet straps, background objects.
- States (same reference, same framing): listening "eyes brighter and
  slightly wider"; analysing "thin geometric light lines moving across the
  plates, deep violet accents"; planning "deep violet light paths forming
  across the face"; executing "controlled magenta energy arcs flowing along
  the edge lines"; concerned "eyes narrowed, magenta concentrated and more
  saturated"; resolute "completely still, eyes thin and precise, background
  darker"; approval "eyes steady, a soft white-silver tone in the light
  lines"; success "a brief soft release of magenta light around the mask";
  warning "eyes orange-red, restrained"; error "eyes dim red, one cheek plate
  line flickering red"; critical "intense red energy cracks across the plates".
- Loops (image-to-video from base.png): "camera locked, the head does not
  move; the eyes slowly brighten and dim like breathing; faint magenta light
  drifts along the edge lines; seamless loop."

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
