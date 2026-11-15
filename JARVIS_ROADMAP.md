# JARVIS roadmap

Vision: a personal AI executive operating system. The owner decides; JARVIS
understands intent, remembers, plans, delegates, checks its own work, reports
problems, asks before sensitive actions, and never claims work it has not done.

Business environments: Monsoor Motors, Aureus Detailing.

## Status at a glance

| Phase | Name | Status |
|---|---|---|
| 1 | Foundation | **Complete** |
| 2 | Intelligence Core | **In progress**: steps 2.1 and 2.2 complete (149 tests passing); 2.3 is next |
| 3 | Autonomous workforce | Not started |
| 4 | Personal interface (voice) | Not started |
| 5 | Business intelligence | Not started |
| 6 | Distributed JARVIS | Not started |

## Phase 1: Foundation (complete)

Local web command centre, SQLite data model, memory, experiences, tasks,
projects, safety and approvals, audit trail, backups and restore,
configuration, logging, AI provider interface, tests.

What it cannot do yet: think. No model is connected.

## Phase 2: Intelligence Core (next)

Goal: JARVIS can take a plain-language goal, use its own memory, carry out
steps with its tools, ask for approval when needed, and report truthfully.

| Step | What gets built | Needs install? | Done when |
|---|---|---|---|
| 2.1 | **Done.** Tool registry, run log (`runs`, `run_steps`), built-in tools | No | Tools run through the safety layer; every call is logged; tests pass |
| 2.2 | **Done.** Reasoning engine loop, tested with a scripted stand-in model | No | A scripted run completes, pauses for approval, fails honestly, and resumes; tests pass |
| 2.3 | Connect one local model (Ollama) | **Yes, owner decision D1** | Chat answers for real; adapter verified against real Ollama |
| 2.4 | Contextual memory: full-text search and context builder | No | Answers draw on stored memories and lessons, with sources shown |
| 2.5 | Planning: goals become visible task lists that the engine works through | No | A multi-step goal is planned, executed, checked and reported |
| 2.6 | Interface: Runs page showing live steps, approvals and results | No | The owner can watch, approve, cancel and resume a run |
| 2.7 | Cloud fallback slot (off by default) | No | Refused unless enabled and approved; tested |

Steps 2.1 and 2.2 are deliberately first: they need no downloads and make
everything after them safe to add.

## Phase 3: Autonomous workforce

Specialist agents (research, operations, finance, marketing, development) as
profiles on the same engine, with delegation and result checking. Depends on
Phase 2.

## Phase 4: Personal interface

Voice in and out, natural commands, richer dashboard. Depends on Phase 2.3.

## Phase 5: Business intelligence

JARVIS learns each business from information the owner provides or connects,
monitors it and flags opportunities. Depends on Phases 2 and 3. No business
data is invented.

## Phase 6: Distributed JARVIS

The MacBook stays the command centre; other machines (for example the Windows
laptop) claim jobs as workers. Depends on Phase 3.

## Standing resource rules

No paid APIs or subscriptions. No unnecessary installs or background services.
No large downloads without the owner's approval. Nothing outside `~/JARVIS`.
Existing code and tests are preserved.

## Owner decisions pending

1. **D1:** approve installing Ollama and one small model (roughly 2 to 5 GB)
   when step 2.3 is reached. Not needed before then.
