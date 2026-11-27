import unittest

from lidl.auth import build_login_url, extract_code, extract_state, new_pkce_pair
from lidl.receipt import parse_amount, parse_items, receipt_stem, receipt_total

SAMPLE_HTML = """<html><body><pre>
<span class="purchase_list"><span id="purchase_list_line_1" class="article" data-art-id="0001" data-art-quantity="1" data-unit-price="499,00" data-tax-type="A" data-art-description="KENYÉR 1KG">KENYÉR 1KG                  499  A00</span>
<span id="purchase_list_line_2" class="article" data-art-id="0002" data-art-quantity="2" data-unit-price="329,00" data-tax-type="A" data-art-description="TEJ 2,8%">2,000 db  *        329,00 Ft /db</span>
<span id="purchase_list_line_3" class="article" data-art-id="0002" data-art-quantity="2" data-unit-price="329,00" data-tax-type="A" data-art-description="TEJ 2,8%">TEJ 2,8%                  658  A00</span>
</span>
</pre></body></html>"""


class AmountTests(unittest.TestCase):
    def test_parse_amount(self):
        cases = {
            "": 0.0,
            "499": 499.0,
            "658,00": 658.0,
            "1.157,00": 1157.0,
            "1 234 Ft": 1234.0,
            "-50,5": -50.5,
            "1,234.56": 1234.56,
            "1\u00a0234,56": 1234.56,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertAlmostEqual(parse_amount(raw), expected, places=2)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.receipt = {
            "id": "RX-001",
            "date": "2026-05-01T14:23:00",
            "totalAmount": 1157.0,
            "htmlPrintedReceipt": SAMPLE_HTML,
            "store": {"name": "Lidl Budapest, Váci út"},
        }

    def test_items_skip_breakdown_line(self):
        items = parse_items(self.receipt)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "KENYÉR 1KG")
        self.assertAlmostEqual(items[0]["line_total"], 499.0)
        self.assertEqual(items[1]["name"], "TEJ 2,8%")
        self.assertAlmostEqual(items[1]["line_total"], 658.0)

    def test_total_and_stem(self):
        self.assertAlmostEqual(receipt_total(self.receipt), 1157.0)
        stem = receipt_stem(self.receipt)
        self.assertIn("2026-05-01_14-23", stem)
        self.assertIn("Lidl-Budapest-Vaci-ut", stem)
        self.assertIn("1157Ft", stem)


class AuthTests(unittest.TestCase):
    def test_pkce_pair(self):
        verifier, challenge = new_pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)
        self.assertNotIn("=", challenge)

    def test_login_url(self):
        url = build_login_url("HU", "hu", "abc123", state="STATE123", nonce="NONCE123")
        self.assertIn("accounts.lidl.com/connect/authorize", url)
        self.assertIn("Country=HU", url)
        self.assertIn("language=hu-HU", url)
        self.assertIn("code_challenge=abc123", url)
        self.assertIn("state=STATE123", url)
        self.assertIn("nonce=NONCE123", url)
        self.assertIn("force=false", url)
        self.assertIn("track=false", url)

    def test_extract_code(self):
        self.assertEqual(extract_code("com.lidlplus.app://callback?code=ABC123&scope=x"), "ABC123")
        self.assertEqual(extract_code("ABC123"), "ABC123")
        with self.assertRaises(Exception):
            extract_code("semmi")

    def test_extract_state(self):
        self.assertEqual(
            extract_state("com.lidlplus.app://callback?code=ABC123&state=XYZ987"),
            "XYZ987",
        )
        self.assertIsNone(extract_state("ABC123"))


if __name__ == "__main__":
    unittest.main()
