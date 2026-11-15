---
name: jarvis-art
description: Generate or replace JARVIS's character art on Higgsfield through the owner's Chrome and wire it into the 3D nanobot face. Use when the owner wants a new face, state stills, or other images for JARVIS.
---

# JARVIS art on Higgsfield

## Route that works
- The project `higgsfield` MCP connector is on an old 0-credit account; the
  claude.ai "Higgsfield AI" connector is read-only. Use **Claude in Chrome** on
  higgsfield.ai, where the owner is signed in (Plus plan).
- Check the account: click the avatar at bottom-left of higgsfield.ai; it shows
  plan and credits.
- **Never** turn on "Unlimited" or buy anything: that toggle opens a paid
  purchase dialog. Close it.

## Generate
1. Quote first: GPT Image 2, 1:1, 2K, High = 6.5 credits per image (Black
   Friday 2026 price; read the number on the Generate button). Wait for the
   owner's yes with that figure.
2. Open `https://higgsfield.ai/image`, then click **Image** in the top bar to get
   the full form with model, ratio, quality and resolution controls. Set GPT
   Image 2, 1:1, High, 2K, 1/4.
3. Paste the prompt (base prompt and per-state lines are in `NEXT_SESSION.md`;
   original character only, never name or imitate existing IP). Click Generate
   once. Resize the window first if the layout moved, or the click misses.
4. Wait ~60-90 s. Read the result URL in the page:
   `[...document.querySelectorAll('img')].map(i => new URL(i.currentSrc).searchParams.get('url'))`
   and take the cloudfront `.png` path (drop the query string).
5. `curl -sfL -o <dest> <url>`, check with `file` (2048 x 2048 PNG), show it to
   the owner. Keep candidates in `data/media/identity_candidates/`; the chosen
   base goes to `jarvis/web/static/identity/base.png`.

## Wire in
- The 3D face (`identity.js`, `loadSwarm`/`makeSwarm`/`makeGL`) samples
  `base.png` for particle positions and colours; replacing the file is enough.
- If the new face is darker or lighter, tune the particle weight
  (`0.35 + lum ** 1.15`) and alpha (`0.42 + 0.75 * L`) in `makeSwarm`.
- Then run the `jarvis-ship` skill.
