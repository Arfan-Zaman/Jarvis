"""Conversations and their messages."""

from __future__ import annotations

import json

from ..common import ValidationError, optional_id, text, utcnow
from .base import Store

ROLES = ("user", "assistant", "system")


class ConversationStore(Store):
    table = "conversations"
    label = "conversation"
    fields = {
        "title": text("title", required=True, max_len=200),
        "project_id": optional_id("project_id"),
    }
    defaults = {"title": "New conversation", "category": "chat"}
    search_columns = ("title",)
    filterable = Store.filterable + ("project_id",)
    order_by = "updated_at DESC, id DESC"

    def add_message(self, conversation_id: int, role: str, content: str,
                    provider: str | None = None, model: str | None = None, run_id: int | None = None,
                    memory_refs: list | None = None, memory_offer: dict | None = None) -> dict:
        if role not in ROLES:
            raise ValidationError(f"role must be one of: {', '.join(ROLES)}")
        content = text("message", required=True)(content)
        self.get(conversation_id)
        now = utcnow()
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, provider, model, run_id, memory_refs, "
                "memory_offer, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (conversation_id, role, content, provider, model, run_id,
                 json.dumps(memory_refs) if memory_refs else None,
                 json.dumps(memory_offer) if memory_offer else None, now),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._message(row)

    @staticmethod
    def _message(row) -> dict:
        message = dict(row)
        for name in ("memory_refs", "memory_offer"):
            message[name] = json.loads(message[name]) if message.get(name) else None
        return message

    def messages(self, conversation_id: int, limit: int = 500) -> list[dict]:
        """Messages in chronological order (the most recent `limit`)."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM (SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?) "
                "ORDER BY id ASC",
                (conversation_id, limit),
            ).fetchall()
        return [self._message(row) for row in rows]

    def get_with_messages(self, conversation_id: int) -> dict:
        conversation = self.get(conversation_id)
        conversation["messages"] = self.messages(conversation_id)
        return conversation
