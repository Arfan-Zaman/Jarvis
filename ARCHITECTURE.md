# JARVIS architecture

How JARVIS is built today and how the Phase 2 Intelligence Core fits onto it.
See `JARVIS_ROADMAP.md` for sequence and `NEXT_SESSION.md` for the next task.

## 1. Principles (these do not change)

1. **Local first.** Data stays on this Mac unless the owner approves otherwise.
2. **Never pretend.** No reply without a model. No "done" without evidence.
3. **Nothing high-impact runs silently.** Destructive, external, financial and
   system actions wait for the owner's approval.
4. **Everything is logged and recoverable.** Audit trail plus backups.
5. **One brain, many interfaces.** Web, command line, voice and agents all go
   through the same orchestrator.
6. **Add only what is needed.** Standard library first; each new dependency or
   download needs a stated reason.
7. **Claude Code builds JARVIS; it is not JARVIS's brain.**

## 2. What exists today (Phase 1 and Phase 2.1, complete and tested)

```
Web interface / command line
            │
            ▼
   Orchestrator (jarvis/orchestrator.py)   ← single entry point
      │        │          │         │
   Safety   Stores     Providers   Backup
   layer    (SQLite)   (AI iface)  /recovery
      │        │
   Audit trail (system_events)
```

| Part | File | State |
|---|---|---|
| Orchestrator | `jarvis/orchestrator.py` | Working |
| Data layer and migrations | `jarvis/db.py`, `jarvis/stores/` | Working, schema v1 |
| Safety, approvals, audit | `jarvis/safety.py`, `stores/events.py` | Working |
| AI provider interface | `jarvis/providers/` | Interface working; no model connected |
| Backup and recovery | `jarvis/backup.py` | Working |
| Config and logging | `jarvis/config.py`, `logging_setup.py` | Working |
| Web interface and API | `jarvis/web/` | Working |
| Tool registry and execution engine | `jarvis/tools/registry.py` | Working (Phase 2.1) |
| Built-in tools (11) | `jarvis/tools/builtin.py` | Working (Phase 2.1) |
| Run log | `jarvis/stores/runs.py` | Working, schema v2 |
| Tests | `tests/` | 114 passing |

Tables: memories, experiences, tasks, projects, agents, conversations,
messages, system_events, settings, approvals, runs, run_steps.

## 3. Decisions to settle before adding intelligence

| # | Decision | Chosen direction | Needs the owner? |
|---|---|---|---|
| D1 | Where the brain runs | A small local model through Ollama. The adapter already exists. | **Yes**: it means installing Ollama and one model download of roughly 2 to 5 GB. This is the only install Phase 2 needs. |
| D2 | Which model | One small general model that fits in 16 GB memory. Chosen by a short trial, not by guesswork. | Approve the pick |
| D3 | Cloud fallback | Built as a slot, switched off. Only free tiers, only with `JARVIS_ALLOW_EXTERNAL_AI=true`, and each use is an "external communication" needing approval. | Later |
| D4 | How the brain acts | Only through registered tools. The model proposes; the engine checks and executes. The model never touches the database or files directly. | No |
| D5 | How "done" is decided | A step counts as done only when its tool returned a result that is stored. A task counts as done only after a check step passes. | No |
| D6 | Memory retrieval | SQLite full-text search (already available, no install). Meaning-based search is deferred until keyword search proves insufficient. | No |
| D7 | Background work | None. Work runs when asked, inside the running server. No schedulers or daemons in Phase 2. | No |
| D8 | Multi-agent readiness | An "agent" is a named profile (instructions plus allowed tools) on the same engine. No second engine. | No |

## 4. Phase 2 design: the Intelligence Core

```
        Web UI      CLI      (voice, later)
           └─────────┼──────────┘
                     ▼
               Orchestrator
                     │
                     ▼
        ┌──── Reasoning engine ────┐
        │  understand → plan →     │
        │  act → check → report    │
        └──┬───────┬────────┬──────┘
           │       │        │
     Context     Model     Tool
     builder     router    registry
        │          │          │
   memories,    local →    each tool declares
   lessons,     cloud      its safety category
   project,     (off)         │
   history                 Safety layer → approvals
        │                     │
        └──── Run log (runs, run_steps) ────┘
                 resume after failure
```

### 4.1 New modules (all inside `jarvis/`)

