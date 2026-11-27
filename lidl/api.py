"""Lidl Plus nyugta API kliens (nem hivatalos, a mobilapp végpontjait utánozza)."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Callable, Iterable

import requests

from .auth import AuthError, TokenData, TokenStore, refresh_access_token

TICKETS_BASE = "https://tickets.lidlplus.com/api"
DEFAULT_APP_VERSION = "16.45.5"

Progress = Callable[[str], None]


class ApiError(RuntimeError):
    """Nyugta API hiba."""


class LidlClient:
    def __init__(
        self,
        store: TokenStore,
        app_version: str | None = None,
        timeout: float = 60,
        session: requests.Session | None = None,
    ):
        token = store.load()
        if token is None:
            raise AuthError("Nincs mentett bejelentkezés. Futtasd: python -m lidl login")
        self.store = store
        self.token: TokenData = token
        self.app_version = (
            app_version or os.environ.get("LIDL_APP_VERSION") or DEFAULT_APP_VERSION
        )
        self.timeout = timeout
        self.session = session or requests.Session()

    # ------------------------------------------------------------------ token

    def _ensure_access_token(self) -> str:
        if not self.token.access_valid:
            self.token = refresh_access_token(self.token)
            # A rotált refresh tokent azonnal mentjük, mielőtt bármi más történik.
            self.store.save(self.token)
        return self.token.access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_access_token()}",
            "App-Version": self.app_version,
            "Operating-System": "iOs",
            "App": "com.lidl.eci.lidl.plus",
            "Accept-Language": self.token.language,
        }

    # --------------------------------------------------------------- requests

    def _request(self, url: str, params: dict | None = None) -> dict:
        refreshed = False
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                response = self.session.get(
                    url, headers=self._headers(), params=params, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
                self._sleep(attempt, f"hálózati hiba: {type(exc).__name__}")
                continue

            if response.status_code == 401 and not refreshed:
                self.token = refresh_access_token(self.token)
                self.store.save(self.token)
                refreshed = True
                continue

            if response.status_code in (429, 500, 502, 503, 504):
                last_error = ApiError(f"HTTP {response.status_code}")
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else None
                self._sleep(attempt, f"HTTP {response.status_code}", wait)
                continue

            if response.status_code == 426:
                raise ApiError(
                    "A Lidl szerver elutasította az App-Version fejlécet. "
                    "Próbáld frissíteni: set LIDL_APP_VERSION=17.0.0"
                )

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise ApiError(
                    f"Nyugta API hiba (HTTP {response.status_code}): {response.text[:300]}"
                ) from exc

            try:
                return response.json()
            except ValueError as exc:
                raise ApiError("A Lidl szerver nem JSON-t adott vissza.") from exc

        raise ApiError(f"Sikertelen kérés többszöri próbálkozás után: {last_error}")

    @staticmethod
    def _sleep(attempt: int, reason: str, override: float | None = None) -> None:
        delay = override if override is not None else min(2 ** (attempt - 1), 30)
        print(f"  {reason}; újrapróbálkozás {delay:.0f} mp múlva...")
        time.sleep(delay)

    # ---------------------------------------------------------------- receipts

    def list_tickets(self) -> list[dict]:
        """Az összes nyugta összefoglalója, legújabbtól a legrégebbi felé."""
        url = f"{TICKETS_BASE}/v2/{self.token.country}/tickets"
        first = self._request(url, params={"pageNumber": 1, "onlyFavorite": "false"})
        tickets: list[dict] = list(first.get("tickets") or [])
        size = int(first.get("size") or len(tickets) or 25)
        total = int(first.get("totalCount") or len(tickets))
        pages = max(1, math.ceil(total / size))

        for page in range(2, pages + 1):
            data = self._request(url, params={"pageNumber": page, "onlyFavorite": "false"})
            batch = data.get("tickets") or []
            if not batch:
                break
            tickets.extend(batch)

        # Biztonsági deduplikáció.
        seen: set[str] = set()
        unique: list[dict] = []
        for ticket in tickets:
            ticket_id = str(ticket.get("id") or "")
            if ticket_id and ticket_id not in seen:
                seen.add(ticket_id)
                unique.append(ticket)
        return unique

    def ticket(self, ticket_id: str) -> dict:
        url = f"{TICKETS_BASE}/v3/{self.token.country}/tickets/{ticket_id}"
        return self._request(url)


def safe_id(ticket_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(ticket_id))


def fetch_all(
    client: LidlClient,
    receipts_dir: Path,
    force: bool = False,
    limit: int | None = None,
    delay: float = 0.25,
    progress: Progress | None = None,
) -> dict:
    """Letölti az összes nyugta részletes JSON-ját egyenként, inkrementálisan."""
    say = progress or (lambda message: print(message))
    receipts_dir.mkdir(parents=True, exist_ok=True)

    tickets = client.list_tickets()
    api_total = len(tickets)
    if limit:
        tickets = tickets[:limit]
    say(f"Összesen {api_total} nyugta az API szerint; most {len(tickets)} kerül feldolgozásra.")

    downloaded = 0
    skipped = 0
    errors: list[tuple[str, str]] = []

    for index, summary in enumerate(tickets, 1):
        ticket_id = str(summary.get("id") or "")
        if not ticket_id:
            continue
        path = receipts_dir / f"{safe_id(ticket_id)}.json"
        if path.exists() and not force:
            skipped += 1
            continue
        try:
            detail = client.ticket(ticket_id)
            if not detail.get("id"):
                detail["id"] = ticket_id
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(detail, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
            downloaded += 1
        except Exception as exc:  # egy hibás nyugta ne állítsa meg az egészet
            errors.append((ticket_id, str(exc)))
        if index % 10 == 0 or index == len(tickets):
            say(f"  {index}/{len(tickets)} (letöltve: {downloaded}, kihagyva: {skipped})")
        if delay:
            time.sleep(delay)

    return {
        "total": len(tickets),
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
    }


def iter_receipt_files(receipts_dir: Path) -> Iterable[Path]:
    return sorted(Path(receipts_dir).glob("*.json"))
