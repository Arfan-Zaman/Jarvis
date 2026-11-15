"""SQLite persistence: connections and schema migrations.

Every operation opens its own short-lived connection, which keeps the layer
safe to use from the web server's worker threads.

To change the schema, append a new entry to MIGRATIONS. Never edit an entry
that has already been released: existing databases will not re-run it.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Columns shared by every stored knowledge item.
_META = """
    source              TEXT    NOT NULL DEFAULT 'user',
    confidence          REAL    NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    verification_status TEXT    NOT NULL DEFAULT 'unverified'
                        CHECK (verification_status IN ('unverified','user_provided','verified','disputed')),
    category            TEXT    NOT NULL DEFAULT 'general',
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    archived_at         TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
"""

MIGRATIONS: list[str] = [
    # --- version 1: initial data model -------------------------------------
    f"""
    CREATE TABLE projects (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,
        slug        TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed')),
        {_META}
    );

    CREATE TABLE tasks (
        id           INTEGER PRIMARY KEY,
        title        TEXT NOT NULL,
        description  TEXT NOT NULL DEFAULT '',
        status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','in_progress','completed','cancelled')),
        priority     TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
        project_id   INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        due_at       TEXT,
        completed_at TEXT,
        {_META}
    );

    CREATE TABLE memories (
        id         INTEGER PRIMARY KEY,
        content    TEXT NOT NULL,
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        {_META}
    );

    CREATE TABLE experiences (
        id          INTEGER PRIMARY KEY,
        title       TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        outcome     TEXT NOT NULL DEFAULT 'unknown' CHECK (outcome IN ('success','failure','mixed','unknown')),
        lesson      TEXT NOT NULL DEFAULT '',
        project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
        {_META}
    );

    CREATE TABLE agents (
        id           INTEGER PRIMARY KEY,
        name         TEXT NOT NULL UNIQUE,
        kind         TEXT NOT NULL DEFAULT 'core',
        description  TEXT NOT NULL DEFAULT '',
        status       TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('idle','active','disabled')),
        capabilities TEXT NOT NULL DEFAULT '',
        {_META}
    );

    CREATE TABLE conversations (
        id         INTEGER PRIMARY KEY,
        title      TEXT NOT NULL DEFAULT 'New conversation',
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        {_META}
    );

    CREATE TABLE messages (
        id              INTEGER PRIMARY KEY,
        conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role            TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
        content         TEXT NOT NULL,
        provider        TEXT,
        model           TEXT,
        created_at      TEXT NOT NULL
    );

    CREATE TABLE system_events (
        id         INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        level      TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('debug','info','warning','error')),
        category   TEXT NOT NULL,
        action     TEXT NOT NULL,
        message    TEXT NOT NULL,
        actor      TEXT NOT NULL DEFAULT 'system',
        details    TEXT
    );

    CREATE TABLE settings (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        category   TEXT NOT NULL DEFAULT 'general',
        source     TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE approvals (
        id           INTEGER PRIMARY KEY,
        action       TEXT NOT NULL,
        category     TEXT NOT NULL,
        summary      TEXT NOT NULL,
        details      TEXT,
        fingerprint  TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','denied','used')),
        requested_by TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        expires_at   TEXT NOT NULL,
        decided_by   TEXT,
        decided_at   TEXT,
        used_at      TEXT
    );

    CREATE INDEX idx_tasks_status       ON tasks(status, is_active);
    CREATE INDEX idx_tasks_project      ON tasks(project_id);
    CREATE INDEX idx_memories_category  ON memories(category, is_active);
    CREATE INDEX idx_memories_project   ON memories(project_id);
    CREATE INDEX idx_experiences_project ON experiences(project_id);
    CREATE INDEX idx_messages_conv      ON messages(conversation_id, id);
    CREATE INDEX idx_events_category    ON system_events(category, id);
    CREATE INDEX idx_approvals_status   ON approvals(status);
    """,
    # --- version 2: run log for tool execution -------------------------------
    """
    CREATE TABLE runs (
        id          INTEGER PRIMARY KEY,
        kind        TEXT NOT NULL DEFAULT 'tool' CHECK (kind IN ('tool','goal')),
        goal        TEXT NOT NULL,
        actor       TEXT NOT NULL DEFAULT 'user',
        agent_id    INTEGER REFERENCES agents(id) ON DELETE SET NULL,
        status      TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','waiting_approval','completed','failed','cancelled','interrupted')),
        result      TEXT,
        error       TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        finished_at TEXT
    );

    CREATE TABLE run_steps (
        id          INTEGER PRIMARY KEY,
        run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        position    INTEGER NOT NULL,
        tool        TEXT NOT NULL,
        category    TEXT,
        actor       TEXT NOT NULL,
        input       TEXT,
        output      TEXT,
        error       TEXT,
        status      TEXT NOT NULL CHECK (status IN ('succeeded','failed','refused','waiting_approval')),
        approval_id INTEGER,
        started_at  TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        duration_ms INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX idx_runs_status     ON runs(status, id);
    CREATE INDEX idx_run_steps_run   ON run_steps(run_id, position);
    CREATE INDEX idx_run_steps_tool  ON run_steps(tool, id);
    """,
    # --- version 3: goal runs: plans, context, and a 'blocked' state ---------
    # SQLite cannot change a CHECK constraint in place, so `runs` is rebuilt.
    """
    CREATE TABLE runs_new (
        id          INTEGER PRIMARY KEY,
        kind        TEXT NOT NULL DEFAULT 'tool' CHECK (kind IN ('tool','goal')),
        goal        TEXT NOT NULL,
        actor       TEXT NOT NULL DEFAULT 'user',
        agent_id    INTEGER REFERENCES agents(id) ON DELETE SET NULL,
        status      TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','waiting_approval','blocked','completed','failed',
                                      'cancelled','interrupted')),
        result      TEXT,
        error       TEXT,
        context     TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        finished_at TEXT
    );
    INSERT INTO runs_new (id, kind, goal, actor, agent_id, status, result, error, created_at, updated_at, finished_at)
        SELECT id, kind, goal, actor, agent_id, status, result, error, created_at, updated_at, finished_at FROM runs;
    DROP TABLE runs;
    ALTER TABLE runs_new RENAME TO runs;
    CREATE INDEX idx_runs_status ON runs(status, id);

    ALTER TABLE run_steps ADD COLUMN plan_id INTEGER;

    CREATE TABLE run_plan (
        id          INTEGER PRIMARY KEY,
        run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        position    INTEGER NOT NULL,
        description TEXT NOT NULL,
        tool        TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed','blocked')),
        inputs      TEXT,
        attempts    INTEGER NOT NULL DEFAULT 0,
        approval_id INTEGER,
        note        TEXT,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX idx_run_plan_run ON run_plan(run_id, position);
    """,
    # --- version 4: chat messages can point at the action (run) they triggered -
    """
    ALTER TABLE messages ADD COLUMN run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL;
    CREATE INDEX idx_messages_run ON messages(run_id);
    """,
    # --- version 5: full-text knowledge index and memory-aware chat messages ---
    """
    CREATE VIRTUAL TABLE knowledge_fts USING fts5(
        kind UNINDEXED, ref_id UNINDEXED, body, tokenize = 'porter unicode61'
    );
    INSERT INTO knowledge_fts (kind, ref_id, body)
        SELECT 'memory', id, content || ' ' || category FROM memories;
    INSERT INTO knowledge_fts (kind, ref_id, body)
        SELECT 'experience', id, title || ' ' || description || ' ' || lesson || ' ' || category FROM experiences;

    CREATE TRIGGER memories_fts_insert AFTER INSERT ON memories BEGIN
        INSERT INTO knowledge_fts (kind, ref_id, body) VALUES ('memory', new.id, new.content || ' ' || new.category);
    END;
    CREATE TRIGGER memories_fts_update AFTER UPDATE OF content, category ON memories BEGIN
        DELETE FROM knowledge_fts WHERE kind = 'memory' AND ref_id = old.id;
        INSERT INTO knowledge_fts (kind, ref_id, body) VALUES ('memory', new.id, new.content || ' ' || new.category);
    END;
    CREATE TRIGGER memories_fts_delete AFTER DELETE ON memories BEGIN
        DELETE FROM knowledge_fts WHERE kind = 'memory' AND ref_id = old.id;
    END;
    CREATE TRIGGER experiences_fts_insert AFTER INSERT ON experiences BEGIN
        INSERT INTO knowledge_fts (kind, ref_id, body) VALUES ('experience', new.id, new.title || ' ' || new.description || ' ' || new.lesson || ' ' || new.category);
    END;
    CREATE TRIGGER experiences_fts_update AFTER UPDATE OF title, description, lesson, category ON experiences BEGIN
        DELETE FROM knowledge_fts WHERE kind = 'experience' AND ref_id = old.id;
        INSERT INTO knowledge_fts (kind, ref_id, body) VALUES ('experience', new.id, new.title || ' ' || new.description || ' ' || new.lesson || ' ' || new.category);
    END;
    CREATE TRIGGER experiences_fts_delete AFTER DELETE ON experiences BEGIN
        DELETE FROM knowledge_fts WHERE kind = 'experience' AND ref_id = old.id;
    END;

    ALTER TABLE messages ADD COLUMN memory_refs TEXT;
    ALTER TABLE messages ADD COLUMN memory_offer TEXT;
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)

# Tables every JARVIS database has had since version 1. Used to recognise a
# backup, so it must not grow: older backups have to stay restorable.
REQUIRED_TABLES = (
    "memories", "experiences", "tasks", "projects", "agents",
    "conversations", "messages", "system_events", "settings", "approvals",
)


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        """Yield a connection; commit on success, roll back on error."""
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> int:
        """Create or upgrade the schema. Returns the resulting version."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer than this JARVIS "
                    f"build supports ({SCHEMA_VERSION}). Update JARVIS or restore a backup."
                )
            for number in range(version + 1, SCHEMA_VERSION + 1):
                # One transaction per migration: it applies fully or not at all.
                script = MIGRATIONS[number - 1]
                conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
            return conn.execute("PRAGMA user_version").fetchone()[0]
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def version(self) -> int:
        with self.connect() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    def tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def integrity_ok(self) -> bool:
        with self.connect() as conn:
            return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    def size_bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0
