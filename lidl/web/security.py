"""Bejelentkezés és CSRF-védelem a webes felülethez.

A jelszó (ha be van állítva) csak környezeti változóból jön. A sessionök a
memóriában élnek: a konténer újraindítása után újra be kell jelentkezni.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time

SESSION_COOKIE = "lidl_session"
SESSION_SECONDS = 7 * 24 * 3600


class Auth:
    def __init__(self, password: str = ""):
        self.password = password or ""
        self.csrf = secrets.token_urlsafe(24)
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.password)

    def login(self, password: str) -> str | None:
        if not self.enabled:
            return ""
        candidate = str(password or "").encode("utf-8")
        expected = self.password.encode("utf-8")
        if not hmac.compare_digest(candidate, expected):
            return None
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune()
            self._sessions[token] = time.time() + SESSION_SECONDS
        return token

    def valid(self, token: str | None) -> bool:
        if not self.enabled:
            return True
        if not token:
            return False
        with self._lock:
            self._prune()
            expiry = self._sessions.get(token)
        return bool(expiry and expiry > time.time())

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def csrf_ok(self, value: str | None) -> bool:
        candidate = str(value or "")
        if not candidate.isascii():
            return False
        return hmac.compare_digest(candidate, self.csrf)

    def _prune(self) -> None:
        now = time.time()
        for token in [key for key, expiry in self._sessions.items() if expiry <= now]:
            self._sessions.pop(token, None)
