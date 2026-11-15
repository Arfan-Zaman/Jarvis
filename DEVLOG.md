# JARVIS development log

Newest entries first. Record what changed, why, and what was verified.

## 2026-11-16 — Long Claude jobs are visible; faster default model

- Chat looked broken because Claude Code jobs ran for 6+ minutes behind a
  silent "Thinking…". `/api/live` now reports a running claude.*/image.* tool
  run ("Working with Claude Code… 1m 20s"); the face and the Chat page's
  thinking bubble show it.
- `claude.work` uses Sonnet by default (`JARVIS_WORK_MODEL`, e.g. opus).
- "Code/improve yourself" requests get a plain answer pointing to Self-review
  (Claude Code works in the workspace and cannot change JARVIS itself).
- 281 tests pass.

## 2026-11-16 — Chat and the JARVIS page share one conversation

- Owner reported Chat "not working": it worked, but the Chat page and the JARVIS
  page kept separate conversations (and a reload started a new one), so JARVIS
  lost the thread when the owner switched pages (conversation 20 vs 22).
- Now one continuing conversation is stored in the browser and used by both
  pages; it resets after 3 quiet hours or with "+ New conversation".
- Chat page: paperclip attach button and drop-onto-messages, same uploads as the
  JARVIS page.
- Checked in Chrome: a codeword told on the JARVIS page was recalled on the Chat
  page in the same conversation; paperclip present; no console errors.

## 2026-11-16 — Merged image generation and weekly self-review

- Merged `claude/self-review-0dbf57` and `claude/image-generation-4646c9`
  (change-log, router, UI and test conflicts resolved by keeping both sides).
- Hardened on merge: the image tool now denies the bare Read/Grep/Glob names
  (it had picked up the new path-scoped list, which would only have denied
  workspace reads); self-review's Read/Edit/Write are confined to its own
  worktree; both pass the prompt after `--`.
- Spending is approved only with the Approve button: a spoken or typed "yes"
  no longer generates a picture ("no" still cancels). The one-click card now
  handles single-tool approvals by re-running that exact call with the
  approval. 281 tests pass; live server restarted, System page shows the
  Self-review panel, all six Claude/image tools registered.
- Not yet run for real: a self-review pass, and a real picture (the higgsfield
  connector is still on the 0-credit account).

## 2026-11-16 — Browser, files and photos, security hardening

- `claude.browse` (system category, asks first): Claude Code drives a real
  browser through Playwright MCP (pinned 0.0.85, private signed-out profile,
  file uploads disabled, rules: never buy, sign in, send, post, solve
  CAPTCHAs). Chat routes "go to this site and..." requests to it. Real run:
  read Hacker News' top stories in 22 s.
- Uploads: `POST /api/files` (25 MB, allow-listed types, safe names, exclusive
  create in `workspace/uploads/`, never executed); `/api/chat` takes
  `attachments`, checked to be real uploads; messages with files go to Claude
  Code, which reads them (images and PDFs too). JARVIS page: paperclip button
  and drop-anywhere. Real runs: answered from a text note and described a
  photo correctly.
- One-click Approve / Deny under the reply on the JARVIS page (approval is
  still never granted by speech or chat text).
- Security review (independent agent) and fixes: Claude Code reads/writes now
  confined to the workspace with path rules (a bare `Read` could read
  `~/.zshrc`, verified, now denied); `claude.operate` (shell) is off unless
  `JARVIS_OPERATE=1`; task text passed after `--`; research sends only the
  query, no personal context. Verified: a poisoned uploaded note asking to
  read ~/.zshrc leaked nothing. Confirmed safe: loopback-only server,
  Origin/Host checks, CSP, static path checks, no innerHTML of content.
- 255 tests pass.

## 2026-11-16 — Weekly self-review (owner approves every change)

- `jarvis/selfreview.py`: every `JARVIS_REVIEW_DAYS` (default 7) while idle
  (off with `JARVIS_REVIEW=0`), JARVIS cuts a git worktree under
  `workspace/self-review/<date>` on `jarvis/self-review-<YYYY-MM-DD>` from
  `main`, hands Claude Code the jarvis.log tail, failed runs and DEVLOG, and
  lets it make up to 3 small fixes there, commit them and explain them in
  `SELF_REVIEW.md`. Claude runs headless with no MCP servers and project
  settings only; Bash is limited to the test suite and a few git commands
  (status/diff/log/show/add/commit); push, merge, checkout, branch are denied.
