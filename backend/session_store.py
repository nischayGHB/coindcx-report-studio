"""Thread-safe in-memory credential/session storage."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .coindcx_client import CoinDCXClient
from .config import SESSION_TTL_SECONDS


@dataclass(slots=True)
class SessionRecord:
    client: CoinDCXClient
    created_at: datetime
    last_used: datetime


class SessionStore:
    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = threading.RLock()

    def create(self, client: CoinDCXClient) -> str:
        self.cleanup_expired()
        now = datetime.now(timezone.utc)
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[session_id] = SessionRecord(client=client, created_at=now, last_used=now)
        return session_id

    def get_client(self, session_id: str) -> CoinDCXClient:
        if not session_id:
            raise KeyError("Invalid or expired session")
        now = datetime.now(timezone.utc)
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                raise KeyError("Invalid or expired session")
            if now - record.last_used > self._ttl:
                self._sessions.pop(session_id, None)
                record.client.close()
                raise KeyError("Invalid or expired session")
            record.last_used = now
            return record.client

    def remove(self, session_id: str) -> bool:
        with self._lock:
            record = self._sessions.pop(session_id, None)
        if record:
            record.client.close()
            return True
        return False

    def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired: list[SessionRecord] = []
        with self._lock:
            for session_id, record in list(self._sessions.items()):
                if now - record.last_used > self._ttl:
                    expired.append(self._sessions.pop(session_id))
        for record in expired:
            record.client.close()
        return len(expired)


SESSIONS = SessionStore()

