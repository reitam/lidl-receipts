"""Böngésző nélküli bejelentkezés a webes felülethez.

A konténerben nincs böngésző, ezért a PKCE folyamatot kettébontjuk:
az authorize URL-t a szerver generálja, a felhasználó a saját böngészőjében
nyitja meg, majd a ``com.lidlplus.app://callback?...`` URL-t (vagy csak a
kódot) beilleszti a felületre. A kódot a szerver váltja tokenre.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from ..auth import (
    AuthError,
    TokenData,
    TokenStore,
    build_login_url,
    exchange_code,
    extract_code,
    extract_state,
    new_pkce_pair,
)

FLOW_TTL = 900  # 15 perc


@dataclass
class LoginFlow:
    state: str
    verifier: str
    country: str
    language: str
    url: str
    created_at: float

    @property
    def expires_in(self) -> int:
        return max(0, int(self.created_at + FLOW_TTL - time.time()))


class LoginFlowStore:
    def __init__(self, store: TokenStore):
        self.store = store
        self._flow: LoginFlow | None = None
        self._lock = threading.Lock()

    def start(self, country: str, language: str) -> LoginFlow:
        verifier, challenge = new_pkce_pair()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        url = build_login_url(country, language, challenge, state=state, nonce=nonce)
        flow = LoginFlow(
            state=state,
            verifier=verifier,
            country=country.upper(),
            language=language.lower(),
            url=url,
            created_at=time.time(),
        )
        with self._lock:
            self._flow = flow
        return flow

    def current(self) -> LoginFlow | None:
        with self._lock:
            flow = self._flow
            if flow is None:
                return None
            if flow.created_at + FLOW_TTL <= time.time():
                self._flow = None
                return None
            return flow

    def cancel(self) -> None:
        with self._lock:
            self._flow = None

    def finish(self, pasted: str) -> TokenData:
        flow = self.current()
        if flow is None:
            raise AuthError(
                "Nincs aktív bejelentkezés (lejárt vagy még el sem indult). "
                "Indíts újat a Bejelentkezés oldalon."
            )
        callback_state = extract_state(pasted)
        if callback_state is not None and callback_state != flow.state:
            raise AuthError(
                "A visszairányítási state nem egyezik. Valószínűleg egy korábbi "
                "bejelentkezés URL-jét illesztetted be – indíts újat."
            )
        code = extract_code(pasted)
        token = exchange_code(code, flow.verifier, flow.country, flow.language)
        self.store.save(token)
        self.cancel()
        return token
