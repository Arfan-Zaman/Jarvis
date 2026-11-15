# Next session handoff

Read this first. Then `JARVIS_ROADMAP.md` (Phase 3) and `ARCHITECTURE.md`
section 4b (autonomous design).

## Where things stand (2026-11-16)

- Phases 1 and 2 and steps 3.1 and 3.2 complete. 192 tests passing.
- JARVIS runs on Qwen 3.5 9B in the Ollama desktop app (`.env`, git-ignored).
  Claude Code 2.1 is installed at `~/.local/bin/claude` and supports `-p`.
- **Owner's decisions:** act on its own and ask only for big risks; use Claude
  Code when needed, but learn once and do that kind of task locally next time;
  remember automatically (reviewable); self-improve with tests and Git as the
  safety net. Business specialisation later.
- Remote `origin` is GitHub; push only when the owner asks.

## Exact next task: steps 3.3 and 3.4, autonomy policy and internet

No installs needed.

### 3.3 Autonomy policy
1. Add permission levels `workspace` and `web_read` to `ActionCategory`; both
   run without approval (like write, refused in read-only mode). Keep
   `external_communication`, `financial`, `destructive`, `system` asking.
2. Create `~/JARVIS/workspace/` (git-ignored contents) and extend
   `SafetyLayer.authorize_path` so writes are allowed under `data/` and
   `workspace/` only.
3. A readable policy summary on the System page and in `jarvis.info`.
4. Tests for every level, and that the hard four still pause for approval.

### 3.4 Internet (read-only, automatic)
5. `web.search` (`web_read`): free, keyless search using DuckDuckGo's HTML
   endpoint via `urllib`; returns title, URL, snippet; timeout; polite
   User-Agent with no personal details; results capped.
6. `web.fetch` (`web_read`): fetch one http(s) URL, strip HTML to readable
   text with `html.parser`, size cap, refuse non-http schemes and local or
   private addresses.
7. Chat: questions about current events or facts JARVIS cannot know route to
   act with these tools; answers cite source URLs.
8. Tests with a fake local HTTP server (no internet in tests); private-address
   refusal; caps; parse failures handled.
9. Real model: three questions that need the web; check sources are real.
10. Update README, DEVLOG, ARCHITECTURE, ROADMAP and this file. Commit.

Then 3.5 (sandboxed code runner), 3.6 and 3.7 (skills and the Claude Code
bridge: learn once).

## Rules for the session

- Standard library only. No new installs or downloads without the owner's approval.
- Everything stays in `~/JARVIS`.
- All actions go through `app.tools.execute`; no unrestricted shell, ever.
- Never report something as working unless a test or a real run showed it.
- Real-model checks use a throwaway `JARVIS_DATA_DIR`, not `data/`.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md, JARVIS_ROADMAP.md and
> ARCHITECTURE.md, then implement steps 3.3 and 3.4 (autonomy policy and
> internet) exactly as described. Standard library only, no installs, preserve
> existing tests, test with the real local model, update the docs and commit.
> Do not push. Keep the report short and in plain language.
