"""Webes felület és adatréteg tesztek (stdlib unittest + FastAPI TestClient)."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lidl.jobs import JobManager
from lidl.web import app as web_app
from lidl.web.app import create_app
from lidl.web.data import WINE_AVAILABLE, ReceiptStore
from lidl.web.loginflow import LoginFlowStore
from lidl.web.security import Auth, SESSION_COOKIE

from lidl.auth import AuthError, TokenStore

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - csak ha a fejlesztői csomag hiányzik
    TestClient = None

HTML = """<html><body><pre>
<span class="article" data-art-id="0446001" data-unit-price="11111,00" data-tax-type="C" data-art-description="AKK SAROKC">AKK SAROKC' '0446001  11&nbsp;111  C00</span>
<span class="article" data-art-id="7202195" data-unit-price="379,00" data-tax-type="C" data-art-description="NYERSSZEL.GOJI">NYERSSZEL.GOJI  379  C00</span>
</pre></body></html>"""


HTML_WINE = """<html><body><pre>
<span class="article" data-art-id="1234567" data-unit-price="1499,00" data-tax-type="C" data-art-description="BOR">BOR  1&nbsp;499  C00</span>
</pre></body></html>"""


def receipt(
    receipt_id: str,
    date: str,
    amount: float,
    store: str = "Tatabánya, Szent Borbála utca",
    html: str = HTML,
) -> dict:
    return {
        "id": receipt_id,
        "date": date,
        "totalAmount": amount,
        "store": {"id": "HU0189", "name": store},
        "htmlPrintedReceipt": html,
        "codes": [],
    }


class WebTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lidl-test-")
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.output_dir = self.root / "nyugtak"
        receipts_dir = self.data_dir / "receipts" / "HU"
        receipts_dir.mkdir(parents=True)
        (self.output_dir / "2024").mkdir(parents=True)
        self.receipts = [
            receipt("T1", "2024-06-17T10:58:11", 19489.0),
            receipt("T2", "2024-11-28T09:00:00", 7999.0, "Siófok, Zamárdi utca", HTML_WINE),
            receipt("T3", "2025-01-05T12:00:00", 1234.0, html=HTML_WINE),
        ]
        for item in self.receipts:
            (receipts_dir / f"{item['id']}.json").write_text(
                json.dumps(item, ensure_ascii=False), encoding="utf-8"
            )
        (self.output_dir / "2024" / "dummy.pdf").write_bytes(b"%PDF-1.4")

        self.settings = {
            "country": "HU",
            "language": "hu",
            "app_version": "",
            "schedule": {"enabled": False, "time": "19:00", "weekdays": [0, 1, 2, 3, 4, 5, 6]},
            "ntfy": {"enabled": False, "url": "", "topic": "lidl", "token": "", "on_manual": False},
        }
        self.store = ReceiptStore(self.data_dir, self.output_dir)
        self.manager = JobManager(
            self.data_dir, self.output_dir, settings_loader=lambda: self.settings
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- adatréteg -----------------------------------------------------
    def test_store_stats_and_years(self) -> None:
        stats = self.store.stats()
        self.assertEqual(stats["receipts"], 3)
        self.assertEqual([row["year"] for row in stats["yearly"]], [2025, 2024])
        self.assertAlmostEqual(stats["total"], 28722.0)
        self.assertEqual(self.store.years(), [2025, 2024])
        self.assertIn("Tatabánya, Szent Borbála utca", self.store.stores())

    def test_search_is_accent_insensitive_and_searches_items(self) -> None:
        self.assertEqual(len(self.store.search("tatabanya")), 2)
        self.assertEqual([item["id"] for item in self.store.search("sarokc")], ["T1"])
        self.assertEqual([item["id"] for item in self.store.search("0446001")], ["T1"])
        self.assertEqual([item["id"] for item in self.store.search("siófok")], ["T2"])
        self.assertEqual([item["id"] for item in self.store.search("", 2025)], ["T3"])

    def test_items_are_parsed_from_html(self) -> None:
        items = self.store.items(self.receipts[0])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["art_id"], "0446001")
        self.assertEqual(items[0]["line_total"], 11111.0)

    # -- feladatkezelés ------------------------------------------------
    def test_job_validation_and_commands(self) -> None:
        self.assertIsNone(self.manager.build_command("nope"))
        if WINE_AVAILABLE:
            self.assertIsNone(self.manager.build_command("wine", 1000))
            command = self.manager.build_command("wine", 2024)
            self.assertIsNotNone(command)
            self.assertEqual(command[-2:], ["--year", "2024"])
        else:
            self.assertIsNone(self.manager.build_command("wine", 2024))
        job, error = self.manager.start("nope")
        self.assertIsNone(job)
        self.assertTrue(error)

    def test_job_runs_and_reports_error_without_receipts(self) -> None:
        # Üres adatmappával a warranty azonnal hibával tér vissza, de a
        # folyamatkezelésnek és a naplózásnak működnie kell.
        empty = self.root / "empty"
        manager = JobManager(empty, self.output_dir, settings_loader=lambda: self.settings)
        job, error = manager.start("warranty")
        self.assertIsNone(error)
        self.assertIsNotNone(job)
        for _ in range(120):
            if manager.get(job.id).status != "running":
                break
            time.sleep(0.1)
        finished = manager.get(job.id)
        self.assertEqual(finished.status, "error")
        self.assertTrue(finished.log_path.is_file())
        self.assertIn("Nincs letöltött nyugta", manager.log_text(finished))

    # -- bejelentkezés -------------------------------------------------
    def test_auth_handles_non_ascii_values(self) -> None:
        auth = Auth("jelszó")
        self.assertIsNone(auth.login("árvíztűrő"))
        self.assertIsNotNone(auth.login("jelszó"))
        self.assertFalse(auth.csrf_ok("árvíztűrő"))
        self.assertTrue(auth.csrf_ok(auth.csrf))

    def test_login_flow_rejects_state_mismatch(self) -> None:
        flows = LoginFlowStore(TokenStore(self.data_dir / "token_HU.json"))
        flow = flows.start("HU", "hu")
        self.assertIn("accounts.lidl.com", flow.url)
        with self.assertRaises(AuthError):
            flows.finish("com.lidlplus.app://callback?code=ABC123&state=wrong")
        self.assertIsNotNone(flows.current())

    # -- web -----------------------------------------------------------
    def test_notifier_flags_expired_token(self) -> None:
        settings = json.loads(json.dumps(self.settings))
        settings["ntfy"] = {
            "enabled": True,
            "url": "http://example.invalid",
            "topic": "lidl",
            "token": "",
            "on_manual": False,
        }
        notifier = web_app._make_notifier(self.store, lambda: settings)
        job = SimpleNamespace(
            status="error",
            source="schedule",
            label="Teljes frissítés",
            started_at=0.0,
            duration="2 s",
            output="Hiba: A Lidl elutasította a tokent (HTTP 401)",
        )
        with patch("lidl.web.app.send_notify") as mocked:
            notifier(job)
        self.assertTrue(mocked.called)
        title = mocked.call_args.args[1]
        self.assertIn("bejelentkezés", title.lower())

    def client(self, password: str = "") -> tuple["TestClient", Auth]:
        auth = Auth(password)
        app = create_app(
            self.store, self.manager, auth, lambda: self.settings, None
        )
        return TestClient(app), auth

    @unittest.skipIf(TestClient is None, "fastapi/httpx nincs telepítve")
    def test_pages_render(self) -> None:
        client, _auth = self.client()
        paths = [
            "/health",
            "/",
            "/receipts",
            "/receipts?q=sarokc",
            "/reports",
            "/reports/warranty",
            "/settings",
            "/auth",
            "/jobs",
            "/receipts/T1",
            "/receipts/T1/preview",
        ]
        if WINE_AVAILABLE:
            paths.append("/reports/wine")
        for path in paths:
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
        health = client.get("/health").json()
        self.assertEqual(health["receipts"], 3)
        self.assertEqual(health["version"], "2.0.0")

    @unittest.skipIf(TestClient is None, "fastapi/httpx nincs telepítve")
    def test_csrf_and_invalid_action(self) -> None:
        client, auth = self.client()
        response = client.post("/jobs/start", data={"csrf": "bad", "action": "export"})
        self.assertEqual(response.status_code, 403)
        response = client.post(
            "/jobs/start",
            data={"csrf": auth.csrf, "action": "nope"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("kind=err", response.headers["location"])

    @unittest.skipIf(TestClient is None, "fastapi/httpx nincs telepítve")
    def test_password_protects_ui(self) -> None:
        client, auth = self.client("titok")
        response = client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))
        response = client.post(
            "/login",
            data={"csrf": auth.csrf, "password": "rossz", "next": "/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 401)
        response = client.post(
            "/login",
            data={"csrf": auth.csrf, "password": "titok", "next": "/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.cookies.get(SESSION_COOKIE))
        response = client.get("/")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
