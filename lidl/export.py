"""Nyugta- és tételjegyzék exportálása CSV-be és Excelbe."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .receipt import (
    enrich_receipts,
    parse_items,
    receipt_currency,
    receipt_datetime,
    receipt_total,
    store_name,
)
from .render import pdf_path_for


def _sort_key(receipt: dict):
    moment = receipt_datetime(receipt)
    return moment or datetime.min


def build_rows(receipts: list[dict], output_root: Path) -> tuple[list[list], list[list]]:
    receipt_rows: list[list] = []
    item_rows: list[list] = []

    for receipt in sorted(receipts, key=_sort_key, reverse=True):
        moment = receipt_datetime(receipt)
        total = receipt_total(receipt)
        currency = receipt_currency(receipt)
        store = store_name(receipt)
        receipt_id = str(receipt.get("id") or "")
        items = parse_items(receipt)

        pdf = pdf_path_for(receipt, output_root)
        pdf_value = ""
        if pdf.exists():
            try:
                pdf_value = str(pdf.relative_to(output_root.parent))
            except ValueError:
                pdf_value = str(pdf)

        note = ""
        if receipt.get("ticketType") == "BROKEN_HTML" or (
            not receipt.get("htmlPrintedReceipt") and not receipt.get("itemsLine")
        ):
            note = "A Lidl nem adott tételadatot (BROKEN_HTML)"

        receipt_rows.append(
            [
                receipt_id,
                moment.strftime("%Y-%m-%d") if moment else "",
                moment.strftime("%H:%M") if moment else "",
                store,
                round(total, 2),
                currency,
                len(items),
                pdf_value,
                note,
            ]
        )
        for item in items:
            item_rows.append(
                [
                    receipt_id,
                    moment.strftime("%Y-%m-%d") if moment else "",
                    store,
                    item["name"],
                    round(item["quantity"], 3),
                    round(item["unit_price"], 2),
                    round(item["line_total"], 2),
                    item.get("tax", ""),
                    "Kedvezmény" if item["line_total"] < 0 else "Tétel",
                ]
            )
    return receipt_rows, item_rows


def _write_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    def write(target: Path) -> None:
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(header)
            writer.writerows(rows)

    try:
        write(path)
        return path
    except PermissionError:
        alternative = path.with_name(
            f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"
        )
        write(alternative)
        return alternative


def _write_xlsx(path: Path, receipt_rows: list[list], item_rows: list[list]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="0050AA")

    receipts_sheet = workbook.active
    receipts_sheet.title = "Nyugták"
    headers = ["Nyugta ID", "Dátum", "Idő", "Bolt", "Összeg", "Valuta", "Tételek", "PDF", "Megjegyzés"]
    receipts_sheet.append(headers)
    for row in receipt_rows:
        receipts_sheet.append(row)
    for cell in receipts_sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
    receipts_sheet.freeze_panes = "A2"
    receipts_sheet.auto_filter.ref = receipts_sheet.dimensions
    widths = [34, 12, 8, 38, 12, 8, 9, 60, 42]
    for index, width in enumerate(widths, 1):
        receipts_sheet.column_dimensions[get_column_letter(index)].width = width
    for cell in receipts_sheet["E"][1:]:
        cell.number_format = "#,##0.00"

    items_sheet = workbook.create_sheet("Tételek")
    item_headers = [
        "Nyugta ID",
        "Dátum",
        "Bolt",
        "Termék",
        "Mennyiség",
        "Egységár",
        "Összeg",
        "Adó",
        "Típus",
    ]
    items_sheet.append(item_headers)
    for row in item_rows:
        items_sheet.append(row)
    for cell in items_sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
    items_sheet.freeze_panes = "A2"
    items_sheet.auto_filter.ref = items_sheet.dimensions
    for index, width in enumerate([34, 12, 30, 46, 12, 12, 12, 8, 12], 1):
        items_sheet.column_dimensions[get_column_letter(index)].width = width
    for cell in items_sheet["F"][1:]:
        cell.number_format = "#,##0.00"
    for cell in items_sheet["G"][1:]:
        cell.number_format = "#,##0.00"

    monthly = defaultdict(lambda: [0.0, 0])
    for row in receipt_rows:
        if row[1]:
            key = row[1][:7]
            monthly[key][0] += float(row[4] or 0)
            monthly[key][1] += 1
    monthly_sheet = workbook.create_sheet("Havi összesítő")
    monthly_sheet.append(["Hónap", "Összeg", "Nyugták száma"])
    for month in sorted(monthly, reverse=True):
        monthly_sheet.append([month, round(monthly[month][0], 2), monthly[month][1]])
    for cell in monthly_sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
    monthly_sheet.column_dimensions["A"].width = 12
    monthly_sheet.column_dimensions["B"].width = 14
    monthly_sheet.column_dimensions["C"].width = 15
    for cell in monthly_sheet["B"][1:]:
        cell.number_format = "#,##0.00"

    try:
        workbook.save(path)
        return path
    except PermissionError:
        alternative = path.with_name(
            f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"
        )
        workbook.save(alternative)
        return alternative


def export_index(
    receipts: list[dict],
    output_root: Path,
    index_dir: Path,
    country: str = "HU",
) -> dict[str, Path]:
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    receipt_rows, item_rows = build_rows(receipts, output_root)

    receipt_header = [
        "Nyugta ID",
        "Dátum",
        "Idő",
        "Bolt",
        "Összeg",
        "Valuta",
        "Tételek",
        "PDF",
        "Megjegyzés",
    ]
    item_header = [
        "Nyugta ID",
        "Dátum",
        "Bolt",
        "Termék",
        "Mennyiség",
        "Egységár",
        "Összeg",
        "Adó",
        "Típus",
    ]

    index_csv = index_dir / f"nyugtak_index_{country}.csv"
    items_csv = index_dir / f"nyugtak_tetelek_{country}.csv"
    index_xlsx = index_dir / f"nyugtak_index_{country}.xlsx"

    index_csv = _write_csv(index_csv, receipt_header, receipt_rows)
    items_csv = _write_csv(items_csv, item_header, item_rows)
    index_xlsx = _write_xlsx(index_xlsx, receipt_rows, item_rows)

    return {"index_csv": index_csv, "items_csv": items_csv, "index_xlsx": index_xlsx}
