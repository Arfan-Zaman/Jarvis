# JARVIS development log

Newest entries first. Record what changed, why, and what was verified.

## 2026-11-16 — Clap detector retuned on real claps

- The owner reported missed claps. The new diagnostic log
  (`data/logs/desktop.log`: every loud sound with its peak, suddenness,
  zero-crossing rate, brightness and the reason for the decision) showed all
  three real double claps were heard: peak 0.09-0.30, 22-95x the room level,
  faded within 10-20 ms, pairs about 450 ms apart. All were rejected as "not
  clap-like" because the MacBook Pro microphone makes claps dull (zero-crossing
  rate 0.04-0.10, against the 0.12 required).
- New rule: peak at least 0.06, at least 12x the room level, faded within 60 ms,
  and a "brightness" check that only rejects deep thuds. Tests added with dull,
  real-style claps; single and slow claps, knocks and speech are still ignored.
- The log stays on so future tuning uses real data.

## 2026-11-16 — JARVIS Desktop: floating orb, double clap, auto-start

### Built
- `desktop/JARVISDesktop.swift`: a native AppKit app (no Dock icon) showing a
  floating, draggable orb on all Spaces. It starts the JARVIS server if it is
  not running, listens to the microphone for a double clap, then records until
  the speaker stops, sends the audio to `/api/voice/transcribe`, requires the
  word "Jarvis" (a click skips that), sends the request to `/api/chat`, shows
  the reply and speaks it via `/api/voice/speak`. "Jarvis" alone gets "Yes,
  sir?" and a follow-up listen. Right-click menu: open, mute, quit.
- Clap detector: 10 ms frames; onset needs peak at least 0.12, at least six
  times the recent level, and a zero-crossing rate of at least 0.12
  (noise-like); it must fade to a quarter within 120 ms; two such claps 120 to
  700 ms apart; 1.5 s cooldown. `--test-clap file.wav` runs it on a recording.
- `jarvis/desktop.py` and `python3 -m jarvis desktop build|install|uninstall|status`:
  compiles with `swiftc` (Command Line Tools, no install), writes Info.plist
  (microphone reason, project paths), signs ad hoc, and installs a LaunchAgent
  (`local.jarvis.desktop`) that opens the app at login.

### Verified
- 233 tests passing (227 existing, 6 new): packaging; the bundle builds and
  verifies; the detector triggers on a double clap (loud and soft) and not on a
  single clap, slow claps, knocks, silence or speech, including speech saying
  "clap clap".
- Installed on the owner's Mac: the app is running and started the server
  itself (voice endpoints available). Not verified here: real hand claps and
  the microphone permission prompt, which the owner must allow.

## 2026-11-16 — Phase 3.5: voice

### Built
- `jarvis/voice.py`: transcribe (ffmpeg to 16 kHz WAV, then whisper.cpp with
  `data/models/ggml-small.en.bin`; non-speech markers removed) and speak (macOS
  `say`, voice Daniel by default, AAC/M4A). Argument lists only, never a
  shell; text to speak goes in a file; temporary audio is deleted.
- API: `GET /api/voice/status`, `POST /api/voice/transcribe` (raw audio body),
  `POST /api/voice/speak` (returns `audio/mp4`). The security policy allows
  `blob:` media so the browser can play the reply.
- Chat: microphone (click to start, click to stop), speaker toggle (remembered
  per browser), spoken questions get spoken answers, "go to sleep" phrases.
- Config: `JARVIS_WHISPER_MODEL`, `JARVIS_VOICE` (validated), `JARVIS_VOICE_RATE`.
- The chat self-description now says JARVIS can search the web and talk; it
  still said "cannot browse the web" from before Phase 3.4.

### Verified
- 227 tests passing (212 existing, 15 new), including a real round trip: JARVIS
  speaks a sentence and transcribes it back.
- Spoken conversation through the server on a throwaway database: questions
  heard exactly in about 1 second; "remind me to call the bank tomorrow
  morning" created the task and was answered aloud.
- Browser: microphone and speaker buttons present; a reply was spoken (speak
  request 200), no console errors. The microphone itself was not exercised from
  the automated browser (no microphone there).

## 2026-11-16 — Reference videos studied; roadmap updated

- The owner shared four Instagram reels showing JARVIS-style assistants.
  Downloaded with yt-dlp (already installed) into `data/media/reels`
  (git-ignored, private reference), transcribed locally with whisper.cpp
  (installed with the owner's approval; model `ggml-small.en`, 480 MB, in
  `data/models`), and reviewed frame by frame.
