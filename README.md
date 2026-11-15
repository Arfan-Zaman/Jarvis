# JARVIS

A local, modular personal assistant core. Milestone 1 is a small, stable
foundation: persistent data, a safety layer, backups, and a local web
interface. Phase 2.1 added controlled tools and a run log; Phase 2.2 adds a
reasoning engine that plans and carries out goals using those tools. Phase 2.3
connects a local AI model (Qwen 3.5 9B through Ollama), so JARVIS can now chat
and carry out goals for real, entirely on this Mac. Phase 3.1 makes chat one
conversation that both talks and acts.

- Runs entirely on this Mac. Nothing is sent anywhere.
- Python standard library only. The one outside program is Ollama, which runs
  the AI model.
- All data lives in `data/` inside this folder.

## What currently works

Everything in this list is covered by the automated tests, and the interface
pages were also exercised by hand in a browser.

| Area | What it does |
|---|---|
| Core orchestrator | One entry point (`jarvis.orchestrator.Jarvis`) that every interface goes through |
| Memory | Create, search, edit, archive, restore and permanently delete memories |
| Experiences | Record what happened, the outcome and the lesson; look lessons up by keyword |
| Tasks | Create, prioritise, complete, reopen; completing with a lesson stores an experience |
| Projects | Create, rename, archive; tasks, memories and experiences attach to a project |
| Conversation | One chat that talks and acts. JARVIS decides whether to answer or to carry out a request through the reasoning engine, asks when something is unclear and takes your next message as the answer, and reports actions in fixed wording taken from the record. Each action shows as a card with its status |
| Safety | Read-only mode, approval for destructive / external / financial / system actions, file-path limits |
| Audit trail | Every change, approval, denial and refusal is recorded in `system_events` |
| Configuration | `.env` file with validation, plus runtime settings in the database |
| Logging | Rotating log file at `data/logs/jarvis.log` |
| Backup / recovery | Consistent online backups, verification, pruning, approved restore |
| Tools | 11 built-in tools with input rules and permission levels; discoverable and executable through one engine |
| Reasoning engine | Takes a goal, plans steps, runs each through the tool engine, checks results, stops for approval or missing information, and reports only what the log proves. Needs an AI model to plan, so it is tested with a scripted stand-in |
| Goals page | Submit a goal, see its plan, each step's status and the verified result; answer questions, continue or cancel |
| Run log | Every tool execution is recorded with time, inputs, result or error, and can be retrieved |
| Web interface | Dashboard, Chat, Memory, Tasks, Projects, Experiences, System status |

Every stored knowledge item carries: creation time, update time, source,
confidence, verification status, category, and an active/archived state.

The database starts with exactly two project records, **Monsoor Motors** and
**Aureus Detailing**, each described only as "Business workspace.". Nothing
else is pre-filled.

## Start JARVIS

Requires Python 3.11 or newer (developed on 3.14).

```bash
cd ~/JARVIS
python3 -m jarvis
```

Then open <http://127.0.0.1:8765>. The first start creates `data/jarvis.db`.

## Stop JARVIS

Press `Ctrl+C` in the terminal where it is running, or from another terminal:

```bash
python3 -m jarvis stop
```

## Other commands

```bash
python3 -m jarvis status          # system status as JSON
python3 -m jarvis init            # create or upgrade the database without starting the server
python3 -m jarvis backup          # back up now
python3 -m jarvis backups         # list backups
python3 -m jarvis restore <name>  # restore a backup (asks for confirmation)
python3 -m jarvis tools           # list the tools JARVIS can execute
python3 -m jarvis goal "Add a task to call the supplier"   # plan and run a goal (needs a model)
python3 -m jarvis tool tasks.create '{"title": "Example"}'   # execute one tool
```

## Talking to JARVIS

Just chat. For each message JARVIS decides:

