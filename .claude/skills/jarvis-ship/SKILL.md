---
name: jarvis-ship
description: Finish any JARVIS change the owner's way - run tests, check the live UI in Chrome, log it, commit, push, restart the server. Use after every step of work in ~/JARVIS.
---

# Ship a JARVIS step

The owner wants every step pushed and nothing reported as working without proof.

1. **Tests:** `cd ~/JARVIS && python3 -m unittest discover -s tests`. All must pass.
   If a test pins old behaviour the owner changed on purpose, update that test
   and say so; never delete coverage.
2. **Syntax for front-end files:** `node --check jarvis/web/static/<file>.js`.
3. **Python changes need a server restart** (static files do not):
   `python3 -m jarvis stop; (nohup python3 -m jarvis serve >/dev/null 2>&1 &)`,
   then `curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/api/tools` → 200.
4. **See it:** in Claude in Chrome open `http://localhost:8765/#<page>`, run
   `location.reload()` (hash changes alone don't reload scripts), screenshot,
   and read console errors. The built-in browser pane is throttled when hidden,
   so prefer Chrome for animation checks.
5. **Log it:** add a dated section at the top of `DEVLOG.md` (what changed, how
   it was checked, test count). Update the status in `NEXT_SESSION.md` if the
   spec there moved.
6. **Commit and push:** `git add <files>` (never `git add -A`: `data/` and
   `workspace/` are private), commit with the session's attribution line, then
   `git push origin main`.
7. **Report** in a few plain lines: what changed, how it was verified, what is
   not done.
