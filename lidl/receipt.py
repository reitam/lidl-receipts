"""Nyugta JSON feldolgozása: fejlécadatok és tételsorok kinyerése.

A Lidl kétféle formátumban adja a tételeket:
  * újabb: a tételek a htmlPrintedReceipt HTML-ben vannak (Magyarországon ez a jellemző),
  * régebbi: itemsLine JSON tömb.
"""

from __future__ import annotations

import html as html_module
import re
import unicodedata
from datetime import datetime
from typing import Any

ARTICLE_RE = re.compile(
    r'(?s)<span\b([^>]*\bclass="[^"]*\barticle\b[^"]*"[^>]*)>(.*?)</span>'
)
DISCOUNT_RE = re.compile(
    r'(?s)<span\b([^>]*\bclass="[^"]*\bdiscount\b[^"]*"[^>]*)>(.*?)</span>'
)
DATA_ATTR_RE = re.compile(r'data-([a-z-]+)="([^"]*)"')
TAG_RE = re.compile(r"<[^>]+>")
TAX_TAIL_RE = re.compile(r"\s+[A-Za-z]+[0-9]{2}\s*$")
TAX_CODE_RE = re.compile(r"([A-Za-z]+[0-9]{2})\s*$")
TRAILING_NUM_RE = re.compile(r"([0-9][0-9.,\u00a0]*)$")
DISCOUNT_NUM_RE = re.compile(r"(-[0-9][0-9.,\u00a0]*)$")


