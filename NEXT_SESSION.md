# Next session handoff

Read this first. Then `JARVIS_ROADMAP.md` (Phase 3) and `ARCHITECTURE.md`
section 4b (autonomous design).

## Where things stand (2026-11-16)

- Phases 1 and 2 and steps 3.1 to 3.4 complete. 212 tests passing.
- JARVIS runs on Qwen 3.5 9B in the Ollama desktop app (`.env`, git-ignored).
  Claude Code 2.1 is installed at `~/.local/bin/claude` and supports `-p`.
- Chat talks and acts, remembers the owner, acts without asking for everyday
  work (asks only for destructive, external, financial and system actions), and
  searches and reads the web with sources. Keyless search is Wikipedia and
  DuckDuckGo instant answers; an optional `JARVIS_BRAVE_API_KEY` adds full web
  search.
- **Owner's decisions:** autonomous within the hard lines; Claude Code once per
  kind of task, then reuse locally as a skill; automatic reviewable memory;
  self-improvement behind tests and Git. Business work later.
- Remote `origin` is GitHub; push only when the owner asks.

## Exact next task: step 3.5, the code runner

No installs needed.

1. `jarvis/tools/code.py`: tool `code.run` (permission `workspace`). Inputs:
   `code` (Python source), optional `filename`, `timeout` (default 30 s, max
   120), `args`. Writes the file under `workspace/runs/<run-id>/` and runs it
   with the same Python as JARVIS as a child process, with cwd in that folder.
2. Sandbox: run through macOS `sandbox-exec` with a profile that denies file
   writes outside the run folder and `workspace/`, and denies network unless
   the call sets `network: true` (then outbound only). Verify `sandbox-exec`
   exists; if it does not, refuse to run rather than run unsandboxed.
3. Limits: timeout (kill the process group), output capped (e.g. 20,000
   characters each for stdout and stderr), environment stripped of secrets
   (no `JARVIS_BRAVE_API_KEY`, etc.).
4. Result: exit code, stdout, stderr, duration, files created (names and sizes).
5. `code.read_file` / `code.write_file` (`workspace`) for files under
   `workspace/` only, via `SafetyLayer.authorize_path`.
6. Engine protocol: for calculations, data processing or anything a short
   script does better, write and run code; check the result before using it.
7. Tests: success, syntax error, timeout kill, output cap, write outside the
   workspace blocked by the sandbox, network blocked by default, secrets absent
   from the environment, refusal when the sandbox is unavailable.
8. Real model: "what is the 50th Fibonacci number", "make a CSV of the next 12
   months with their number of days and save it in my workspace", "count the
   words in this text: …".
9. Update README, DEVLOG, ARCHITECTURE, ROADMAP and this file. Commit.

Then 3.6 and 3.7: skills and the Claude Code bridge (learn once).

## Rules for the session

- Standard library only. No new installs or downloads without the owner's approval.
- Everything stays in `~/JARVIS`.
- All actions go through `app.tools.execute`; no unrestricted shell, ever.
- Never report something as working unless a test or a real run showed it.
- Real-model checks use a throwaway `JARVIS_DATA_DIR`, not `data/`.

## Prompt to paste

> Continue JARVIS. Read NEXT_SESSION.md, JARVIS_ROADMAP.md and
> ARCHITECTURE.md, then implement step 3.5 (the sandboxed code runner) exactly
> as described. Standard library only, no installs, preserve existing tests,
> test with the real local model, update the docs and commit. Do not push.
> Keep the report short and in plain language.
