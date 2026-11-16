# JARVIS development log

Newest entries first. Record what changed, why, and what was verified.

## 2026-11-16 — JARVIS installs skills and software itself; talks like a person

- `jarvis/tools/skills.py`: `skills.search` (GitHub: SKILL.md files and skill repos), `skills.install`
  (downloads the repo archive, keeps only instruction files; scripts and binaries are left out and listed;
  the owner approves each install), `skills.list`, and `system.install` (pip / npm / brew, argument lists,
  checked package names, one approval). Installed skills live in `workspace/.claude/skills`, where Claude
  Code sees them too.
- The local brain uses the installed skill that fits a request (`skills.relevant`) as advice in its answer.
- Routing: "download/install/set up skills" and "pip/npm/brew install X" go to these tools, not Claude.
- Voice: new speaking rules (match the size of the question, plain talk, no headings or bullets in
  conversation, no preambles or closing offers). The 50-line ability list goes into the prompt only when
  the owner asks what JARVIS can do, since it pulled replies toward reciting features.

## 2026-11-16 — Self-review: learning passes no longer wasted on repeats

- `Learner.pick()` refused repeats of the last 50 queries but only showed the model 25. It now shows them
  all and retries once when the model repeats; the skip message says whether the reply was unreadable or a
  repeat (log 21:37:19 "no new query chosen").
- Tests: 356 OK.

## 2026-11-16 — Self-review: domain lookups (gap from run #237)

