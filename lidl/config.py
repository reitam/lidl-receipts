"""Útvonalak és felhasználói beállítások.

A fájlrendszer gyökere a projektmappa (Windows, helyi használat), de
konténerben a ``LIDL_DATA_DIR`` / ``LIDL_OUTPUT_DIR`` környezeti változókkal
a volume-ra állítható. A felhasználói beállítások a
``<DATA_DIR>/config.json`` fájlban élnek, hogy a konténer újraindítása után
is megmaradjanak.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default.resolve()
    return Path(raw).expanduser().resolve()


DATA_DIR = _env_path("LIDL_DATA_DIR", ROOT / "data")
OUTPUT_DIR = _env_path("LIDL_OUTPUT_DIR", ROOT / "nyugtak")
LOGS_DIR = DATA_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "config.json"
JOB_INDEX_FILE = DATA_DIR / "jobs.json"
SCHEDULER_STATE_FILE = DATA_DIR / "scheduler.json"

COUNTRY = (os.environ.get("LIDL_COUNTRY") or "HU").strip().upper()
LANGUAGE = (os.environ.get("LIDL_LANGUAGE") or "hu").strip().lower()
APP_VERSION_OVERRIDE = (os.environ.get("LIDL_APP_VERSION") or "").strip()
UI_PASSWORD = os.environ.get("LIDL_UI_PASSWORD") or ""
# A web UI jelszava csak környezeti változóból jön, hogy ne kerüljön
# titkos adat a config.json-ba.

DEFAULTS: dict[str, Any] = {
    "country": COUNTRY,
    "language": LANGUAGE,
    "app_version": APP_VERSION_OVERRIDE,
    "schedule": {
        "enabled": False,
        "time": "19:00",
        "weekdays": [0, 1, 2, 3, 4, 5, 6],
    },
    "ntfy": {
        "enabled": False,
        "url": "",
        "topic": "lidl",
        "token": "",
        "on_manual": False,
    },
}

WEEKDAY_NAMES = ["Hétfő", "Kedd", "Szerda", "Csütörtök", "Péntek", "Szombat", "Vasárnap"]


def _deep_merge(base: dict, extra: dict) -> dict:
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        elif value is not None:
            base[key] = value
    return base


def load_settings() -> dict:
    """Alapértelmezések + config.json + (ahol van) környezeti felülírás."""
    data = copy.deepcopy(DEFAULTS)
    if SETTINGS_FILE.is_file():
        try:
            _deep_merge(data, json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    if os.environ.get("LIDL_COUNTRY"):
        data["country"] = COUNTRY
    if os.environ.get("LIDL_LANGUAGE"):
        data["language"] = LANGUAGE
    if APP_VERSION_OVERRIDE:
        data["app_version"] = APP_VERSION_OVERRIDE
    return data


def save_settings(settings: dict) -> None:
    """Csak a felhasználó által szerkeszthető mezőket írja ki, atomikusan."""
    data = copy.deepcopy(DEFAULTS)
    _deep_merge(
        data,
        {
            key: settings[key]
            for key in ("country", "language", "app_version", "schedule", "ntfy")
            if key in settings
        },
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def ensure_dirs() -> None:
    for path in (DATA_DIR, OUTPUT_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def token_path(country: str | None = None) -> Path:
    return DATA_DIR / f"token_{(country or COUNTRY).upper()}.json"


def receipts_dir(country: str | None = None) -> Path:
    return DATA_DIR / "receipts" / (country or COUNTRY).upper()


def env_for_child(settings: dict | None = None) -> dict[str, str]:
    """A háttérfeladatok (subprocess) környezete: ugyanazok az útvonalak."""
    settings = settings or load_settings()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["LIDL_DATA_DIR"] = str(DATA_DIR)
    env["LIDL_OUTPUT_DIR"] = str(OUTPUT_DIR)
    env["LIDL_COUNTRY"] = str(settings.get("country") or COUNTRY).upper()
    env["LIDL_LANGUAGE"] = str(settings.get("language") or LANGUAGE).lower()
    version = str(settings.get("app_version") or "").strip()
    if version:
        env["LIDL_APP_VERSION"] = version
    else:
        env.pop("LIDL_APP_VERSION", None)
    return env