- A proposal that touches `jarvis/safety.py`, `jarvis/selfreview.py`,
  dependency files, `.claude/` or `.env` is discarded automatically; an empty
  one leaves no branch behind.
- Owner only, from the System page "Self-review" panel: Approve tries the
  `--no-ff` merge in a scratch worktree, runs the tests on the merged result,
  and only then fast-forwards `main` to that tested merge (refuses if main is
  not checked out or is dirty). Never pushes. Reject deletes branch + worktree.
  Both act only on `jarvis/self-review-*` branches. No tool exposes them.
- API: `GET /api/self-review`, `POST /api/self-review/run`,
  `POST /api/self-review/<branch>/approve|reject`.
- Verified: `tests/test_selfreview.py` (fake Claude, real temp git repo:
  naming, protected files, merge refused on failing tests, branch guard,
  routes); full suite 262 tests OK. Not yet run against real Claude Code.

## 2026-11-16 — Pictures on Higgsfield ("Jarvis, make me a picture of …")

- New `jarvis/tools/images.py`: `image.quote` (automatic, spends nothing:
  balance + `generate_image` with `get_cost: true`) and `image.generate`
  (financial: the safety layer asks the owner every time; `max_credits` is the
  quoted price and is part of the approval). Both run Claude Code headless like
  `claude.py`, but with only the `higgsfield` server from `.mcp.json` and only
  the four Higgsfield tools allowed (no shell, files or web). Model
  `gpt_image_2_6`, one image, `use_unlim: false`; Claude re-checks the price
  and refuses above the approved cost, and JARVIS flags any charge above it.
  JARVIS downloads the image itself (https only) to
  `workspace/images/<timestamp>-<slug>.png`.
- Chat: new "image" route (router mode plus a wording catch). JARVIS replies
  with the cost and balance and waits; "yes" approves and makes it, "no"
  denies it and nothing is spent. If the balance is below the cost it says so
  and asks for nothing.
- `GET /api/files/<path>` serves files inside the workspace only (traversal
  refused); only plain images and text are served as themselves, anything
  else as a download, so workspace HTML never runs on JARVIS's origin. The chat
  shows any `workspace/images/…` path in a reply as the picture.
- Verified: 13 new tests (Claude never run) and the full suite green. A live
  headless `balance` call through the project connector returned
  `{"credits":0,"subscription_plan_type":"free"}`: it is still signed in to the
  owner's OLD account. A live `image.quote` through the real code priced one
  high 2k `gpt_image_2_6` picture at 2.75 credits (balance 0, free plan).
  No image was generated and no credits were spent. To use
  the paid Plus account: sign out of higgsfield.ai in the normal browser, then
  in Claude Code `/mcp` → higgsfield → clear authentication → authenticate
  with the new account.

## 2026-11-16 — Interrupt and mute

- While JARVIS thinks or talks, a quiet second listener runs; hearing
  "Jarvis" stops speech instantly (also mid-sentence and while audio is still
  loading) and what follows the name is sent in the same conversation, so the
  answer takes the whole exchange into account. Its own voice saying "Jarvis"
  is ignored.
- A press on the face while it thinks or talks mutes it (the pending reply is
  not spoken) until it is called again.
- Checked in Chrome: stop takes 0-1 ms at 0.8 s and 2.5 s into a reply; no
  console errors. The spoken barge-in itself needs the owner's voice to try.

## 2026-11-16 — Free full-web learning through Claude Code

- Owner wanted a free-for-life search. SearXNG was rejected: it scrapes Google
  and Bing and ships `curl_cffi` to disguise requests as a browser, i.e. it
  works around bot detection, which JARVIS does not do. Marginalia's free API
  did not respond. Chosen: Claude Code's own web search, already paid for by
  the owner's plan and allowed.
- New read-only tool `claude.research` (WebSearch + WebFetch only, Haiku,
  `JARVIS_RESEARCH_MODEL`): returns short facts each with its source URL.
  Learning uses it first and falls back to basic search
  (`JARVIS_LEARN_SOURCE=web` forces basic).
