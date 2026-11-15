# JARVIS roadmap

Vision: a personal AI executive operating system. The owner decides; JARVIS
understands intent, remembers, plans, delegates, checks its own work, reports
problems, asks before sensitive actions, and never claims work it has not done.

**Current priority (owner's decision, 2026-11-16): make JARVIS a genuinely
intelligent general assistant first, one that feels like a real JARVIS.
Business-specific work (Monsoor Motors, Aureus Detailing) comes later.**

## Status at a glance

| Phase | Name | Status |
|---|---|---|
| 1 | Foundation | **Complete** |
| 2 | Intelligence Core: tools, reasoning engine, local model | **Complete** (2.1 to 2.3; 155 tests passing) |
| 3 | A real JARVIS: autonomous, learning, connected | **In progress**: 3.1 to 3.5 and JARVIS Desktop done (233 tests passing); 3.6 HUD next |
| 4 | Voice | Not started |
| 5 | Autonomous workforce (specialist agents) | Not started |
| 6 | Business intelligence | Later, by owner's choice |
| 7 | Distributed JARVIS | Not started |

## Phase 1: Foundation (complete)

Local web command centre, SQLite data model, memory, experiences, tasks,
projects, safety and approvals, audit trail, backups and restore,
configuration, logging, AI provider interface, tests.

## Phase 2: Intelligence Core (complete)

| Step | What was built |
|---|---|
| 2.1 | Tool registry, execution engine, run log, 11 built-in tools |
| 2.2 | Reasoning engine: plan, act, check, report; approvals; limits; resume |
| 2.3 | Local model (Qwen 3.5 9B in Ollama); goal review; honest chat |

## Phase 3: A real JARVIS

### Done
| Step | What was built |
|---|---|
| 3.1 | One conversation that thinks and acts; truthful reports from the run log |
| 3.2 | Memory of you: ranked full-text memory in every answer, citations |

### Owner's decisions (2026-11-16)
1. **Claude Code, learn once.** When the local model cannot do a kind of task,
   JARVIS hands it to Claude Code (the owner's existing plan; no API key, no
   extra cost). The working result is saved as a JARVIS skill, so the next task
   of that kind runs locally without Claude.
2. **Autonomy: act, ask only for big risks.** JARVIS works on its own:
   researching online, reading files, writing and running code in its own
   workspace, creating skills and automations. It still asks before deleting
   the owner's files, sending email or messages, spending money, or changing
   anything outside its workspace.
3. **Memory: automatic, reviewable.** JARVIS saves useful facts and decisions
   by itself; the Memory page lets the owner see and delete anything. This
   replaces "Shall I remember that?".
4. **Self-improvement with a safety net.** Skills and instructions improve
   automatically. Core code changes are kept only if every test passes, and
   every change is committed to Git so it can be undone.

### Reference videos studied (2026-11-16)
Four public Instagram reels the owner shared (kept privately in
`data/media/reels`, transcribed locally): a voice JARVIS that phones a
restaurant, books a table and calls back; JARVIS phoning its owner about a
problem it is already fixing; "Rose", a wake-word assistant that builds visual
research boards and is controlled by voice; and "Zero", an assistant with a
glowing knowledge-graph "brain" that reports what it handled overnight.
Common to all: **voice, a living interface, proactive reports, a butler
personality.**

### Next: the autonomous JARVIS (built in this order)
| Step | What gets built | Needs install? | Done when |
|---|---|---|---|
| 3.3 | **Done.** Autonomy policy (`workspace`, `web_read` automatic; the four hard lines ask) | No | |
| 3.4 | **Done** (keyless search is limited; optional Brave key). Internet: `web.search`, `web.fetch` with sources | No | |
| 3.5 | **Done** (push-to-talk). **Voice.** Talk to JARVIS from the browser (push-to-talk) and hear it answer. Speech-to-text with whisper.cpp (installed 2026-11-16, model in `data/models`); spoken replies with the macOS voice (British, butler tone); "go to sleep" / "wake up"; transcripts saved like chat | Done | Speak a request, hear a truthful spoken answer; works offline |
| 3.5b | **Done** (owner's request). **JARVIS Desktop.** Floating orb on the desktop, starts at login, double clap then "Jarvis" to talk, answers aloud and acts | No | Real claps confirmed by the owner |
| 3.6 | **Living interface (HUD).** An arc-reactor status ring (online, listening, thinking, speaking), the active model shown, live action cards ("Searching…", "Running code…") while a run works | No | The ring and cards follow real state, never animation alone |
| 3.7 | **Code runner.** Python in the sandboxed workspace (time and output limits, no writes outside) | No | Escapes blocked in tests; real tasks run |
| 3.8 | **Skills and learn-once, Claude Code bridge.** Claude Code builds a skill the first time; the same kind of task then runs locally | No | Second time needs no Claude |
| 3.9 | **Research reports.** "Research X" produces a visual board: findings, charts drawn from collected data, images and sources; voice and click control ("enlarge the chart") | No | A real research question produces a sourced board |
| 3.10 | **Automations, briefings and proactive alerts.** Scheduled and triggered automations; a morning briefing ("while you were away…" from the real log); JARVIS raises problems itself with a macOS notification and a spoken alert | No | A timed automation runs; a briefing matches the log; an alert fires |
| 3.11 | **The brain view.** An interactive map of everything JARVIS knows (memories, projects, skills, lessons) and how they link, glowing where it is working | No | Every node is real data; click to inspect |
| 3.12 | **Automatic memory** (reviewable) | No | |
| 3.13 | **Self-improvement** behind tests and Git | No | |

### Later, needs an owner decision (paid service)
- **Phone calls on the owner's behalf** (reel 1) and **JARVIS phoning the
  owner** (reel 2) need a telephony and voice service (for example Twilio,
  Vapi or Retell), all pay-per-minute, plus a phone number. Every outgoing call
  would be an `external_communication` action needing approval. Until then,
  alerts use macOS notifications and speech.

The hard lines do not move: JARVIS never pretends something happened, and
destructive, external, financial and system actions always wait for the owner.

## Phase 4: Voice everywhere

Phase 3.5 brings push-to-talk voice in the browser. Phase 4 adds a wake word
("Hey JARVIS") and hands-free listening.

<!-- earlier text kept below -->

Talk to JARVIS and hear it answer. Speaking uses the voice built into macOS (no
install). Listening needs a local speech-to-text model (owner approval for a
download). A push-to-talk button first; a wake word much later.

## Phase 5: Autonomous workforce

Specialist agents (research, operations, finance, marketing, development) as
profiles on the same engine, with delegation and result checking.

## Phase 6: Business intelligence (later)

JARVIS learns Monsoor Motors and Aureus Detailing from information the owner
provides or connects, monitors them and flags opportunities. No business data
is invented.

## Phase 7: Distributed JARVIS

The MacBook stays the command centre; other machines (for example the Windows
laptop) claim jobs as workers.

## Standing resource rules

No paid APIs or subscriptions. No unnecessary installs or background services.
No large downloads without the owner's approval. Nothing outside `~/JARVIS`.
Existing code and tests are preserved.

## Owner decisions pending

None now. Phase 4 (speech-to-text download) will need a yes when reached.