| Module | Job |
|---|---|
| `engine/engine.py` | The loop: build context, ask the model for the next step, validate it, run the tool, record the result, repeat until finished or a limit is hit |
| `engine/context.py` | Chooses what the model sees: relevant memories, lessons, project facts and recent conversation, within a size budget. Every item keeps its source and confidence |
| `engine/planner.py` | Turns a goal into a short list of steps stored as tasks, so plans are visible and editable |
| `tools/registry.py` | **Built.** The catalogue of capabilities and the single execution path. Each tool has a name, description, input rules, a safety category and a function |
| `tools/builtin.py` | **Built.** First tools, wrapping what already works: search and save memory, create and complete tasks, record experience, list projects |
| `providers/router.py` | Picks the provider: local by default, cloud only if allowed and approved. Reports clearly when none is available |

### 4.2 New tables

| Table | Purpose |
|---|---|
| `runs` | **Built (schema v2).** One row per piece of work: kind (`tool` or `goal`), goal, agent, status (`running`, `waiting_approval`, `completed`, `failed`, `cancelled`), result, timestamps |
| `run_steps` | **Built (schema v2).** Each step in a run: what the model proposed, the tool called, inputs, output or error, status. This is the transparent activity log and the resume point |
| `memories_fts` | Not built (step 2.4). Full-text index over memories and experiences |

The existing `tasks`, `agents`, `approvals` and `system_events` tables are
reused unchanged.

### 4.2a How a tool executes (built)

`ToolRegistry.execute(name, inputs, actor, approval_id, run_id, allowed)`:

1. Unknown tool: refused.
2. Caller's allow-list (`allowed`), if given: refused when the tool is not on it.
   This is how a future agent is limited to its own tools.
3. Inputs are checked against the tool's schema.
4. The safety layer decides by the tool's category.
5. The handler runs; any error is caught.
6. A `run_steps` row is written whatever the outcome.
7. A structured result is returned: `ok`, `status` (`succeeded`, `failed`,
   `refused`, `approval_required`), `output`, `error`, `approval`, `run_id`,
   `step_id`, `duration_ms`.

The reasoning engine (step 2.2) will call exactly this, passing its own
`run_id` so all steps of one goal sit in one run.

### 4.3 How one request flows

1. The owner states a goal ("add a task to chase the parts order").
2. The engine opens a **run** and builds context.
3. The model replies with one structured step: a tool name and inputs, or a
   final answer. Anything that is not valid structure is rejected and retried
   once, then the run fails honestly.
4. The registry looks the tool up. Unknown tool: refused.
5. The safety layer classifies it. Read or write: runs. High-impact: the run
   pauses as `waiting_approval` and appears on the System page.
6. The result is stored as a **run step** and fed back to the model.
7. The loop ends on a final answer, a step limit, a time limit or an error.
8. The report to the owner lists what was actually done, taken from the stored
   steps, never from the model's own claim.

### 4.4 Honesty and recovery rules

- The final report is assembled from `run_steps`, so a model cannot claim an
  action that has no recorded result.
- A failed step is recorded with its error; the run stops or retries within a
  fixed limit. Nothing is silently skipped.
- After a crash or restart, runs still marked `running` are shown as
  interrupted and can be resumed from the last completed step or cancelled.
- Hard limits per run: maximum steps, maximum time, maximum tool failures.

### 4.5 Local first, cloud second

| Tier | When | Rule |
|---|---|---|
| None | Today | JARVIS says no model is connected |
| Local (Ollama) | Default after D1 | No approval needed; nothing leaves the Mac |
| Cloud | Only if local cannot do it and the owner allows | Off by default, free tiers only, approval per use, business data excluded unless explicitly permitted |

Claude Code remains the development tool used to extend JARVIS. It is not
called by JARVIS at runtime.

## 5. Prepared for later, not built now

| Future | What Phase 2 leaves ready |
|---|---|
| Specialist agents | `agents` rows become profiles: instructions plus a tool allow-list. `runs.agent_id` records who did what. Delegation is one more tool ("hand this to agent X") |
| Voice | A voice layer is just another interface calling the orchestrator: speech in becomes text, the answer is spoken. macOS has built-in speech output |
| Business intelligence | Project-scoped memory and tools; business data connectors arrive as tools with their own safety category |
| Distributed workers | A run is a self-contained job record, so a second machine can later claim jobs over the local API. No change to the engine |
| Scheduled work | A scheduler would only create runs; deferred to respect "no background services" |

## 6. Dependencies

Phase 2 adds **no Python packages**. The only new software is Ollama plus one
model (decision D1). Step 2.1 is built without it and step 2.2 does not need it.