def parse_amount(value: Any) -> float:
    """'1 234,56' / '1.234,56' / '1234.56' / 1234.5 -> float."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0

    text = text.replace("\u00a0", "").replace("\u202f", "")
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text or text in ("-", ",", "."):
        return 0.0

    last_comma = text.rfind(",")
    last_dot = text.rfind(".")
    if last_comma >= 0 and last_dot >= 0:
        if last_comma > last_dot:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif last_comma >= 0:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return 0.0


def _first(receipt: dict, *keys: str, default=None):
    for key in keys:
        value = receipt.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def receipt_datetime(receipt: dict) -> datetime | None:
    raw = _first(receipt, "date", "datetime", "purchaseDate", "receiptDate")
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=None)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def receipt_total(receipt: dict) -> float:
    return parse_amount(
        _first(receipt, "totalAmount", "total", "amount", "totalPrice", default=0)
    )


def receipt_currency(receipt: dict, default: str = "Ft") -> str:
    value = _first(receipt, "currency", "currencyCode")
    if isinstance(value, dict):
        value = value.get("code") or value.get("symbol")
    if not value:
        return default
    text = str(value).strip()
    return {"HUF": "Ft"}.get(text.upper(), text)


def store_name(receipt: dict) -> str:
    store = receipt.get("store")
    if isinstance(store, dict):
        name = str(store.get("name") or store.get("locality") or store.get("id") or "").strip()
        if name:
            return name
    if isinstance(store, str):
        return store.strip()
    for key in ("storeName", "shopName", "storeID", "storeId"):
        value = receipt.get(key)
        if value:
            return str(value).strip()
    return ""


def enrich_receipts(receipts: list[dict]) -> list[dict]:
    """Kiegészíti a hiányos store-adatokat a többi nyugtából ismert nevekkel."""
    mapping: dict[str, str] = {}
    for receipt in receipts:
        store = receipt.get("store")
        if isinstance(store, dict) and store.get("id") and store.get("name"):
            mapping[str(store["id"])] = str(store["name"])

    for receipt in receipts:
        store = receipt.get("store")
        if isinstance(store, dict):
            if not store.get("name"):
                store_id = str(store.get("id") or "")
                if store_id in mapping:
                    store["name"] = mapping[store_id]
        elif not store:
            store_id = str(receipt.get("storeID") or receipt.get("storeId") or "")
            if store_id:
                receipt["store"] = {"id": store_id, "name": mapping.get(store_id, store_id)}
    return receipts


def _html_items(document: str) -> list[dict]:
    items: list[dict] = []

    events: list[tuple[str, re.Match]] = []
    events.extend(("article", match) for match in ARTICLE_RE.finditer(document))
    events.extend(("discount", match) for match in DISCOUNT_RE.finditer(document))
    events.sort(key=lambda pair: pair[1].start())

    for kind, match in events:
        attrs_blob, inner = match.group(1), match.group(2)
        text = html_module.unescape(TAG_RE.sub("", inner)).strip()
        attrs = {
            key: html_module.unescape(value)
            for key, value in DATA_ATTR_RE.findall(attrs_blob)
        }

        if kind == "discount":
            tax_match = TAX_CODE_RE.search(text)
            tax = tax_match.group(1) if tax_match else ""
            tail = TAX_TAIL_RE.sub("", text).strip()
            amount_match = DISCOUNT_NUM_RE.search(tail)
            if not amount_match:
                continue
            amount = parse_amount(amount_match.group(1))
            name = tail[: amount_match.start()].strip(" -")
            items.append(
                {
                    "name": name or "Kedvezmény",
                    "quantity": 1.0,
                    "unit_price": amount,
                    "line_total": amount,
                    "tax": tax,
                    "art_id": attrs.get("promotion-id", ""),
                }
            )
            continue

        # A magyar nyugtán minden tétel kétszer szerepel: egyszer
        # "2,000 db * 329,00 Ft /db" bontásként, egyszer pedig a leírás
        # soraként, a sor végösszegével és adókódjával.
        if "*" in text:
            continue

        name = attrs.get("art-description", "").strip()
        if not name:
            continue

        quantity = parse_amount(attrs.get("art-quantity"))
        if not quantity:
            quantity = 1.0
        unit_price = parse_amount(attrs.get("unit-price"))

        tail = TAX_TAIL_RE.sub("", text).strip()
        trailing = TRAILING_NUM_RE.search(tail)
        line_total = parse_amount(trailing.group(1)) if trailing else 0.0
        if not line_total:
            line_total = unit_price * quantity

        items.append(
            {
                "name": name,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "tax": attrs.get("tax-type", ""),
                "art_id": attrs.get("art-id", ""),
            }
        )
    return items


def _json_items(receipt: dict) -> list[dict]:
    raw_items = receipt.get("itemsLine") or receipt.get("items") or []
    items: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("description") or "").strip()
        if not name:
            continue
        quantity = parse_amount(raw.get("quantity")) or 1.0
        unit_price = parse_amount(
            raw.get("currentUnitPrice") or raw.get("unitPrice") or raw.get("price")
        )
        line_total = parse_amount(raw.get("originalAmount") or raw.get("totalPrice"))
        if not line_total:
            line_total = unit_price * quantity
        discounts = raw.get("discounts") or []
        discount_total = 0.0
        for discount in discounts:
            if isinstance(discount, dict):
                discount_total += abs(parse_amount(discount.get("amount")))
        items.append(
            {
                "name": name,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "discount": discount_total,
                "tax": str(raw.get("taxGroupName") or raw.get("taxType") or ""),
                "art_id": str(raw.get("codeInput") or raw.get("id") or ""),
            }
        )
    return items


def parse_items(receipt: dict) -> list[dict]:
    document = receipt.get("htmlPrintedReceipt") or ""
    if isinstance(document, str) and document.strip():
        items = _html_items(document)
        if items:
            return items
    return _json_items(receipt)


def safe_filename(text: str, max_length: int = 60) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_text).strip("-._")
    return (ascii_text or "ismeretlen")[:max_length].strip("-._") or "ismeretlen"


def receipt_stem(receipt: dict) -> str:
    moment = receipt_datetime(receipt)
    date_part = moment.strftime("%Y-%m-%d_%H-%M") if moment else "ismeretlen-datum"
    total = receipt_total(receipt)
    total_part = f"{total:.0f}" if abs(total - round(total)) < 0.005 else f"{total:.2f}".replace(".", "_")
    store = safe_filename(store_name(receipt), 40)
    ticket_id = safe_filename(str(receipt.get("id") or ""), 24)
    return f"{date_part}_{store}_{total_part}Ft_{ticket_id}"
