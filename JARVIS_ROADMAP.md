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
| 3 | A real JARVIS: one conversation that thinks, remembers and acts | **In progress**: 3.1 done (174 tests passing); 3.2 next |
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

## Phase 3: A real JARVIS (next)

What makes it feel like JARVIS rather than a form-filling app: you talk to it
naturally, it knows who you are and what you said before, it does things when
you ask, it tells you plainly what it did, and it speaks up with useful
information.

| Step | What gets built | Needs install? | Done when |
|---|---|---|---|
| 3.1 | **Done.** **One conversation that thinks and acts.** Chat decides for itself whether to just answer or to carry out an action through the reasoning engine, then replies in natural language based on what actually happened. Goals page stays as the detailed view | No | "Remind me to call Sam tomorrow" in chat creates the task and says so truthfully; "What's 15% of 240?" just answers; refusals and approvals appear in the conversation |
| 3.2 | **Memory of you.** Full-text memory search; a context builder that gives the model the most relevant facts with their sources; conversation history carried forward; JARVIS proposes "Shall I remember that?" for personal facts and preferences, saved only with your yes | No | Tell it a preference once, and later answers use it, citing that it came from memory |
| 3.3 | **Personality and self-knowledge.** A consistent JARVIS voice (calm, concise, a little dry, addresses you as you prefer); accurate knowledge of its own abilities, generated from the live tool list | No | Asked "what can you do?", it answers from its real tool list; tone is consistent across chat and reports |
| 3.4 | **Everyday tools.** Date and time, calculations, unit conversion, notes, reminders with due times, reading files you place in a JARVIS inbox folder | No | Each tool tested; reading is confined to the inbox folder |
| 3.5 | **Proactive briefings.** "Good morning" summary on request and on the dashboard: due and overdue reminders, open tasks, what JARVIS did since last time, anything waiting for approval | No | Briefing reflects real data only and says "nothing due" when that is true |
| 3.6 | **Web knowledge (optional, approval each time).** A free, keyless web lookup tool classed as external communication, so every use needs your approval | No | Off unless enabled; every lookup asks first; results are labelled as from the web |

## Phase 4: Voice

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

None now. Phase 3.6 (web lookups) and Phase 4 (speech-to-text download) will
each need a yes when reached.
