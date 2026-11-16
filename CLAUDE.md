# JARVIS: standing rules for every Claude session

The owner set these rules on 2026-11-16 and should never have to repeat them.

## Local first, Claude only when needed
- JARVIS's own local model (Ollama, `JARVIS_AI_MODEL`, now qwen3.5:9b) is the brain by default
  (`JARVIS_BRAIN=local`). It answers, plans, reads web pages and drives the browser itself.
- JARVIS calls Claude Code only for writing or fixing code, building things as files, deep multi-source
  research, a request its own way could not answer, and the gap loop below. Never add a path that sends
  everyday chat to Claude.
- Web: `browser.search` / `browser.read` / `browser.use` work in JARVIS's own Chrome (Playwright MCP over
  stdio, persistent profile `data/browser-profile`). Free open APIs are under `jarvis/tools/opendata.py`;
  add more keyless open services there.

## The gap loop: JARVIS gets better over time
1. When JARVIS cannot do something on its own, `jarvis/gaps.py` records a gap. The owner can also say
   "learn to ..." to add one.
2. The self-review (`jarvis/selfreview.py`) hands the open gaps to Claude Code with a brief to build each
   ability INTO JARVIS (a tool, a route, a prompt, a fix, or a skill), with tests. It runs every
   `JARVIS_TEACH_HOURS`, or at once when the owner asks.
3. The work lands on a `jarvis/self-review-*` branch and waits for the owner's Approve on the System page.
   Anything that needs a download, a new dependency, a paid service or a permission goes under
   "Needs the owner" in SELF_REVIEW.md. It is never added silently.
4. A Claude session working on JARVIS should read the open gaps first: `gaps.open` in settings, or the
   `gap.recorded` events. Build those abilities into JARVIS, so it needs Claude less each time.

## Hard lines (unchanged)
- Approvals come only from the UI Approve button, never from chat or speech. Anything that sends, pays,
  deletes, posts or runs commands asks first. Never buy anything or turn on paid add-ons.
- No new installs or downloads without the owner's OK. Never weaken `jarvis/safety.py`.
- The owner's personal email never goes in the repo.

## How to ship
- Keep the tests green (`python3 -m unittest discover -s tests`), add a DEVLOG entry, commit, push after
  every step, and restart the server. The `jarvis-ship` skill does all of this.