- All Claude tools now run with `--setting-sources project`: the owner's
  personal plugins and hooks (context-mode blocked WebFetch) are not loaded.
- Optional `JARVIS_SEARXNG_URL` search support stays in `web.py` for an
  owner-run instance limited to engines with official APIs.
- Real pass: "top 10 most reliable used cars Australia 2024", 3 sourced facts
  from CarsGuide in 36 s (~3 US cents of plan usage per pass). 248 tests pass.

## 2026-11-16 — Continuous learning

- `jarvis/learner.py`: while the server runs, every 30 minutes when idle
  (`JARVIS_LEARN_MINUTES`, off with `JARVIS_LEARN=0`), JARVIS picks one new
  search query from the owner's projects, stated facts and recent chats,
  searches, reads up to two pages and saves up to three durable facts per page
  as unverified "learned" memories with the source URL. All through
  `tools.execute` (actor `jarvis:learn`), logged as a `learning` event.
- `GET /api/learn`, `POST /api/learn/run`; a Learning panel on the Memory page
  with "Learn now" and recent topics.
- Real passes: throwaway data (16 s, 3 facts) and the owner's server (19 s,
  6 facts, topic taken from a recent chat). Search reaches only Wikipedia and
  DuckDuckGo instant answers until a Brave Search key is set.
- 2 new tests (scripted model, faked web).

## 2026-11-16 — Claude Code signed in; its answers reach the owner

- Owner confirmed the wake word works with a real voice, and signed in the
  `claude` CLI.
- Real check: a coding request went through the planner to `claude.work` and
  came back in 18 s. Runs that used Claude Code now reply with its result
  instead of "I ran claude.work."

## 2026-11-16 — Wake word and purposeful motion

- Hands-free is now on by default on the JARVIS page: it listens quietly,
  transcribes short utterances locally (whisper.cpp) and ignores anything
  without its name; "Jarvis" (alone, or followed by a request) starts a
  conversation; ~25 s of silence or "stop" returns to waiting. One toggle
  ("Hands-free: on/off"), remembered per browser.
- The periodic split-and-fly cycle is gone. Motion now has a cause: first load
  builds the face from the rings layer by layer; thinking re-places a thin band
  as a build line passes (the face stays whole); executing and success sweep a
  scan line; failure breaks one side off and rebuilds it; voice ripples the
  surface; the cursor parts the bots; a click sends a ripple from that point.
- Ultron likeness declined (Marvel IP); the face stays original.
- Checked in Chrome: build on load, intact thinking face, hands-free on and
  waiting for the name, no console errors.

## 2026-11-16 — Emotion, hands-free talk, auto-learning, full-power mode

- Spec for a living JARVIS written at the top of `NEXT_SESSION.md`.
- Emotion: four new swarm states (warm/amber with a buoyant pulse, curious/
  violet leaning in, sad/blue sinking and dim, angry/red trembling with the
  voice). Replies are spoken sentence by sentence; each sentence's feeling
  (`feel()` in app.js) sets the state while it plays, and the next sentence's
  audio is prepared during playback, so speech starts sooner.
- Hands-free conversation on Presence ("Start conversation"): listens, detects
  the end of speech by silence, answers aloud, listens again; "stop
  conversation" ends it.
- Auto-learning: lasting facts said in chat are saved without asking
  (`JARVIS_AUTO_LEARN`, default on) as unverified, source `jarvis:learn`.
- `claude.operate`: Claude Code with shell, confined to `workspace/`, system
  category, so JARVIS asks the owner every time.
- Project skills: `.claude/skills/jarvis-ship` and `.claude/skills/jarvis-art`.
- Checked in Chrome: sentence feelings classify correctly, speech endpoint
  returns audio, sad/angry/warm render distinctly, no console errors. 246 tests
  pass. Not yet tried with a real microphone conversation.

## 2026-11-16 — HUD on every page

- `hud.css` (loaded last) reskins every page through the shared parts:
  obsidian room with a faint scan grid, panels framed by magenta corner
  brackets, readout rules after headings, instrument-style numbers, magenta
  controls and focus, chat replies as a lit edge, hairline lists and tables.
- A small live JARVIS (compact swarm) sits in each page header and follows
  `/api/live`; hidden on the Presence page.