- Features seen: voice with personality, arc-reactor status HUD, knowledge
  graph "brain", visual research boards controlled by voice, proactive calls
  and overnight reports, AI phone calls to businesses.
- Roadmap: voice (3.5) and the HUD (3.6) move first; research boards, alerts
  and briefings, and the brain view are added; phone calls are listed as a
  later owner decision because they need a paid telephony service.

## 2026-11-16 — Phases 3.3 and 3.4: autonomy policy and internet

### Built
- Permission levels `web_read` (allowed even in read-only mode) and `workspace`
  (allowed unless read-only). The four asking levels are unchanged. The policy
  is reported in status and shown on the System page.
- `~/JARVIS/workspace/` (git-ignored); `authorize_path` allows writes under
  `data/` and `workspace/` only.
- `jarvis/tools/web.py`: `web.search` (Wikipedia REST search and DuckDuckGo
  instant-answer API, keyless; Brave Search if `JARVIS_BRAVE_API_KEY` is set)
  and `web.fetch` (clean page text, size cap, `focus` keeps the matching parts
  of long pages; refuses non-http(s) URLs and private or local addresses,
  including on redirect).
- Chat routes internet questions to act; the protocol says read a given URL
  rather than search, and retry with a different search when results miss.
  Answers end with Sources taken from the run log (pages read; search hits
  only if nothing was read).
- Web reads are not counted as "changes made".

### Decisions
- DuckDuckGo's HTML results page answered automated requests with a bot
  challenge. It is not used, and no attempt is made to get around it.
- The search key is read from `.env` and never shown (`public_dict` masks it).

### Found with the real model, then fixed
1. Given a URL, it searched instead of reading it.
2. Sources listed search hits it never read (the Ruby article for a Python
   question).
3. A long page was cut off before the answer; `focus` now extracts the
   matching parts.
4. After a miss it gave up; the review step now retries with a new search.

### Verified
- 212 tests passing (192 existing, 20 new); web tests use a fake local server.
- Real model: Python's creator (correct, cited), python.org downloads (read the
  given page), Bhutan's capital and population (correct, two sources).
  Australia's tallest mountain still fails honestly: keyless search returned
  the wrong Wikipedia page.

## 2026-11-16 — Phase 3.2: memory of you

### Built
- Schema v5: `knowledge_fts` (FTS5, porter stemming) over memories and
  experiences, kept in sync by triggers and back-filled on upgrade;
  `messages.memory_refs` and `messages.memory_offer`.
- `jarvis/engine/context.py`: ranked search (bm25 weighted by verification and
  confidence), personal facts always included, size budget, project scope.
- Chat answers get "What you know about the owner" with ids; the reply's
  `[memory: …]` marker becomes "From memory" chips (only ids actually supplied).
- REMEMBER mode saves at once as `user:chat`, `user_provided`. Passing personal
  facts become an offer; "yes" saves, "no" declines, moving on drops it.
- Goals (`Engine._recall`) and `memory.search` use the index.

### Found with the real model, then fixed
1. It saved passing remarks, and even a bare "Yes"/"No", without asking. Now an
   immediate save requires the owner's own words ("remember", "note that",
   "don't forget"…), checked in code; otherwise it can only offer.
2. Facts were written as "The user prefers…". The router asks for first person.
3. While offering, it claimed "I have noted / logged / flagged that". Plain
   statements now get "Understood." plus the offer; for questions, sentences
   claiming something was kept are removed.
4. It refused general advice (dinner ideas) as if that needed the web. The chat
   prompt now allows general knowledge and suggestions.
5. A trailing full stop defeated duplicate detection. Fixed.

### Verified
- 192 tests passing (174 existing, 18 new).
- Real model: remember, offer then yes, offer then no; a new conversation
  used and cited the saved facts.

## 2026-11-16 — Phase 3.1: one conversation that thinks and acts

### Built
- `jarvis/engine/conversation.py`: for each chat message the model routes to
  ANSWER or ACT (JSON). ACT runs the reasoning engine on a restated goal.
- Truthful replies: what JARVIS did is written in fixed wording from the run
  log ("Done. I added the task …"). The model phrases only look-up answers,
  from the data the tools returned. Chosen over model-written summaries because
  the real model was seen inventing actions (Phase 2.3).
- Follow-ups: when the last reply asked a question, the next message resumes
  that run as the answer; "never mind" and similar cancel it.
- Approvals are explained in chat; chat text never approves anything.
- The chat system prompt is generated from the live tool list and includes the
  owner's local date and time.
- Schema v4: `messages.run_id`; chat shows an action card (status, changes,
  Details, Review approval, Continue).