- `open.domain` (RDAP via IANA's registry list, free, read-only): registered or available, registrar,
  holder if public, dates, nameservers; `.au` notes auDA's ABN/ACN rule.
- Domain questions ("is x.com.au available", "who owns ...", "whois ...") go straight to it
  (`DOMAIN_CHECK` → `_quick_tool`) instead of the browser agent.
- Browser agent reads refs written as `[ref=e5]`, `ref=e5` or under `target`.
- Tests: 353 OK. Live RDAP not checked yet (no network in the review session).

## 2026-11-16 — Fixes from the owner's real chats ("worse than a school project")

Read the last 70 messages. What was broken, and what changed:
- Trapped in an old question: after "Where is the file?", every later message ("Can you build
  agents?", "new capabilities?") was taken as the answer. Now only an answer resumes it; a new request
  drops the old question (`NEW_REQUEST`).
- Approving in words looped ("I approve" x4 -> the same "approve on the System page"). Chat now has
  Approve and Deny buttons on the message; saying "approved" points at them (`SAYS_APPROVE`).
- File search needed exact names: "Aureus Dailing" in Documents was never found. Now typo-tolerant,
  skips JARVIS's own code, returns found folders with their contents; new `mac.list_folder` and
  `mac.read_file` (Word, PDF, Markdown, CSV...; private paths refused). File requests always use them.
- The planner asked "did you mean" on an obvious match; now it carries on. It no longer calls Claude to
  phrase answers. JARVIS describes its agent-building ability truthfully.
- `browser.use` typing and clicking failed: Playwright MCP 0.0.85 calls the element `target`, not `ref`.
  Live: the .au WHOIS check of aureusdetailing.com.au now works (3 steps, 31 s; confirmed with whois).
- `web.search` (the planner's search) now searches the whole web through JARVIS's Chrome.
- Approve on self-reviews: retests if main moves mid-merge; plain errors; a second click is harmless.
- Boost (`jarvis/providers/boost.py`): Groq / Cerebras / OpenRouter / Together, open models, Mac model as
  fallback. Off until the owner sets JARVIS_BOOST, JARVIS_BOOST_KEY and JARVIS_ALLOW_EXTERNAL_AI=true.

## 2026-11-16 — Speed: streaming replies, a two-call path for open data, a lean router

- Measured, not guessed: the 9b writes ~11 tokens/s; routing took 5.8 s; weather took 45 s (planner).
- Replies stream: `OllamaProvider.generate(on_token=...)`, the text so far is in `/api/live` as `draft`,
  and Chat and Presence show it as it is written.
- Open-data questions (weather, currency, holidays, VIN, words, news) go one-pick -> tool -> answer
  (`_quick_tool`): weather in Perth 45 s -> 12 s.
- The router sees only the first sentence of each tool: 9b routing 5.8 s -> 2.7 s, 10/10 right on the
  benchmark. A separate router model was tested and NOT used: qwen3.5:4b routed in 2.1 s but got 8/10,
  and 16 GB cannot hold it beside the 9b, so every swap reloads a model (6-8 s). `JARVIS_ROUTER_MODEL`
  remains as an option for a bigger Mac.
- Self-review Approve: merges even with unrelated unsaved work (refuses only when the same files are
  dirty, and says which); the result now shows right under the buttons, with progress while the tests run.

## 2026-11-16 — Local-first JARVIS: its own brain, its own Chrome, open data, the gap loop

- The local model is the brain by default (`JARVIS_BRAIN=local`; `claude` restores the old way).
  Claude is called only for code, builds, deep research, a question its own search could not answer,
  and teaching. Router, `HARD_WORK` and voice no longer send plans, maths or writing to Claude.
- `jarvis/tools/browser.py`: JARVIS's own Chrome (Playwright MCP 0.0.85 over stdio, persistent profile
  `data/browser-profile`, JARVIS's server blocked). `browser.search` (free full-web search, ~5 s),
  `browser.read`, and `browser.use`, a step-by-step agent run by the local model. One approval per task;
  it stops before buy/pay/send/post/sign-up clicks and never types passwords or card numbers.
  Live check: it read three cars and prices off monsoormotors.com.au in one step, matching the site.
- Web questions are answered locally: search, read the top pages, answer with sources (`_web_answer`).
- `jarvis/tools/opendata.py`: free keyless APIs: Open-Meteo weather, Frankfurter + open.er-api currency,
  Nager.Date holidays, NHTSA VIN decoding, Free Dictionary, Google News. Each checked live.
- Photos: the local model's vision answers about attached pictures (`OllamaProvider.see`).
- Local model: 16k context (`JARVIS_CTX`) and kept loaded for 30 minutes, so replies start at once.
- Learning is local and every 10 minutes (its Chrome + local model); the briefing uses `open.news`.
- The gap loop (`jarvis/gaps.py`): what JARVIS could not do becomes a gap, and the self-review hands the
  gaps to Claude Code to build into JARVIS with tests, on a branch the owner approves. Runs every
  `JARVIS_TEACH_HOURS` (6) or right away when the owner says "learn to ...".
- `CLAUDE.md`: the standing rules (local first, the gap loop, hard lines) for every future session.

## 2026-11-16 — The OS is the default page

- `/` now opens JARVIS AI Operating System; the single-page interface moved
  to `/classic` (the OS windows embed it from there). `/static/os.html` still works.

## 2026-11-16 — JARVIS AI Operating System; stress test and lessons

- `os.html` / `os.css` / `os.js`: a desktop shell. Top bar (live state,
  battery, Wi-Fi, clock, notifications), live desktop widgets, a dock of apps
  that open as real JARVIS pages in draggable, resizable, minimisable windows
  (iframes in `?embed=1` mode; CSP now `frame-ancestors 'self'`), positions
  remembered, a Cmd-K command bar to open apps or ask JARVIS (no animation:
  it opens many times a day), toasts for approvals and reminders, a one-time
  boot. Checked in Chrome: windows, dock, command bar answer, no errors.
- Stress test on a test copy, 12 tasks: 8 passed (build an agent, live web,
  research, tasks, memory, reminder, loan maths, picture refusal, browser
  approval). Fixed the 4 gaps:
  - `mac.find_files` now searches one folder, by kind (pdf, image, ...),
    newest first, with dates and sizes ("latest PDF in Downloads").
  - Run / test / install / "run it" requests go to `claude.operate` (one
    approval) instead of the no-shell tool.
  - Multi-part routines ("every Monday X and every Friday Y") become separate
    schedules.
  - The builder tells the owner exactly what to say to run what it built.
- Proof: re-run of the 4 tasks all pass; the built price_watch agent's 5
  tests pass through Mac access (13 s, sandboxed). 336 tests pass.

## 2026-11-16 — Interface redesign: motion, HUD reticle, interactive dashboard, better chat

- Skills: installed (after vetting, text only, MIT) Emil Kowalski's animate,
  choreograph, improve-animations, animation-performance, review-animations,
  find-animation-opportunities, animation-vocabulary, emil-design-eng
  (emilkowalski/skills, 57k stars) and design-motion-principles
  (kylezantos). Used with unslop, dashboard-design, ux-designer and
  frontend-design.
- `motion.css` / `motion.js`: tokens (strong ease-out, 120-280 ms), page
  fade-and-settle, one choreographed staggered entrance per session, press
  feedback, pointer-only hover, data flash and count-up on change, toast and
  reply entrances, reduced motion respected. A HUD reticle around the face
  (hairline ticks, arcs, sweep; spins faster and sweeps while working; state,
  timer and signal readouts) and a live voice line driven by the real
  speech/microphone level that stops drawing when idle.
- Speed: gallery faces render only when scrolled into view. Measured 120 fps,
  worst frame 9 ms on the JARVIS page.
- Dashboard: stat tiles count up and open their page; the activity log has
  category filters, search and a count.
- Chat: replies render safely (paragraphs, headings, lists, bold, inline code,
  links, code blocks with Copy; no innerHTML), a copy button per reply,
  suggestions from the owner's goals in a new conversation, conversation
  search, auto-growing message box, only new messages animate. The JARVIS
  page reply uses the same rendering.
- 336 tests pass; checked in Chrome with no console errors.

## 2026-11-16 — The concept is now the JARVIS page

- Owner approved the concept. `deck.js` builds its panels (System, Activity,
  This Mac, Current task, Last result, Coming up, Needs you, the live States
  gallery and Abilities) around the existing JARVIS page centre, so voice,
  wake word, interrupt, files, the Approve card and the shared conversation
  are unchanged. `deck.css` lays it out (three columns, then states and
  abilities; folds to two and one column) and carries the quiet style to every
  page: neutral graphite panels and hairlines, off-white primary buttons,
  magenta kept for the face, live state and selection.
- Checked in Chrome: JARVIS page, Dashboard and Chat render with no console
  errors; the test tab was closed so only one hands-free listener runs.
  concept.html stays as a standalone preview.

## 2026-11-16 — Vetted GitHub skills installed and used on the concept

- Installed for Claude Code (~/.claude/skills) and JARVIS
  (workspace/.claude/skills), after reading them in a quarantine folder:
  unslop (heydamir, 16.7k stars, text only; its helper scripts, which start
  Chrome and run commands, were left out), dashboard-design (abdiraimov-otabek;
  its promotional sign-off section removed), ux-designer (szilu), and
  Anthropic's official theme-factory, mcp-builder and doc-coauthoring. A
  16-star 21 MB repo was rejected.
- Used on the concept page (unslop polish mode + dashboard-design critique):
  neutral graphite surfaces and hairlines, magenta kept for the face, the live
  state and the selection; line icons in the rail; 500-weight title; honest
  counts ("16 of 16 available, 3 ask first", activity with the day before);
  one-line Last result that skips background reads.
- New read-only `GET /api/mac/status` (not logged as an action) so the page
  does not fill the activity log; fixed a negative index in the fallback face
  drawing that threw occasionally. 336 tests pass; no console errors.

## 2026-11-16 — JARVIS set up around the owner's goal: grow all the businesses

- Owner's goal saved as personal facts (grow Monsoor Motors, Aureus Detailing
  and OwnWay; proactive, prioritised actions with numbers; Australia). Project
  profiles written for all three (OwnWay added) with their growth levers.
- Standing jobs: weekly growth review per business (Mon 8:00 / 8:15 / 8:30)
  and a Friday 4pm wrap-up across all three.
- Learning takes turns across the businesses and asks for current
  information (picks: detailing pricing benchmarks 2026, used car pricing
  strategy Nov 2026, best selling products for seniors 2026).
- Real request "What should I do this week to grow Aureus Detailing?": a full
  plan in workspace/aureus-detailing/weekly-growth-strategy.md (111 s, deep
  model), honest that real numbers are unknown, with 8 questions to tune it.

## 2026-11-16 — Owner's skills available to JARVIS; first self-review started

- The owner's 20 Claude Code skills (ceo-operator, finance-analyst,
  shopify-store-builder, meta/google ads, compliance-au, ...; written for the
  OwnWay store) are copied into `workspace/.claude/skills/` (git-ignored), so
  JARVIS's Claude Code loads them; confirmed with a real run. Refresh with
  `rsync -a ~/.claude/skills/ ~/JARVIS/workspace/.claude/skills/`.
- Status: all 16 abilities on; "not built yet" is empty. First self-review
  pass started from the API; proposals appear on the System page.

## 2026-11-16 — Merged reminders, email and calendar, morning briefing; model tiers

- Merged `claude/unruffled-heisenberg-1318a6` (reminders and recurring jobs),
  `claude/dreamy-saha-6144e9` (Apple Mail and Calendar, mail.send asks every
  time) and `claude/nervous-poincare-d3842d` (morning briefing). Conflicts were
  only registrations and the change log: both sides kept. Checked: AppleScript
  values passed as argv, scheduled jobs go through the same approvals.
- Local model: on this 16 GB M5 the current qwen3.5:9b (7.6 GB) stays; the MLX
  9B build is 8.9 GB and 27B does not fit, so nothing was downloaded.
- Model tiers: local Qwen routes and handles JARVIS's own data; Claude Haiku
  converses and researches; Sonnet does everyday work; Opus is chosen
  automatically for strategy, in-depth or very long jobs (`work_model()`,
  `JARVIS_WORK_MODEL` overrides). 330 tests pass.

## 2026-11-16 — Semantic memory search is on

- Owner approved pulling `nomic-embed-text` (274 MB, Ollama). Memories are
  embedded with nomic's task prefixes (`search_document:` / `search_query:`);
  word-search hits below 0.55 similarity are dropped as off-topic.
- Real data: "what do I know about cloud computing" -> the three cloud facts
  (0.68-0.71); "AI memory research" -> the three memory-paper facts
  (0.63-0.66); "reliable used cars to stock" -> nothing (correct, no such
  memory; before the filter it returned unrelated notes). First search indexes
  everything (~13 s), later ones are instant. Tests never use the real model.

## 2026-11-16 — Live abilities on the Safety panel; semantic memory search

- The Safety panel was stale ("External AI: blocked", wake word and browser
  listed as not built). `status()` now computes `abilities` from the live tools
  and settings: Read, Write, Web, Code, Build, Commands, Mac, Browser,
  Co-work, Autonomous, Voice, Pictures, Semantic memory, Reminders, Email and
  calendar, Morning briefing, each on / asks first / needs X / not built;
  "Not built yet" is derived from it. External AI shows Claude, what it is
  used for, and what the sandbox keeps private.
- `jarvis/semantic.py`: memories by meaning with a local Ollama embedding
  model (`JARVIS_EMBED_MODEL`, default nomic-embed-text, vectors cached in
  data/embeddings.db); used in recall and `memory.search`. Without the model
  it expands the query with related words, which proved too noisy on real
  data ("my dealership" matched AWS facts), so the owner is asked to approve
  pulling the ~270 MB model. 282 tests pass.

## 2026-11-16 — Reminders and recurring jobs

- Owner: "remind me at 5pm to call the supplier", "remind me tomorrow
  morning…", "every weekday at 8am check the used-car prices".
- `jarvis/scheduler.py`: plain-English time parsing in the owner's local zone
  (at 5pm / at 9 = the next 9 o'clock / tomorrow at 5 = 5 pm / tonight / this
  afternoon / in 20 minutes / in half an hour / on Friday / next Monday /
  20 November / noon; every day / weekday / weekend / Monday and Thursday /
  morning / daily), and a daemon thread (`app.scheduler`, started in `serve`,
  every `JARVIS_SCHEDULE_TICK`=20 s, off with `JARVIS_SCHEDULER=0`). A schedule
  is moved on before it fires, so it never fires twice; missed by >12 h (JARVIS
  was off) it is skipped and marked "Missed"; a few minutes late it says when it
  was due.
- Schema v6: `schedules` and `schedule_alerts` (`jarvis/stores/schedules.py`).
- Tools `schedule.add` / `schedule.list` / `schedule.cancel`. Chat understands
  reminders, "what reminders do I have" and "cancel the supplier reminder"
  without the model (so reminders work even with no model connected); the
  router has a `schedule` mode for phrasings the patterns miss.
- A reminder fires as: `mac.notify`, a spoken line on the JARVIS page
  (`GET /api/reminders/due`, polled every 15 s, each alert handed out once),
  and a message in the current conversation. A job runs its request through
  the normal chat handling as `jarvis:schedule` in its own "Scheduled: …"
  conversation; the result is posted in the current conversation. Anything
  needing approval waits for the owner (tested with a financial tool).
- Tasks page: Reminders panel (list, cancel, set one). API: `GET/POST
  /api/reminders`, `POST /api/reminders/<id>/cancel`.
- "Remind me to call Sam tomorrow" now sets a reminder rather than a task; two
  conversation tests were reworded to "Add a task…".
- Verified live on a throwaway server (port 8779): set by chat and API, the
  panel listed all three, and at 10:12 the reminder fired: notification run
  completed as `jarvis:schedule`, the JARVIS page spoke it, the conversation
  got "Reminder: …". 296 tests pass (14 new, fake clock).

## 2026-11-16 — Email and calendar through Mail and Calendar

- Owner uses Apple Mail and Calendar (asked first). New tools in
  `jarvis/tools/mail_calendar.py`, AppleScript through `osascript` with every
  value passed as an argument (never spliced into a script), no installs:
  - read, automatic: `mail.recent` (last N days, unread only, start of each
    message), `mail.search` (sender/subject, inbox or every mailbox except
    Trash/Junk, Gmail Inbox/All Mail twins removed), `mail.read` (one whole
    message), `calendar.today`, `calendar.upcoming`.
  - write: `mail.draft` (opens the message, or a reply to the sender with the
    original quoted, in Mail for the owner to check; never sends) and
    `calendar.add_event` (timed or all-day, named calendar or the first
    writable one; refuses unknown calendars and times in the past).
  - `mail.send` is external communication: the safety layer asks the owner on
    the System page every time, for exactly those recipients and words, once.
    A spoken or typed "yes" does not approve it (tested).
- Calendar's `whose` cannot test `recurrence` and does not expand repeats, so
  each calendar is read in one bulk request and repeating events (RRULE:
  daily/weekly/monthly/yearly, INTERVAL, BYDAY incl. 2MO/-1FR, BYMONTH,
  BYMONTHDAY, COUNT, UNTIL) are expanded in Python; cancelled occurrences are
  fetched only for repeats that land in the window. All-day events end at
  23:59:59 in Calendar and are detected from that.
- Calendar is slow (~3 s per bulk property on the owner's 114-event holiday
  calendar): first read ~17-23 s (was 110 s before bulk reads), then cached for
  two minutes covering today and the next 15 days; adding an event clears it.
- macOS asks once to allow automation of Mail and Calendar; if refused, the
  tools say where to turn it on (System Settings > Privacy & Security >
  Automation). A Mail/Calendar that was quitting (-600) is retried once.
- Routing: mail/calendar words added to `OWN_DATA` (not "events", "schedule"
  or "send", so web questions still go to Claude); the router and the
  abilities sentence now say JARVIS does email and calendar.
- Verified on the owner's Mac (counts only, no content read out): recent mail
  4 s (2 found, bodies read), search everywhere 5 s, calendar 60 days: 8
  all-day holiday events with yearly repeats expanded. All scripts compile.
  Draft, send and add-event were not run against the real apps (mocked tests
  only) so nothing was created in the owner's accounts.
- 309 tests pass (27 new in `tests/test_mail_calendar.py`).

## 2026-11-16 — Spoken morning briefing

- New `jarvis/briefing.py`: a 30-60 second spoken briefing from open tasks
  (due today, overdue, top priority), what the learner saved since yesterday
  (source `jarvis:learn`), pending approvals and self-review proposals, the Mac
  (`mac.status`), and 2-3 headlines on the owner's interests via read-only
  `claude.research` (`JARVIS_BRIEFING_TOPICS` to change them; no personal data
  is sent). The local model writes it in spoken style; markdown and URLs are
  stripped, and if the model is unavailable or rambles, plain sentences are used.
- `GET /api/briefing` keeps one briefing per day (`?refresh=1` makes a new one).
  Headlines are fetched in the background at server start (after 4 am); the
  endpoint waits at most `JARVIS_BRIEFING_NEWS_WAIT` (20 s) for them, and a
  briefing made without them is not kept, so the next request picks them up.
  `JARVIS_BRIEFING=0` turns the background fetch off.
- JARVIS page, hands-free: the first bare "Jarvis" of the day plays the
  briefing; "what's my briefing" plays it any time. "Skip", "stop" or "Jarvis"
  cuts it off (barge-in), as does a click on JARVIS.
- Dashboard: a Briefing card with the text, sources (headline / learned, with
  site links) and "Make a new one".
- Verified: 288 tests pass (scripted model, faked research and Mac tools, never
  real Claude); Dashboard card checked in the browser on a throwaway server
  (plain briefing, sources list, rebuild, no console errors). The voice flow
  was not tried with a microphone.

## 2026-11-16 — Mac access, sandboxed

- `claude.operate` is now Mac access, on by default (`JARVIS_OPERATE=0` turns
  it off): runs from the home folder with Bash, files, installs (no sudo) and
  the web; the owner approves each task once (system category), then it works
  without further prompts. Blocked: sudo, security, osascript, ssh, diskutil,
  launchctl, crontab, git push, file tools on keys/credentials/browser and mail
  data/JARVIS's .env and data.
- macOS sandbox (`sandbox-exec`, `JARVIS_SANDBOX=0` disables) around every
  Claude Code run except the browser: ~/.ssh, ~/.aws, ~/.gnupg, gh/docker
  config, .netrc/.npmrc, JARVIS .env and data are unreadable, and JARVIS's API
  port is unreachable, even from shell commands. Verified with real Claude:
  `ls ~/.ssh` -> Operation not permitted; API unreachable; web works. (The
  keychain folder cannot be blocked: Claude Code signs in through it.)
- New no-approval tools `mac.find_files` (Spotlight), `mac.status`,
  `mac.open`, `mac.notify` (argument lists, never a shell). Verified: battery
  99%, 242 GB free; found workspace/conversation_listener.py.
- Real run through Mac access: the owner's "fix it" on conversation_listener.py
  ran its self-test (passed, exit 0, 11 s).
- The conversational brain now knows JARVIS can act on the Mac and never tells
  the owner to run things by hand; JARVIS's prompt lists what it can do.
- 282 tests pass.

## 2026-11-16 — JARVIS understands: Claude as the conversational brain

- Owner: "it's not understanding me". Causes found in real transcripts: names
  misheard (Ultron as Altron/Ultraman), utterances cut at the first pause
  ("So..."), short follow-ups ("Can you?") turned into 6-minute Claude Code
  jobs, and the local 9B planner failing web questions (45-53 s, "unusable
  action twice").
- `claude.converse` (web_read, Haiku, `JARVIS_CHAT_MODEL`; off with
  `JARVIS_BRAIN=local`): conversation replies and web questions now go to
  Claude with the whole conversation, persona and memories; it searches the
  web itself. The local model still routes and handles JARVIS's own data
  (tasks, memory, projects, goals) and is the fallback.
- Speech: whisper gets a vocabulary hint (JARVIS terms, project names, names
  from memory): "Monsaw Motors" became "Monsoor Motors" in a test. End of
  speech waits 1.7 s; fillers like "So..." are held and joined to what follows.
- Spoken mode (`voice: true` from hands-free and the mic): one to three short
  sentences; long answers say the first three sentences and leave the rest on
  screen. Short messages (under five words) are never turned into jobs.
- Real spoken test: tallest mountain (11 s, correct), the correction to
  include New Guinea (11 s, Puncak Jaya), "Can you?" (7 s, on topic), EV
  advice (10 s, three short sentences and a question). 281 tests pass.

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
