"""ntfy push értesítés (opcionális).

A JSON-os publikálást használjuk, mert így a magyar ékezetes cím is
gond nélkül átmegy (a HTTP fejlécek nem lennének UTF-8-barátok).
"""

from __future__ import annotations

import requests

_PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


def send(
    settings: dict,
    title: str,
    message: str,
    tags: list[str] | None = None,
    priority: str = "default",
) -> bool:
    """Elküld egy ntfy üzenetet. Soha nem dob kivételt."""
    cfg = (settings or {}).get("ntfy") or {}
    if not cfg.get("enabled"):
        return False
    base = str(cfg.get("url") or "").strip().rstrip("/")
    topic = str(cfg.get("topic") or "").strip().strip("/")
    if not base or not topic:
        return False
    headers = {}
    token = str(cfg.get("token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "topic": topic,
        "title": title,
        "message": message,
        "tags": tags or ["shopping_cart"],
        "priority": _PRIORITIES.get(priority, 3),
    }
    try:
        response = requests.post(base, json=payload, headers=headers, timeout=15)
        return response.status_code < 400
    except requests.RequestException:
        return False