### Found with the real model, then fixed
1. No sense of today's date: "tomorrow" became today. The model now gets the
   local date and time in plans, chat and look-up answers.
2. It attached a task to a project the owner never mentioned. The protocol now
   forbids picking a project.
3. Clumsy reports ("added …, updated …, updated …"). Updates to a task just
   created are folded into "added"; duplicates are removed.
4. A look-up labelled a project wrongly. Look-up answers now get project names.

### Verified
- 174 tests passing (155 existing, 19 new).
- Real conversation on a throwaway database: small talk, maths, a reminder with
  the correct date and no guessed project, a clarifying question then
  completion, a task list, saving a preference, declining email.

## 2026-11-16 — Phase 2.3: local model connected

### Installed (owner approved)
- Ollama desktop app 0.40.16 via Homebrew cask `ollama-app`. It starts at login
  and runs in the background (the owner chose this over on-demand).
- Model `qwen3.5:9b` (7.6 GB on disk). The first download was cut off when the
  network dropped and resumed on retry.
- `.env` created (git-ignored): `JARVIS_AI_PROVIDER=ollama`,
  `JARVIS_AI_MODEL=qwen3.5:9b`.

### Changed
- `generate(messages, json_output=False)` across providers. The engine always
  asks for JSON; Ollama gets `format: "json"`, `think: false`, low temperature.
- New REVIEW stage. After every step succeeds, the model must confirm the goal
  was achieved. If not, it may add steps once; otherwise the run fails with
  what is missing. An unusable review means "not confirmed", never "done".
- Reports list `changes_made` (successful non-read tool calls) and the headline
  says how many changes were made.
- The model sees the project list and the owner's answers folded into the goal
  text. The protocol says when to ask and forbids guessing.
- The chat system prompt lists what JARVIS can and cannot do.

### Found by testing with the real model, then fixed
1. A plan that only looked up projects was reported "verified complete", and
   the model claimed it had added the task. Fixed by the REVIEW stage.
2. An ambiguous "the business" was silently assigned to one project. Fixed by
   the ask-don't-guess rule.
3. The first fix over-corrected (it asked even when the project was named or
   not needed). Fixed by showing the model the project list.
4. After answering a question, the model asked it again. Fixed by putting
   answers into the goal text.
5. Chat claimed JARVIS could send email and manage a calendar. Fixed with an
   accurate capability list; it now declines and points to Goals.

### Verified
- 155 tests passing (149 existing, 6 new; tests never need Ollama).
- Real model, throwaway database: four goals, all with the correct outcome
  (5 to 21 seconds each); chat answers honestly.

## 2026-11-15 — Phase 2.2: reasoning engine

### Built
- `jarvis/engine/engine.py`: plan, act, check, report. Model output is one JSON
  object per request (`plan`, `inputs`, `blocked`, `summary`); unusable output
  gets one retry, then the run fails.
- Every action goes through `ToolRegistry.execute` with actor `jarvis-core`
  and the run's allow-list. The engine has no other way to act.
- Run states: running, waiting_approval, blocked, completed, failed,
  cancelled, interrupted. Plan step states: pending, running, completed,
  failed, blocked.
- Limits (configurable): plan length, tool failures, model calls.
- Resume after approval, after an answer to a question, or after an
  interruption, without repeating finished steps.
- Schema v3: `run_plan` table, `runs.context`, `run_steps.plan_id`, and the
  `blocked` state (the `runs` table is rebuilt to change its CHECK constraint).
- `ScriptedProvider`: a stand-in that replays prepared replies, used only in
  tests and not selectable through configuration.
- Context: memories and lessons matching the goal's key words are shown to the
  model with their confidence and source.
- Each finished or failed goal is recorded once as an experience;
  `memory.save` returns an existing identical memory instead of a duplicate.
- API `POST /api/runs`, `/api/runs/<id>/resume|cancel`; CLI `goal`; Goals page.
- GitHub repository added as remote `origin`. Nothing pushed.

### Decisions
- "Verified complete" means every planned step has a recorded successful
  execution. The model's summary is stored and shown, labelled as unverified.
- A refused step ends the goal rather than retrying: refusal is a permission
  decision, not an error to work around.
- Engine bookkeeping (recording the experience) is a run step but not a plan
  step, so it cannot make or break verification.

### Verified
- 149 tests passing (114 existing, 35 new).
- Throwaway database: Goals page renders with a clear "no model" banner and a
  disabled button; `goal` command reports no model. No console errors.

### Not done
- Never run against a real model.

## 2026-11-15 — Phase 2.1: tools, execution engine, run log

