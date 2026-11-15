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
| 3 | A real JARVIS: autonomous, learning, connected | **In progress**: 3.1 to 3.4 done (212 tests passing); 3.5 next |
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

### Next: the autonomous JARVIS (built in this order)
| Step | What gets built | Needs install? | Done when |
|---|---|---|---|
| 3.3 | **Done.** **Autonomy policy.** New permission levels: `workspace` (write and run inside `~/JARVIS/workspace`) and `web_read` run without asking; `external_communication`, `financial`, `destructive` and `system` (anything outside the workspace) still ask. One policy file the owner can read | No | Tests prove each level; the System page shows the policy |
| 3.4 | **Done** (keyless search is limited; optional Brave key). **Internet.** `web.search` (free, no key) and `web.fetch` (page to clean text), automatic; results labelled with their source URL | No | Real searches answer real questions with sources |
| 3.5 | **Code runner.** JARVIS writes and runs Python in its workspace: time limit, output limit, and macOS sandboxing so it cannot write outside the workspace. No unrestricted shell | No | Escapes are blocked in tests; real tasks run |
| 3.6 | **Skills and learn-once.** A skill is a folder in `~/JARVIS/skills/` (manifest plus code), loaded as a tool, tested before it is enabled, committed to Git. Before calling Claude Code, JARVIS looks for a skill that fits | No | A new kind of task builds a skill via Claude Code; the same kind of task later runs locally without Claude |
| 3.7 | **Claude Code bridge.** A tool that runs `claude -p` in the background on a task, restricted to the workspace or a skill folder, with a time limit; every use is logged with its cost in turns | No | Claude builds and tests a working skill unattended |
| 3.8 | **Automations.** "Every morning at 8, …" or "when a file lands in my inbox, …" become saved automations run by a scheduler inside the JARVIS server, each run logged; pause, edit and delete from the interface | No | A timed and a file-triggered automation run correctly |
| 3.9 | **Automatic memory.** After each exchange JARVIS extracts lasting facts and decisions and saves them (source and confidence recorded); duplicates merged; Memory page review and delete | No | Facts appear without asking; nothing invented; deletes stick |
| 3.10 | **Self-improvement.** A review loop turns failures and lessons into better skills and instructions automatically; core changes go through Claude Code, must pass the full test suite, are committed, and are reverted automatically if anything later fails | No | A failure leads to a tested fix without the owner's help, with a Git record |

The hard lines do not move: JARVIS never pretends something happened, and
destructive, external, financial and system actions always wait for the owner.

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

None now. Phase 4 (speech-to-text download) will need a yes when reached.
