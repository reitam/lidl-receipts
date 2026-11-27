"""Napi ütemezett frissítés (beépített, kis scheduler).

Nem kell cron a konténerben: a webes folyamat egy szálon figyeli az időt,
és a beállításokban megadott napokon/órában elindítja a teljes frissítést.
A beállításokat minden körben újraolvassa, így a UI-ból azonnal él.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from . import config


def _parse_time(value: object) -> tuple[int, int] | None:
    try:
        parts = str(value or "").strip().split(":")
        hour, minute = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _weekdays(value: object) -> list[int]:
    result: list[int] = []
    for item in value or []:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in result:
            result.append(day)
    return sorted(result)


def next_run_at(settings: dict, now: datetime | None = None) -> datetime | None:
    """A következő ütemezett futás időpontja (vagy None, ha ki van kapcsolva)."""
    schedule = (settings or {}).get("schedule") or {}
    if not schedule.get("enabled"):
        return None
    parsed = _parse_time(schedule.get("time"))
    days = _weekdays(schedule.get("weekdays"))
    if parsed is None or not days:
        return None
    now = now or datetime.now()
    hour, minute = parsed
    for offset in range(0, 8):
        candidate = (now + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= now:
            continue
        if candidate.weekday() in days:
            return candidate
    return None


class Scheduler(threading.Thread):
    def __init__(
        self,
        manager,
        settings_loader,
        state_file: Path | None = None,
        poll_seconds: float = 20.0,
        catchup_hours: float = 6.0,
    ):
        super().__init__(daemon=True, name="lidl-scheduler")
        self.manager = manager
        self.settings_loader = settings_loader
        self.state_file = Path(state_file or config.SCHEDULER_STATE_FILE)
        self.poll_seconds = poll_seconds
        self.catchup_hours = catchup_hours
        self._stop = threading.Event()
        self._last_run = self._load_state()

    def _load_state(self) -> str:
        if not self.state_file.is_file():
            return ""
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        return str(data.get("last_run") or "")

    def _save_state(self) -> None:
        tmp = self.state_file.with_suffix(".json.tmp")
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps({"last_run": self._last_run}, indent=2), encoding="utf-8"
            )
            tmp.replace(self.state_file)
        except OSError:
            pass

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.tick()
            except Exception:
                traceback.print_exc()

    def tick(self, now: datetime | None = None):
        now = now or datetime.now()
        settings = self.settings_loader() or {}
        schedule = settings.get("schedule") or {}
        if not schedule.get("enabled"):
            return None
        days = _weekdays(schedule.get("weekdays"))
        if not days:
            return None
        parsed = _parse_time(schedule.get("time"))
        if parsed is None:
            return None
        # A legutóbbi esedékes időpont: ma, vagy ha még nem értük el, tegnap.
        # Így éjfél utáni újraindulásnál is pótolható a kimaradt futás.
        target = now.replace(hour=parsed[0], minute=parsed[1], second=0, microsecond=0)
        if target > now:
            target -= timedelta(days=1)
        for _ in range(7):
            if target.weekday() in days:
                break
            target -= timedelta(days=1)
        else:
            return None
        if (now - target).total_seconds() > self.catchup_hours * 3600:
            return None
        target_date = target.date().isoformat()
        if self._last_run == target_date:
            return None
        job, _error = self.manager.start("all", source="schedule")
        if job is None:
            # Foglalt a folyamat; a következő körben újra próbáljuk.
            return None
        self._last_run = target_date
        self._save_state()
        return job
