"""Context builder: what JARVIS knows that matters right now.

Finds the most relevant active memories and lessons for a piece of text using
the SQLite full-text index (`knowledge_fts`, schema v5), ranked by relevance
and adjusted so verified, owner-provided and high-confidence facts win over
guesses. Personal facts and preferences are always included, because they
apply to every conversation ("I prefer short answers") whatever the topic.

Every item keeps its id, source and verification status, so a reply can say
where a fact came from.
"""

from __future__ import annotations

import re

PERSONAL = ("preference", "personal", "profile")
_STOP = frozenset("""a an and are as at be been but by can could did do does for from had has have how i if in
into is it its just me my of on or our please so than that the their them then there these they this to
was we were what when where which who why will with would you your about tell know want need like
jarvis""".split())

# Higher weight = more trusted. bm25 scores are negative (more negative = better),
# so multiplying by a larger weight ranks an item higher.
_TRUST = ("CASE m.verification_status WHEN 'verified' THEN 1.5 WHEN 'user_provided' THEN 1.3 "
          "WHEN 'disputed' THEN 0.4 ELSE 1.0 END * (0.5 + m.confidence / 2)")
_MEMORY_FIELDS = ("id", "content", "category", "source", "confidence", "verification_status", "project_id")


def fts_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 query: meaningful words joined by OR."""
    words = [w for w in dict.fromkeys(re.findall(r"[a-z0-9]{3,}", (text or "").lower())) if w not in _STOP]
    return " OR ".join(f'"{w}"' for w in words[:12]) or None


class ContextBuilder:
    def __init__(self, app):
        self.app = app

    def search_memories(self, text: str, limit: int = 10, *, category: str | None = None,
                        project_id: int | None = None, include_global: bool = True) -> list[dict]:
        """Active memories matching `text`, best first. Empty if nothing matches."""
        query = fts_query(text)
        if not query:
            return []
        clauses, params = ["knowledge_fts MATCH ?", "m.is_active = 1"], [query]
        if category:
            clauses.append("m.category = ?")
            params.append(category)
        if project_id is not None:
            clauses.append("(m.project_id = ?" + (" OR m.project_id IS NULL)" if include_global else ")"))
            params.append(project_id)
        with self.app.db.connect() as conn:
            rows = conn.execute(
                "SELECT m.* FROM knowledge_fts JOIN memories m "
                "ON knowledge_fts.kind = 'memory' AND m.id = knowledge_fts.ref_id "
                f"WHERE {' AND '.join(clauses)} ORDER BY bm25(knowledge_fts) * {_TRUST} LIMIT ?",
                [*params, max(1, int(limit))]).fetchall()
        return [self.app.memory._row(row) for row in rows]

    def search_lessons(self, text: str, limit: int = 3) -> list[dict]:
        query = fts_query(text)
        if not query:
            return []
        with self.app.db.connect() as conn:
            rows = conn.execute(
                "SELECT e.* FROM knowledge_fts JOIN experiences e "
                "ON knowledge_fts.kind = 'experience' AND e.id = knowledge_fts.ref_id "
                "WHERE knowledge_fts MATCH ? AND e.is_active = 1 AND e.lesson != '' "
                "ORDER BY bm25(knowledge_fts) LIMIT ?", (query, max(1, int(limit)))).fetchall()
        return [self.app.experiences._row(row) for row in rows]

    def personal(self, limit: int = 5) -> list[dict]:
        """Facts about the owner that apply everywhere, most trusted and recent first."""
        marks = ", ".join("?" for _ in PERSONAL)
        with self.app.db.connect() as conn:
            rows = conn.execute(
                f"SELECT m.* FROM memories m WHERE m.is_active = 1 AND m.category IN ({marks}) "
                f"ORDER BY {_TRUST} DESC, m.updated_at DESC LIMIT ?", (*PERSONAL, limit)).fetchall()
        return [self.app.memory._row(row) for row in rows]

    def build(self, text: str, project_id: int | None = None, *, memories: int = 6, lessons: int = 3,
              budget_chars: int = 2000) -> dict:
        """Relevant memories and lessons for `text`, within a size budget."""
        chosen, seen, used = [], set(), 0
        for item in self.personal() + self.search_memories(text, limit=memories, project_id=project_id):
            if item["id"] in seen or len(chosen) >= memories + len(PERSONAL):
                continue
            if used + len(item["content"]) > budget_chars:
                break
            seen.add(item["id"])
            used += len(item["content"])
            chosen.append({key: item[key] for key in _MEMORY_FIELDS})
        found = [{key: item[key] for key in ("id", "title", "outcome", "lesson")}
                 for item in self.search_lessons(text, limit=lessons)]
        return {"memories": chosen, "lessons": found}
