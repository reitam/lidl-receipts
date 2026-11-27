"""Ütemező tesztek (a tényleges várakozás nélkül, kézi tickkel)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lidl.scheduler import Scheduler, next_run_at


def settings(enabled: bool = True, time_value: str = "19:00", days=None) -> dict:
    return {
        "schedule": {
            "enabled": enabled,
            "time": time_value,
            "weekdays": list(days if days is not None else range(7)),
        }
    }


class FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.busy = False

    def start(self, action: str, year=None, source: str = "manual"):
        if self.busy:
            return None, "Már fut egy feladat."
        self.calls.append((action, source))
        return object(), None


class NextRunTests(unittest.TestCase):
    def test_same_day(self) -> None:
        now = datetime(2026, 11, 28, 18, 0)  # szombat
        self.assertEqual(next_run_at(settings(), now), datetime(2026, 11, 28, 19, 0))

    def test_next_day_when_passed(self) -> None:
        now = datetime(2026, 11, 28, 20, 0)
        self.assertEqual(next_run_at(settings(), now), datetime(2026, 11, 29, 19, 0))

    def test_weekday_filter(self) -> None:
        now = datetime(2026, 11, 28, 18, 0)  # szombat
        self.assertEqual(
            next_run_at(settings(days=[0]), now), datetime(2026, 11, 30, 19, 0)
        )

    def test_disabled_or_invalid(self) -> None:
        self.assertIsNone(next_run_at(settings(enabled=False), datetime(2026, 11, 28)))
        self.assertIsNone(next_run_at(settings(time_value="25:99"), datetime(2026, 11, 28)))
        self.assertIsNone(next_run_at(settings(days=[]), datetime(2026, 11, 28)))


class TickTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lidl-sched-")
        self.state_file = Path(self._tmp.name) / "scheduler.json"
        self.manager = FakeManager()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make(self, settings_fn=settings) -> Scheduler:
        return Scheduler(
            self.manager, settings_fn, state_file=self.state_file, catchup_hours=6
        )

    def test_runs_once_per_day(self) -> None:
        scheduler = self.make()
        job = scheduler.tick(now=datetime(2026, 11, 28, 19, 5))
        self.assertIsNotNone(job)
        self.assertEqual(self.manager.calls, [("all", "schedule")])
        self.assertIsNone(scheduler.tick(now=datetime(2026, 11, 28, 19, 10)))
        self.assertEqual(len(self.manager.calls), 1)
        self.assertTrue(self.state_file.is_file())

    def test_state_survives_restart(self) -> None:
        first = self.make()
        first.tick(now=datetime(2026, 11, 28, 19, 5))
        second = self.make()
        self.assertIsNone(second.tick(now=datetime(2026, 11, 28, 19, 30)))
        self.assertEqual(len(self.manager.calls), 1)

    def test_busy_is_retried(self) -> None:
        self.manager.busy = True
        scheduler = self.make()
        self.assertIsNone(scheduler.tick(now=datetime(2026, 11, 28, 19, 5)))
        self.manager.busy = False
        self.assertIsNotNone(scheduler.tick(now=datetime(2026, 11, 28, 19, 6)))
        self.assertEqual(len(self.manager.calls), 1)

    def test_catchup_window(self) -> None:
        # 19:00 helyett 00:30-kor indul újra: 5,5 óra, még pótolható.
        scheduler = self.make()
        self.assertIsNotNone(scheduler.tick(now=datetime(2026, 11, 29, 0, 30)))
        # 19:00 után 6,5 órával már nem pótol.
        late = self.make()
        late._last_run = ""
        self.assertIsNone(late.tick(now=datetime(2026, 11, 29, 1, 30)))
        # Másnap 19:01-kor viszont az aznapi futás elindul.
        self.assertIsNotNone(scheduler.tick(now=datetime(2026, 11, 29, 19, 1)))

    def test_disabled_does_nothing(self) -> None:
        scheduler = self.make(lambda: settings(enabled=False))
        self.assertIsNone(scheduler.tick(now=datetime(2026, 11, 28, 19, 5)))
        self.assertEqual(self.manager.calls, [])


if __name__ == "__main__":
    unittest.main()
