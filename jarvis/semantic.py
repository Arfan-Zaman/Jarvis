"""Semantic memory search: find memories by meaning, not just matching words.

With a local embedding model in Ollama (`JARVIS_EMBED_MODEL`, default
`nomic-embed-text`), every active memory gets a vector (cached in
`data/embeddings.db`, recomputed when the memory changes) and a question is
matched by cosine similarity, so "my dealership" finds "I run a used car
business". Everything stays on this Mac.

Without that model, `expand()` asks the local chat model for related words and
the normal word search runs on them: weaker, but still finds paraphrases.
"""

from __future__ import annotations

import array
import json
import math
import os
import sqlite3
import time
import urllib.request

from .logging_setup import get_logger
from .providers.base import ChatMessage, ProviderError

log = get_logger("semantic")
MIN_SCORE = 0.55


def _model() -> str:
    return os.environ.get("JARVIS_EMBED_MODEL", "nomic-embed-text")


class Semantic:
    def __init__(self, app):
        self.app = app
        self.path = app.config.data_dir / "embeddings.db"
        self._checked, self._ok = 0.0, False

    # --- the embedding model ------------------------------------------------
    def _url(self, path: str) -> str:
        return getattr(self.app.config, "ollama_url", "http://127.0.0.1:11434").rstrip("/") + path

    def available(self) -> bool:
        """Is the embedding model installed in Ollama? Checked at most once a minute."""
        if time.monotonic() - self._checked < 60:
            return self._ok
        self._checked = time.monotonic()
        try:
            with urllib.request.urlopen(self._url("/api/tags"), timeout=3) as response:
                names = {m.get("name", "").split(":")[0] for m in json.load(response).get("models", [])}
            self._ok = _model().split(":")[0] in names
        except (OSError, ValueError):
            self._ok = False
        return self._ok

    def embed(self, texts: list[str]) -> list[list[float]]:
        body = json.dumps({"model": _model(), "input": [t[:2000] for t in texts]}).encode()
        request = urllib.request.Request(self._url("/api/embed"), body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response).get("embeddings") or []

    # --- the vector cache ---------------------------------------------------
    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("CREATE TABLE IF NOT EXISTS vectors (memory_id INTEGER PRIMARY KEY, stamp TEXT, "
                     "model TEXT, vec BLOB)")
        return conn

    def _vectors(self) -> dict[int, tuple[dict, list[float]]]:
        """Vectors for all active memories, embedding any new or changed ones first."""
        memories = self.app.memory.list(limit=5000)
        with self._db() as conn:
            stored = {row[0]: (row[1], row[2], row[3]) for row in conn.execute("SELECT * FROM vectors")}
            stale = [m for m in memories if stored.get(m["id"], (None, None))[:2] != (m["updated_at"], _model())]
            for start in range(0, len(stale), 32):
                batch = stale[start:start + 32]
                for memory, vec in zip(batch, self.embed([m["content"] for m in batch])):
                    blob = array.array("f", vec).tobytes()
                    conn.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)",
                                 (memory["id"], memory["updated_at"], _model(), blob))
                    stored[memory["id"]] = (memory["updated_at"], _model(), blob)
        out = {}
        for memory in memories:
            blob = stored.get(memory["id"], (None, None, None))[2]
            if blob:
                vec = array.array("f"); vec.frombytes(blob)
                out[memory["id"]] = (memory, vec.tolist())
        return out

    # --- search -------------------------------------------------------------
    def search(self, text: str, limit: int = 6) -> list[dict]:
        """Memories closest in meaning to `text`, best first ([] if the model is missing)."""
        if not text.strip() or not self.available():
            return []
        try:
            query = self.embed([text])[0]
            scored = [(_cosine(query, vec), memory) for memory, vec in self._vectors().values()]
        except (OSError, ValueError, IndexError) as exc:
            log.info("Semantic search unavailable: %s", exc)
            return []
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{**memory, "similarity": round(score, 3)} for score, memory in scored[:limit] if score >= MIN_SCORE]

    def expand(self, text: str) -> str:
        """Related words for a word search, from the local model (fallback without embeddings)."""
        try:
            reply = self.app.provider.generate([
                ChatMessage("system", "List 8 short words or phrases with the same meaning as, or closely related "
                                      "to, the owner's search. Reply with them separated by commas, nothing else."),
                ChatMessage("user", text[:300])]).text
        except ProviderError:
            return text
        return f"{text} {reply.replace(',', ' ')}"[:600]

    def status(self) -> dict:
        return {"model": _model(), "embeddings": self.available(),
                "mode": "meaning (embeddings)" if self.available() else "related words (no embedding model)"}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
