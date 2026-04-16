"""SessionManager — manages the active session lifecycle in the CLI.

Coordinates:
- Which session is currently active
- Persisting messages from Supervisor/Agent runs
- Loading session history for context injection
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from lustre.session.store import Session, SessionStore

if TYPE_CHECKING:
    from lustre.bus.message import Message as BusMessage

logger = logging.getLogger(__name__)

__all__ = ["SessionManager"]


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------

class SessionManager:
    """Manages the active session and its conversation history.

    Provides:
    - Active session tracking (in-memory)
    - Persistence via SessionStore
    - Automatic message logging from bus events
    - Session switching / creation / deletion

    Usage:
        sm = SessionManager()
        sm.set_active_session(sm.create("调研项目"))
        sm.log_message("user", "帮我调研 FastAPI")
        sm.log_message("assistant", "好的，我开始调研...")
        # Later: inject history into CodeAgent context
        history = sm.get_history()
    """

    def __init__(
        self,
        store: SessionStore | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self._store = store or SessionStore(db_path=db_path)
        self._active_session: Session | None = None

    # -------------------------------------------------------------------------
    # Active session
    # -------------------------------------------------------------------------

    @property
    def active_session(self) -> Session | None:
        """Return the currently active session (may be None)."""
        return self._active_session

    def set_active_session(self, session: Session | None) -> None:
        """Set or clear the active session."""
        self._active_session = session

    # -------------------------------------------------------------------------
    # Session CRUD (delegate to store)
    # -------------------------------------------------------------------------

    def create_session(
        self,
        title: str = "新会话",
        metadata: dict | None = None,
    ) -> Session:
        """Create a new session and make it active."""
        session = self._store.create_session(title=title, metadata=metadata)
        self._active_session = session
        logger.debug("Session created: %s", session.id)
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Load a session from the store."""
        return self._store.get_session(session_id)

    def list_sessions(self, limit: int = 20, offset: int = 0) -> list[Session]:
        """List recent sessions."""
        return self._store.list_sessions(limit=limit, offset=offset)

    def switch_session(self, session_id: str) -> Session | None:
        """Switch to a different session (load from store)."""
        session = self._store.get_session(session_id)
        if session:
            self._active_session = session
            logger.debug("Switched to session: %s", session_id)
        return session

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. If it was active, clears active session."""
        was_active = self._active_session and self._active_session.id == session_id
        result = self._store.delete_session(session_id)
        if was_active:
            self._active_session = None
        return result

    def rename_session(self, session_id: str, title: str) -> bool:
        """Rename a session."""
        return self._store.update_session(session_id, title=title)

    # -------------------------------------------------------------------------
    # Message logging
    # -------------------------------------------------------------------------

    def log_message(
        self,
        role: str,
        content: str,
        *,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
    ) -> None:
        """Log a message to the active session (if any)."""
        if self._active_session is None:
            return
        self._store.add_message(
            session_id=self._active_session.id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )

    def log_bus_message(self, bus_message: "BusMessage") -> None:
        """Convert a bus Message and log it to the active session.

        Maps bus message roles to session roles:
            supervisor → assistant
            agent:<name> → assistant
            user → user
        """
        if self._active_session is None:
            return

        role_map = {
            "user": "user",
            "supervisor": "assistant",
            "agent:code": "assistant",
            "agent:research": "assistant",
            "agent:test": "assistant",
            "system": "system",
        }
        role = role_map.get(bus_message.source, "assistant")

        self.log_message(
            role=role,
            content=bus_message.content or "",
            tool_call_id=getattr(bus_message, "tool_call_id", None),
            tool_name=getattr(bus_message, "tool_name", None),
        )

    # -------------------------------------------------------------------------
    # History for context injection
    # -------------------------------------------------------------------------

    def get_history(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return message history suitable for injecting into an LLM context.

        Returns list of {"role": ..., "content": ...} dicts.
        """
        if session_id:
            session = self._store.get_session(session_id)
        else:
            session = self._active_session

        if not session:
            return []

        # Get recent messages (oldest first)
        messages = self._store.get_recent_messages(
            session.id if session else "",
            limit=limit,
        )
        return [{"role": m.role, "content": m.content} for m in messages]

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across all sessions."""
        messages = self._store.search_messages(query, limit=limit)
        return [m.to_dict() for m in messages]

    # -------------------------------------------------------------------------
    # Active session helpers
    # -------------------------------------------------------------------------

    def ensure_active(self) -> Session:
        """Return active session, creating one if needed."""
        if self._active_session is None:
            self._active_session = self._store.create_session(title="新会话")
        return self._active_session

    @property
    def active_session_id(self) -> str | None:
        """Return the ID of the active session (or None)."""
        return self._active_session.id if self._active_session else None

    def touch(self) -> None:
        """Keep the active session alive (update timestamp)."""
        if self._active_session:
            self._store.touch(self._active_session.id)
