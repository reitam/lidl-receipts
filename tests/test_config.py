"""Beállításfájl (config.json) környezetfüggetlen tesztje."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lidl import config


class SettingsFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lidl-config-")
        self._original = config.SETTINGS_FILE
        config.SETTINGS_FILE = Path(self._tmp.name) / "config.json"

    def tearDown(self) -> None:
        config.SETTINGS_FILE = self._original
        self._tmp.cleanup()

    def test_defaults(self) -> None:
        settings = config.load_settings()
        self.assertFalse(settings["schedule"]["enabled"])
        self.assertEqual(settings["schedule"]["time"], "19:00")
        self.assertFalse(settings["ntfy"]["enabled"])

    def test_roundtrip(self) -> None:
        settings = config.load_settings()
        settings["schedule"] = {"enabled": True, "time": "06:30", "weekdays": [0, 2, 4]}
        settings["ntfy"] = {
            "enabled": True,
            "url": "http://ntfy.example.com:8080",
            "topic": "lidl",
            "token": "titok",
            "on_manual": True,
        }
        config.save_settings(settings)
        self.assertTrue(config.SETTINGS_FILE.is_file())
        loaded = config.load_settings()
        self.assertTrue(loaded["schedule"]["enabled"])
        self.assertEqual(loaded["schedule"]["time"], "06:30")
        self.assertEqual(loaded["schedule"]["weekdays"], [0, 2, 4])
        self.assertEqual(loaded["ntfy"]["topic"], "lidl")
        self.assertTrue(loaded["ntfy"]["on_manual"])

    def test_broken_file_falls_back_to_defaults(self) -> None:
        config.SETTINGS_FILE.write_text("{ ez nem json", encoding="utf-8")
        settings = config.load_settings()
        self.assertFalse(settings["schedule"]["enabled"])
        self.assertEqual(settings["ntfy"]["topic"], "lidl")


if __name__ == "__main__":
    unittest.main()