- Checked Dashboard, Chat, Tasks and System in Chrome with real clicks; no
  console errors; 243 tests pass.

## 2026-11-16 — 3D face (WebGL) and HUD Presence page

- The swarm now renders with WebGL (no library): soft glowing sprites,
  additive light so the bots look see-through, a bloom pass, depth fog, and
  three tilted 3D rings of bots spinning in their own planes, all turning with
  the gaze. Canvas 2D stays as the fallback.
- Presence page: the grey stat cards are gone. Readouts (health, tasks,
  memories, tools) are HUD callouts pinned to the reticle with leader lines;
  the side column is a quiet activity log. Collapses to a grid under 900px.
- Checked in Chrome on 8765 (WebGL active, no console errors); 243 tests pass.

## 2026-11-16 — Claude Code as JARVIS's deep mind

- New tool `claude.work` (`jarvis/tools/claude.py`, category workspace): runs
  `claude -p` in `workspace/` with Bash disallowed, no MCP servers, no saved
  session, 15-minute limit. Read and web search only unless `write_files`, then
  Edit/Write inside the workspace only.
- Chat router has a new "delegate" mode for code, building, in-depth research,
  analysis, long writing and planning; a keyword backstop catches hard requests
  the 9B router calls "answer". If Claude Code fails, the local model answers
  and the reply says why (e.g. signed out).
- Real check: the router delegated coding and page-building requests; the call
  failed only because the `claude` CLI is signed out (OAuth expired), and the
  reply said so. 243 tests pass (3 new, Claude never run in tests).

## 2026-11-16 — Nanobot swarm face

- `base.png` generated on Higgsfield (GPT Image 2, 2K, owner chose version 1;
  version 2 kept in `data/media/identity_candidates/`).
- `identity.js`: swarm mode. ~3,200 particles (1,300 compact) sampled from
  `base.png` assemble into the face, divide into five fragments that orbit the
  core, merge again at a shifted spot and drift home (16 s calm, 9 s executing).
  State colour, burst on success, scatter on failure, voice level on the eyes,
  gaze tilt. Physics is step-based, so a throttled tab still converges. Falls
  back to the still art, then the vector face. Checked in Chrome on port 8765;
  240 tests pass.

## 2026-11-16 — Art mode for the face (rendered character)

- `identity.js` now has an "art mode". `GET /api/identity/assets` lists which
  rendered files exist in `jarvis/web/static/identity/` (fixed names: see
  NEXT_SESSION.md). If any exist, the vector face hides and the art shows:
  the state's still (or its loop: idle/thinking/executing) crossfades in once
  fully loaded; live eye glow uses the state table's colour, glow and eye
  opening; the voice level drives the eyes while speaking; the cursor gives a
  subtle 3D tilt; the canvas core stays behind as a halo. A state with no still
  of its own uses `base.png` (glow still shows the state colour). With no
  files at all, the vector face is used unchanged. States still come only from
  real events; the preview stays labelled as a simulation.
- Verified in the browser (throwaway data dir, temporary placeholder PNGs,
  since deleted): Presence and desktop views enter art mode, listening swaps
  in its still, analysing falls back to base, no files gives the vector face,
  no console errors. 240 tests pass (including a new test for the asset endpoint).
- Not done yet: the art itself. The Higgsfield account connected had 0
  credits; quote given (about 33 credits for base plus 11 stills at 2K high,
  plus 105 for three 720p loops or 240 at 1080p). The owner is switching the
  connector to a new account. Eye positions in `ART_EYES` must be matched to
  the real render once it exists.

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
- Second real test: both double claps detected. One request was lost because
  "Jarvis" was said before recording began, so the transcript lacked the name;
  the other because the speech (rms 0.015-0.02) was below the fixed 0.016
  "speaking" threshold. Fixes: a 1.5 s pre-roll is prepended to each recording;
  speech is judged against the measured room level (5x, minimum 0.005); 8 s to
  start speaking; the name is optional after a double clap (the clap is the
  call). Recording outcomes are logged.
- Third real test: the owner confirmed JARVIS woke and answered. The claps
  themselves, kept in the pre-roll, were transcribed as a stray word ("Amen"),
  so the pre-roll is now cleared at the moment the double clap is recognised.

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