- **Answer:** conversation, questions, maths, advice. Nothing changes.
- **Act:** you want something done with its tools ("remind me to call Sam
  tomorrow", "what tasks do I have?", "remember that I prefer short
  answers"). The request goes through the reasoning engine below.

What JARVIS says it *did* comes from the run log in fixed wording ("Done. I
added the task …"), so the model cannot add claims. Answers to look-ups are
phrased by the model from the data the tools returned. If JARVIS needs a
detail it asks, and your next message is taken as the answer ("never mind"
cancels). Sensitive steps wait for approval on the System page; saying "yes"
in chat never approves anything. JARVIS knows today's date and its own real
abilities, which come from the live tool list.

Real conversation, Qwen 3.5 9B: a greeting, "15% of 240" (36), "remind me to
call Sam tomorrow" (task created with the correct date), an ambiguous request
that asked which business, a task list, saving a preference, and declining to
send email. Replies take 2 to 30 seconds; the first after a restart is slowest.

## Goals and the reasoning engine

You give JARVIS a goal in plain language. It works in four stages:

1. **Plan.** The model proposes a short list of steps, each using one
   registered tool. The plan is checked (real tools only, within the step
   limit) and stored before anything runs.
2. **Act.** For each step the model supplies the tool's inputs, and the engine
   runs it through the same permission-checked tool engine as everything else.
3. **Check.** A failed step gets one corrected attempt. A refused step stops
   the goal. A sensitive step pauses for your approval. If the model needs
   information, the goal stops with its question.
4. **Review.** The model checks the recorded results against the goal. If
   something is missing it may add steps once; otherwise the goal fails.
5. **Report.** Built from the run log, not from what the model says. A goal
   is "verified" only if every planned step has a recorded success and the
   review confirms the goal was achieved. The report lists the changes made.

Relevant memories and lessons are shown to the model as context. Each
finished or failed goal is saved once as an experience. Limits on plan
length, tool failures and model calls (see `.env.example`) prevent runaway
loops. A goal interrupted by a crash or shutdown can be continued without
repeating finished steps.

The model is shown your project names, so it can use them directly, and is
told to ask rather than guess when a request is ambiguous.

**Tested with the real model:** adding a task, a multi-step goal (task plus
memory for a named business), an ambiguous goal that asked "which project?"
and then finished after the answer, and a read-only question. A typical goal
takes 5 to 20 seconds. The first request after starting Ollama takes about 15
seconds longer while the model loads.

## Tools

A tool is a named capability with a description, input rules and a permission
level. Tools are the only way JARVIS acts, and every execution is checked by
the safety layer and written to the run log.

| Tool | Permission | What it does |
|---|---|---|
| `jarvis.info` | read | What JARVIS is, what it holds, which tools it has |
| `system.health` | read | Database integrity, backups, safety mode, AI connection |
| `projects.list`, `projects.get` | read | Read project information |
| `tasks.list` | read | List or search tasks |
| `memory.search` | read | Retrieve stored memories |
| `tasks.create`, `tasks.update`, `tasks.complete` | write | Change tasks |
| `memory.save` | write | Save a memory, recording who saved it; an identical memory is not stored twice |
| `experience.record` | write | Record an outcome and lesson |

- **Read** tools run automatically. **Write** tools run unless read-only mode
  is on, and are audited. Tools in a sensitive category (destructive, external,
  financial, system) stop and wait for the owner's approval; none of the
  built-in tools are in those categories yet.
- Unknown tools, tools outside a caller's allow-list, and invalid inputs are
  refused or failed without side effects. A tool that crashes is contained.
- There is no shell or run-any-code tool, by design.
- The System page lists the tools and recent executions. Executions are also
  available at `/api/executions` and `/api/runs`.
- To add a tool, write a handler and register a `Tool` in
  `jarvis/tools/builtin.py`.

## Project structure

```
JARVIS/
├── README.md
├── DEVLOG.md              development log
├── .env.example           configuration template
├── pyproject.toml         project metadata (no dependencies)
├── jarvis/
│   ├── __main__.py        command line: serve, stop, status, backup, restore
│   ├── orchestrator.py    core orchestrator: wires everything together
│   ├── config.py          configuration manager (.env + defaults + validation)
│   ├── logging_setup.py   logging system
│   ├── db.py              SQLite connections and schema migrations
│   ├── safety.py          safety/permission layer and approvals
│   ├── backup.py          backup and recovery
│   ├── common.py          shared errors and validators
│   ├── stores/
│   │   ├── base.py        generic record store (metadata, archive, search)
│   │   ├── records.py     memory, experience, task, project, agent stores
│   │   ├── conversations.py
│   │   ├── events.py      append-only audit trail
│   │   ├── runs.py        run log (runs and their steps)
│   │   └── settings.py    runtime settings
│   ├── engine/
│   │   └── engine.py      reasoning engine: plan, act, check, report
│   ├── tools/
│   │   ├── registry.py    tool registry and execution engine
│   │   └── builtin.py     the built-in tools
│   ├── providers/
│   │   ├── base.py        AI provider interface
│   │   ├── registry.py    provider selection
│   │   ├── ollama.py      adapter for a local Ollama server
│   │   └── scripted.py    scripted stand-in model, for tests only
│   └── web/
│       ├── server.py      local JSON API and static file server
│       └── static/        index.html, app.css, app.js
├── tests/                 automated tests (unittest)
└── data/                  created at runtime, git-ignored
    ├── jarvis.db
    ├── logs/
    └── backups/
```

### Database tables

`memories`, `experiences`, `tasks`, `projects`, `agents`, `conversations`,
`messages`, `system_events`, `settings`, `approvals`, `runs`, `run_steps`,
`run_plan`.

To change the schema, append a migration to `MIGRATIONS` in `jarvis/db.py`.
Existing databases upgrade automatically on the next start, after a
`pre-upgrade` backup is taken.

## Configuration

Copy `.env.example` to `.env` and edit. Every setting has a safe default, so
`.env` is optional. Real environment variables override `.env`.

| Setting | Default | Meaning |
|---|---|---|
| `JARVIS_HOST` | `127.0.0.1` | Loopback addresses only; anything else is rejected |
| `JARVIS_PORT` | `8765` | Port for the web interface |
| `JARVIS_DATA_DIR` | `data` | Where the database, logs and backups live |
| `JARVIS_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `JARVIS_AI_PROVIDER` | `none` | `none`, `ollama`, or `mlx` (not implemented) |
| `JARVIS_AI_MODEL` | empty | Model name for the chosen provider |
| `JARVIS_OLLAMA_URL` | `http://127.0.0.1:11434` | Address of a local Ollama server |
| `JARVIS_ALLOW_EXTERNAL_AI` | `false` | Must be `true` before any non-local provider can be used |
| `JARVIS_ALLOW_WRITES` | `true` | `false` puts JARVIS in read-only mode |
| `JARVIS_APPROVAL_TTL_MINUTES` | `15` | How long a pending approval stays valid |
| `JARVIS_BACKUP_ON_START` | `true` | Back up each time the server starts |
| `JARVIS_BACKUP_KEEP` | `14` | Number of backups to keep |
| `JARVIS_ENGINE_MAX_STEPS` | `12` | Most steps one goal's plan may have |
| `JARVIS_ENGINE_MAX_FAILURES` | `3` | Tool failures tolerated in one goal |
| `JARVIS_ENGINE_MAX_MODEL_CALLS` | `40` | Most model calls for one goal |

## Safety model

Every action is classified, and the safety layer decides before anything runs:

| Category | Rule |
|---|---|
| read | Allowed |
| write | Allowed unless read-only mode is on; audited |
| destructive | Needs explicit human approval |
| external communication | Needs explicit human approval |
| financial | Needs explicit human approval |
| system | Needs explicit human approval |

An approval is tied to one exact action, expires after 15 minutes, and works
once. Only the human user can approve; an agent cannot approve its own request.
Unknown categories are refused. File writes are confined to `data/`.

In practice today: permanently deleting a record and restoring a backup need
approval. Archiving is the reversible alternative to deleting. External
communication and financial actions do not exist yet; the gate for them does.

## AI providers

JARVIS uses **Qwen 3.5 9B** running in **Ollama** on this Mac. Nothing is sent
over the internet, and there is no cost. Ollama is a desktop app that starts at
login; it must be running for chat and goals to work. If it is not running,
JARVIS says so instead of answering.

Settings live in `.env` (private, not in Git):

```
JARVIS_AI_PROVIDER=ollama
JARVIS_AI_MODEL=qwen3.5:9b
```

For goals, JARVIS asks Ollama for strict JSON and turns off the model's hidden
"thinking" output, which keeps replies fast. To switch models, `ollama pull`
another one and change `JARVIS_AI_MODEL`. To disconnect, set
`JARVIS_AI_PROVIDER=none`.

`jarvis/providers/base.py` defines the interface. To add a provider, subclass
`AIProvider` and register it in `jarvis/providers/registry.py`.

- **Ollama**: connected and verified against the real server (chat, JSON
  replies, goals, and the "model not installed" message).
- **Apple MLX**: placeholder only. Selecting it reports that it is not implemented.
- **External providers**: none exist. They are blocked unless
  `JARVIS_ALLOW_EXTERNAL_AI=true`.

## Testing

```bash
cd ~/JARVIS
python3 -m unittest discover -s tests
```

174 tests cover database initialisation, memory create/retrieve/delete, task
creation and completion, project creation, experience storage, configuration
loading, safety checks, AI provider reporting, backup and restore, the web
API, the tool registry, tool execution, permissions, the run log, and the
reasoning engine (planning, failures, invalid plans, missing information,
approvals, limits, false completion claims, goal review, interruption
recovery), and the conversation (routing, truthful reporting, follow-up
questions, approvals in chat). The automated tests use a scripted stand-in, so they never need
Ollama. Each test uses its own temporary database and never touches `data/`.

## Backup and recovery

- A backup is taken every time the server starts, and on demand from the System
  page or `python3 -m jarvis backup`.
- Backups are complete copies of the database in `data/backups/`. Each one is
  verified after it is written. The newest 14 are kept.
- To recover:

  ```bash
  python3 -m jarvis stop
  python3 -m jarvis backups
  python3 -m jarvis restore <name>
  ```

  A restore first saves the current state as a `pre-restore` backup, so it can
  be undone by restoring that one.
- `data/` is not in Git. To protect against losing the Mac, copy
  `data/backups/` somewhere else yourself; JARVIS does not do off-machine
  backups.

## Current limitations

- The model is small and local: it handles simple goals well but can still
  make poor plans on complex ones. The review step and the run log catch
  failures, but they are not perfect.
- Memory is used only when JARVIS decides to look something up; it does not
  yet bring relevant memories into every reply (Phase 3.2).
- Routing can occasionally misjudge whether you wanted an action. When unsure
  it answers rather than acts.
- Context recall is keyword matching on the goal's words, not meaning-based.
- Goals run while you wait; there is no background execution.
- Tools can be executed from the command line and the API. The web interface
  shows tools and their history but has no form to run one.
- MLX is not implemented.
- Memory and experience search is plain keyword matching, not semantic.
- No login. The server accepts connections from this Mac only and rejects
  requests from other websites, but anyone using this Mac account can open it.
- Restoring a backup is command-line only.
- The audit trail lives in the same database, so a restore replaces it with the
  backup's version.
- Runtime settings have a store and tests but no page in the interface.
- The agents table holds only the core orchestrator; there are no other agents.
- Not built: voice, autonomous agents, browser automation, external
  integrations, scheduled work.

## Next recommended milestone

**Phase 3.2: memory of you.** JARVIS brings the most relevant things it knows
about you into every reply, cites them, and offers "Shall I remember that?"
for personal facts and preferences, saving only with your yes. No installs.
See `NEXT_SESSION.md`.