### Built
- `jarvis/tools/registry.py`: `Tool` and `ToolRegistry`. One `execute` path:
  find tool, check allow-list, validate inputs, ask the safety layer, run,
  record, return a structured result. It never raises for a failed tool.
- `jarvis/tools/builtin.py`: 11 tools (6 read, 5 write) wrapping existing
  orchestrator methods, so validation and audit still apply.
- `jarvis/stores/runs.py` and schema v2: `runs` and `run_steps`.
- API: `/api/tools`, `/api/tools/<name>/execute`, `/api/runs`, `/api/executions`.
- Command line: `tools` and `tool`. System page: tools and recent executions.

### Decisions
- A tool's permission level is its existing safety category, so there is one
  permission system, not two.
- A direct tool call creates its own single-step run, so nothing executes
  without a log entry. Goal runs (Phase 2.2) will hold many steps.
- Memories saved by a tool record the real caller as the source and default to
  "unverified".
- An existing database is backed up (`pre-upgrade-v1`) before migrating.
- `REQUIRED_TABLES` stays at the version 1 set so older backups remain
  restorable.
- No destructive built-in tools yet; the approval path is tested with
  test-only tools.

### Verified
- 114 tests passing (90 existing, 24 new): registration, discovery, each
  built-in tool, invalid inputs, unknown tools, allow-list, crash containment,
  read-only mode, approval flow for all four sensitive categories, run log
  contents and retrieval, restart survival, interrupted runs, v1 upgrade, API.
- Real run on a throwaway database: CLI tool calls (success, bad input,
  unknown tool) and the System page panels. No console errors.

### Not done
- The live database in `data/` is still schema v1. It upgrades, with a backup,
  the next time JARVIS starts.
- No model, so nothing chooses tools yet.

## 2026-11-15 — Milestone 1: core foundation

### Environment at the time
- macOS 26.6.2, Apple M5, 16 GB memory, 258 GB free disk.
- Python 3.14.7 (Miniconda), SQLite 3.53.2, Git 2.50.1, Node 24.16.0 (unused).
- Nothing was installed for this milestone.

### Decisions
- **Standard library only.** The web server, database access, configuration,
  and tests all use what ships with Python. No virtual environment is needed
  and there is nothing to break on upgrade. Revisit only when a feature
  genuinely needs a dependency.
- **SQLite, one short-lived connection per operation**, WAL mode, foreign keys
  enforced. Simple and safe with the threaded web server.
- **Schema migrations** are an append-only list in `jarvis/db.py`, tracked with
  SQLite's `user_version`.
- **One generic store** (`stores/base.py`) gives every knowledge table the same
  metadata, validation, search, archive and delete behaviour.
- **Everything goes through the orchestrator.** The web API and command line
  never touch a store directly, so the safety layer and audit trail cannot be
  bypassed by accident.
- **Two-step approvals** for high-impact actions: request, human approves,
  then execute. Approvals are fingerprinted to the exact action, expire, and
  are single-use.
- **Archive is the default way to remove something.** Permanent deletion is
  classed as destructive and needs approval.
- **No fake AI.** With no provider, chat stores a `system` message, never an
  `assistant` one.
- **Loopback only.** The config rejects non-local hosts, and the server rejects
  foreign `Host` and `Origin` headers.
- **Seed data** is limited to the two business workspaces and the core agent,
  created once and never re-created if the user removes them.

### Built
Core orchestrator, AI provider abstraction, memory, experience/learning, task
manager, project manager, safety/permission layer, configuration manager,
logging, backup/recovery, the SQLite data model, the local web interface, and
the command line.

### Verified
- `python3 -m unittest discover -s tests`: 90 tests, all passing.
- Browser check against a throwaway database: dashboard, saving a memory, the
  permanent-delete confirmation, adding and completing a task, chat with no
  provider, the System page, and phone-width layout on all seven pages. No
  console errors.
- Command line check: serve, stop, status, backup, backups, restore (confirmed,
  cancelled, and invalid name).

### Fixed along the way
- A pre-restore backup could prune the very backup being restored. Pruning is
  now skipped for that backup, with a test.
- Forms lost their default values after saving.
- The page overflowed sideways at phone width.
- A slow page load could overwrite a newer one after quick navigation.
- A startup event was being logged by every command, not only by the server.

### Known gaps
- Ollama adapter tested only against a simulated server.
- The Claude Code preview launcher refused to start the server from
  `.claude/launch.json` (it reported the port as in use when it was not), so
  the browser check ran the server from a shell instead. The launch entry is
  kept but unverified.
- See "Current limitations" in the README.

### Next
Milestone 2: connect one local model (see README).
