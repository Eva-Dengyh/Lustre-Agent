"""SQLite-backed session store — persists conversation history.

Schema:
    sessions(id, title, created_at, updated_at, metadata)
    messages(id, session_id, role, content, tool_call_id,
             tool_name, created_at)

Supports FTS5 full-text search on message content.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["SessionStore"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A single message in a conversation."""

    id: str
    role: str          # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    created_at: str = field(default_factory="")

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Message":
        return cls(
            id=d["id"],
            role=d["role"],
            content=d["content"],
            tool_call_id=d.get("tool_call_id"),
            tool_name=d.get("tool_name"),
            created_at=d.get("created_at", ""),
        )


@dataclass
class Session:
    """A conversation session with its messages."""

    id: str
    title: str
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now()
        if not self.updated_at:
            self.updated_at = self.created_at

    @property
    def is_empty(self) -> bool:
        return len(self.messages) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------

class SessionStore:
    """SQLite-backed session storage with thread-safe access.

    All public methods are thread-safe (SQLite connections are local to
    each call; writes are serialised via a reentrant lock).
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".lustre" / "sessions.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if hasattr(self, "_conn") and self._conn:
                self._conn.close()
                self._conn = None

    # -------------------------------------------------------------------------
    # Init
    # -------------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self, "_conn") or self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent read performance
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL DEFAULT '新会话',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    metadata    TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id           TEXT PRIMARY KEY,
                    session_id   TEXT NOT NULL,
                    role         TEXT NOT NULL,
                    content      TEXT NOT NULL,
                    tool_call_id TEXT,
                    tool_name    TEXT,
                    created_at   TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, created_at);

                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                    USING fts5(content, content=messages,
                               content_rowid=rowid,
                               tokenize='unicode61');
            """)
            conn.commit()

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------

    def create_session(
        self,
        title: str = "新会话",
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session and return it."""
        sid = _new_id()
        now = _now()
        meta = json.dumps(metadata or {}, ensure_ascii=False)

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO sessions(id, title, created_at, updated_at, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, title, now, now, meta),
            )
            conn.commit()

        return Session(id=sid, title=title, metadata=metadata or {}, created_at=now, updated_at=now)

    def get_session(self, session_id: str) -> Session | None:
        """Load a session with all its messages."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None

            meta = json.loads(row["metadata"] or "{}")
            messages = [
                Message.from_dict(dict(m))
                for m in conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at",
                    (session_id,),
                ).fetchall()
            ]

            return Session(
                id=row["id"],
                title=row["title"],
                messages=messages,
                metadata=meta,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Session]:
        """List recent sessions (newest first)."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [
                Session(
                    id=r["id"],
                    title=r["title"],
                    metadata=json.loads(r["metadata"] or "{}"),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update session title or metadata. Returns True if found."""
        with self._lock:
            conn = self._get_conn()
            now = _now()
            if title is not None:
                conn.execute(
                    "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (title, now, session_id),
                )
            if metadata is not None:
                conn.execute(
                    "UPDATE sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(metadata, ensure_ascii=False), now, session_id),
                )
            conn.commit()
            return conn.total_changes > 0

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages. Returns True if found."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return conn.total_changes > 0

    # -------------------------------------------------------------------------
    # Messages
    # -------------------------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
    ) -> Message:
        """Append a message to a session. Updates session.updated_at."""
        msg_id = _new_id()
        now = _now()

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO messages"
                "(id, session_id, role, content, tool_call_id, tool_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, session_id, role, content, tool_call_id, tool_name, now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            conn.commit()

        return Message(
            id=msg_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            created_at=now,
        )

    def search_messages(self, query: str, limit: int = 20) -> list[Message]:
        """Full-text search across all message content."""
        with self._lock:
            conn = self._get_conn()
            # FTS5 search
            rows = conn.execute(
                """
                SELECT m.* FROM messages m
                JOIN messages_fts fts ON m.rowid = fts.rowid
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
            return [Message.from_dict(dict(r)) for r in rows]

    def get_recent_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[Message]:
        """Get the most recent N messages for a session."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [Message.from_dict(dict(r)) for r in reversed(rows)]

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    def count_messages(self, session_id: str) -> int:
        """Return total message count for a session."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row[0] if row else 0

    def touch(self, session_id: str) -> None:
        """Update the session's updated_at timestamp (keep-alive)."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (_now(), session_id),
            )
            conn.commit()
