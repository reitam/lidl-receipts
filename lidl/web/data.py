"""Nyugta-adatok betöltése, keresése és kimutatások a webes felülethez."""

from __future__ import annotations

import json
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from ..receipt import (
    enrich_receipts,
    parse_items,
    receipt_datetime,
    receipt_total,
    store_name,
)
from ..render import build_page, pdf_path_for, receipt_year
from ..warranty import build_warranty_rows

try:  # a borkimutatás opcionális modul (a publikus buildből kimarad)
    from ..wine import build_wine_rows, monthly_summary

    WINE_AVAILABLE = True
except ImportError:  # pragma: no cover - csak a bor nélküli buildben
    build_wine_rows = None
    monthly_summary = None
    WINE_AVAILABLE = False


def fold(value: object) -> str:
    """Ékezet- és kisbetű-független összehasonlításhoz."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.casefold().strip()


def format_amount(value: float, suffix: str = " Ft") -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    text = f"{number:,.0f}".replace(",", "\u00a0")
    return f"{text}{suffix}" if suffix else text


class ReceiptStore:
    """A JSON nyugták a forrás; mtime alapján cache-el, hogy gyors legyen."""

    def __init__(
        self,
        data_dir: Path,
        output_dir: Path,
        country: str = "HU",
        language: str = "hu",
    ):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.country = country.upper()
        self.language = language.lower()
        self._lock = threading.RLock()
        self._signature: tuple[int, float] | None = None
        self._receipts: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._items: dict[str, list[dict]] = {}
        self._warranty_signature = None
        self._warranty_rows: list[dict] = []
        self._wine_cache: dict[int, list[dict]] = {}

    # -- betöltés ------------------------------------------------------
    @property
    def receipts_dir(self) -> Path:
        return self.data_dir / "receipts" / self.country

    def token_exists(self) -> bool:
        return (self.data_dir / f"token_{self.country}.json").is_file()

    def _signature_now(self) -> tuple[int, float]:
        files = list(self.receipts_dir.glob("*.json"))
        newest = max((path.stat().st_mtime for path in files), default=0.0)
        return len(files), newest

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            signature = self._signature_now()
            if not force and signature == self._signature:
                return
            receipts: list[dict] = []
            for path in sorted(self.receipts_dir.glob("*.json")):
                try:
                    receipts.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
            receipts.sort(
                key=lambda item: receipt_datetime(item) or datetime.min, reverse=True
            )
            enrich_receipts(receipts)
            self._receipts = receipts
            self._by_id = {str(item.get("id") or ""): item for item in receipts}
            self._items.clear()
            self._warranty_signature = None
            self._wine_cache.clear()
            self._signature = signature

    @property
    def receipts(self) -> list[dict]:
        self.refresh()
        return self._receipts

    def get(self, receipt_id: str) -> dict | None:
        self.refresh()
        return self._by_id.get(str(receipt_id))

    def items(self, receipt: dict) -> list[dict]:
        with self._lock:
            key = str(receipt.get("id") or "")
            if key and key in self._items:
                return self._items[key]
            items = parse_items(receipt)
            if key:
                self._items[key] = items
            return items

    # -- szűrés --------------------------------------------------------
    def years(self) -> list[int]:
        return sorted({receipt_datetime(item).year for item in self.receipts if receipt_datetime(item)}, reverse=True)

    def stores(self) -> list[str]:
        return sorted({store_name(item) for item in self.receipts if store_name(item)})

    def search(
        self,
        query: str = "",
        year: int | None = None,
        store: str = "",
        limit: int | None = None,
    ) -> list[dict]:
        needle = fold(query)
        result: list[dict] = []
        for receipt in self.receipts:
            moment = receipt_datetime(receipt)
            if year and (moment is None or moment.year != year):
                continue
            if store and store_name(receipt) != store:
                continue
            if needle:
                haystack = [
                    store_name(receipt),
                    str(receipt.get("id") or ""),
                    moment.strftime("%Y-%m-%d") if moment else "",
                    f"{receipt_total(receipt):.0f}",
                ]
                for item in self.items(receipt):
                    haystack.append(str(item.get("name") or ""))
                    haystack.append(str(item.get("art_id") or ""))
                if not any(needle in fold(value) for value in haystack):
                    continue
            result.append(receipt)
            if limit and len(result) >= limit:
                break
        return result

    # -- statisztika ---------------------------------------------------
    def stats(self) -> dict:
        receipts = self.receipts
        dated = [receipt_datetime(item) for item in receipts if receipt_datetime(item)]
        yearly: dict[int, dict] = {}
        for receipt in receipts:
            moment = receipt_datetime(receipt)
            if not moment:
                continue
            bucket = yearly.setdefault(moment.year, {"year": moment.year, "count": 0, "total": 0.0})
            bucket["count"] += 1
            bucket["total"] += receipt_total(receipt)
        files = list(self.receipts_dir.glob("*.json"))
        pdfs = list(self.output_dir.glob("*/*.pdf")) if self.output_dir.is_dir() else []
        return {
            "token": self.token_exists(),
            "receipts": len(receipts),
            "date_from": min(dated).strftime("%Y-%m-%d") if dated else "",
            "date_to": max(dated).strftime("%Y-%m-%d") if dated else "",
            "total": round(sum(receipt_total(item) for item in receipts), 2),
            "pdfs": len(pdfs),
            "last_fetch": max((path.stat().st_mtime for path in files), default=0.0),
            "yearly": sorted(yearly.values(), key=lambda row: row["year"], reverse=True),
        }

    def new_receipts_since(self, timestamp: float) -> tuple[int, float]:
        """Az adott időpont után letöltött nyugták száma és összege."""
        count = 0
        total = 0.0
        for path in self.receipts_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < timestamp:
                    continue
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            count += 1
            total += receipt_total(receipt)
        return count, total

    # -- kimutatások ---------------------------------------------------
    def warranty_rows(self) -> list[dict]:
        self.refresh()
        with self._lock:
            if self._warranty_signature == self._signature:
                return self._warranty_rows
            rows = build_warranty_rows(self.receipts, self.output_dir)
            self._warranty_rows = rows
            self._warranty_signature = self._signature
            return rows

    def wine_rows(self, year: int) -> list[dict]:
        if not WINE_AVAILABLE:
            return []
        self.refresh()
        with self._lock:
            if year not in self._wine_cache:
                self._wine_cache[year] = build_wine_rows(self.receipts, year, self.output_dir)
            return self._wine_cache[year]

    def wine_summary(self, year: int) -> list[dict]:
        if not WINE_AVAILABLE:
            return []
        return monthly_summary(self.wine_rows(year), year)

    def wine_years(self) -> list[int]:
        return self.years() or [datetime.now().year]

    # -- fájlok --------------------------------------------------------
    def pdf_path(self, receipt: dict) -> Path:
        return pdf_path_for(receipt, self.output_dir)

    def jpg_path(self, receipt: dict) -> Path:
        return self.pdf_path(receipt).with_suffix(".jpg")

    def preview_html(self, receipt: dict) -> str:
        return build_page(receipt, logo_cache_dir=None, paper_copy=False)

    def report_paths(self) -> dict[str, Path]:
        country = self.country
        output = self.output_dir
        return {
            "index_xlsx": output / f"nyugtak_index_{country}.xlsx",
            "index_csv": output / f"nyugtak_index_{country}.csv",
            "items_csv": output / f"nyugtak_tetelek_{country}.csv",
            "warranty_xlsx": output / f"muszaki_garancia_{country}.xlsx",
        }

    def wine_report_path(self, year: int) -> Path:
        return self.output_dir / f"bor_kimutatas_{year}.xlsx"

    @staticmethod
    def receipt_year(receipt: dict) -> str:
        return receipt_year(receipt)
