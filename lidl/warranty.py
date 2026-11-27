"""Műszaki cikk / szerszám 3 éves garancia kimutatás.

A nyugtákon a terméknevek rövidítettek, ezért a besorolás szabályalapú,
és minden sornál jelzi a bizonyosságot (Biztos / Valószínű / Bizonytalan).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from .receipt import parse_items, receipt_datetime, store_name
from .render import pdf_path_for


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _r(pattern: str, interpretation: str, confidence: str, category: str):
    return (re.compile(pattern), interpretation, confidence, category)


# Ezek a szabályok a rövidített nevek alapján is felismerhető, egyértelmű
# műszaki/szerszám tételeket fedik le. Sorrend számít: a specifikusabb elöl.
_SPECIFIC_RULES = [
    _r(r"akkus utve", "Akkus ütvecsavarozó (Parkside)", "Biztos", "Szerszám"),
    _r(r"akk\.? sarok|akk sarok", "Akkus sarokcsiszoló (Parkside)", "Biztos", "Szerszám"),
    _r(r"sarokcsisz", "Sarokcsiszoló", "Biztos", "Szerszám"),
    _r(r"akkus pors", "Akkus porszívó", "Biztos", "Háztartási gép"),
    _r(r"akkus kert", "Akkus kerti szerszám", "Valószínű", "Kerti gép"),
    _r(r"akkumul", "Akkumulátor (Parkside)", "Biztos", "Akkumulátor"),
    _r(r"furo-?[ ]*es ve|furo es ve", "Fúró- és vésőkalapács", "Biztos", "Szerszám"),
    _r(r"kalapacsfu", "Kalapácsfúró", "Biztos", "Szerszám"),
    _r(r"furotokman", "Fúrótokmány", "Biztos", "Szerszám"),
    _r(r"fafuro kes", "Fafúrókészlet", "Biztos", "Szerszám"),
    _r(r"hss furokesz", "HSS fúrókészlet", "Biztos", "Szerszám"),
    _r(r"lepcso? f[uú]", "Lépcsős fúró", "Biztos", "Szerszám"),
    _r(r"bimetal ly", "Bimetál lyukfűrész", "Biztos", "Szerszám"),
    _r(r"furoszar", "Fúrószár / fúróél", "Bizonytalan", "Szerszám"),
    _r(r"fureszlap", "Fűrészlap-készlet", "Bizonytalan", "Szerszám"),
    _r(r"multifun", "Multifunkciós szerszám", "Biztos", "Szerszám"),
    _r(r"kompressz|mini kompr", "Kompresszor", "Biztos", "Szerszám"),
    _r(r"hegesztokesz", "Hegesztőkészülék", "Biztos", "Szerszám"),
    _r(r"hegesztofu", "Hegesztő fúvóka", "Valószínű", "Szerszám"),
    _r(r"forrasztol|forrasztos", "Forrasztópáka / forrasztóállomás", "Biztos", "Szerszám"),
    _r(r"elezogep", "Élezőgép", "Biztos", "Szerszám"),
    _r(r"nyomatekk", "Nyomatékkulcs", "Biztos", "Szerszám"),
    _r(r"lezeres ta", "Lézeres távolságmérő", "Biztos", "Mérőműszer"),
    _r(r"vizmertek", "Vízmérték", "Valószínű", "Mérőműszer"),
    _r(r"homero|homersekle", "Hőmérő", "Valószínű", "Mérőműszer"),
    _r(r"digitalis", "Digitális mérőműszer", "Bizonytalan", "Mérőműszer"),
    _r(r"ragasztopis", "Ragasztópisztoly", "Biztos", "Szerszám"),
    _r(r"gazego", "Gázégő", "Biztos", "Szerszám"),
    _r(r"izzo kortefo", "Izzó", "Valószínű", "Elektromos"),
    _r(r"csavarhuzo", "Csavarhúzó", "Biztos", "Kéziszerszám"),
    _r(r"fogokeszle", "Fogókészlet", "Biztos", "Kéziszerszám"),
    _r(r"ollo keszl", "Ollókészlet", "Biztos", "Kéziszerszám"),
    _r(r"bard", "Bárd", "Biztos", "Kéziszerszám"),
    _r(r"spakli kes|lapos spat", "Spakli", "Biztos", "Kéziszerszám"),
    _r(r"keselezo", "Késélező", "Biztos", "Kéziszerszám"),
    _r(r"csomagrog", "Csomagrögzítő heveder", "Valószínű", "Szerszám"),
    _r(r"kampo kesz", "Kampókészlet", "Bizonytalan", "Szerszám"),
    _r(r"rabitzfogo", "Rabitztogó", "Biztos", "Kéziszerszám"),
    _r(r"szegecs ke", "Szegecskészlet", "Valószínű", "Szerszám"),
    _r(r"tuzogep ke", "Tűzőgép készlet", "Biztos", "Szerszám"),
    _r(r"csapszegva", "Csapszegvágó", "Valószínű", "Szerszám"),
    _r(r"negyszoges", "Négyszög", "Valószínű", "Kéziszerszám"),
    _r(r"meroszalag", "Mérőszalag", "Biztos", "Kéziszerszám"),
    _r(r"muanyag cs|csovago", "Csővágó", "Biztos", "Szerszám"),
    _r(r"vagokeszlet", "Vágókészlet", "Biztos", "Szerszám"),
    _r(r"szerszamos", "Szerszámos készlet", "Biztos", "Szerszám"),
    _r(r"barkacsdob", "Barkácsdoboz", "Biztos", "Szerszám"),
    _r(r"bitkeszlet|bit- es cs", "Bitkészlet", "Biztos", "Szerszám"),
    _r(r"melydugoku", "Mélydugókulcs-készlet", "Biztos", "Szerszám"),
    _r(r"racsnis", "Racsnis kulcsszett", "Biztos", "Szerszám"),
    _r(r"kombinalt", "Kombinált kulcs/fogó", "Valószínű", "Kéziszerszám"),
    _r(r"5 colos ta", "5 colos tartó/szorító", "Bizonytalan", "Szerszám"),
    _r(r"gyemant", "Gyémánt fúró/vágó", "Valószínű", "Szerszám"),
    _r(r"kezi csisz", "Kézi csiszoló", "Biztos", "Szerszám"),
    _r(r"szalagcsis", "Szalagcsiszoló", "Biztos", "Szerszám"),
    _r(r"kerti toml", "Kerti tömlő", "Valószínű", "Kerti"),
    _r(r"kerti szer", "Kerti szerszám", "Valószínű", "Kerti"),
    _r(r"kerti", "Kerti szerszám", "Valószínű", "Kerti"),
    _r(r"fusze?gely", "Fűszegélynyíró", "Biztos", "Kerti gép"),
    _r(r"cserjevago", "Cserjevágó", "Biztos", "Kerti gép"),
    _r(r"szedoollo|metszoollo", "Szedő-/metszőolló", "Biztos", "Kerti"),
    _r(r"bypass", "Bypass kerti metszőolló", "Valószínű", "Kerti"),
    _r(r"gereblye", "Gereblye", "Biztos", "Kerti"),
    _r(r"kiskapa", "Kiskapa", "Biztos", "Kerti"),
    _r(r"lapat", "Lapát", "Biztos", "Kerti"),
    _r(r"ontozo|locsolo", "Öntöző-/locsolókanna", "Valószínű", "Kerti"),
    _r(r"permetezo|multi perm|2 agu szor", "Permetező", "Valószínű", "Kerti"),
    _r(r"tomloc?satl", "Kerti tömlőcsatlakozó", "Valószínű", "Kerti"),
    _r(r"kerekparpo|kereparpon", "Kerékpárpumpa", "Biztos", "Kerti"),
    _r(r"teleszkopo", "Teleszkópos pole", "Valószínű", "Kerti"),
    _r(r"novenyhaz", "Növényház", "Valószínű", "Kerti"),
    _r(r"led lampa|led izzo|led panel|led fenyfu|lampakeszl|fejlampa|asztali la|fali ora", "LED lámpa / világítás", "Valószínű", "Elektromos"),
    _r(r"adapter", "Adapter", "Biztos", "Elektromos"),
    _r(r"eloszt|hosszabbit", "Elosztó / hosszabbító", "Biztos", "Elektromos"),
    _r(r"tolto kabel|tolto?kabel", "Töltőkábel", "Valószínű", "Elektromos"),
    _r(r"toltheto e", "Tölthető elem", "Valószínű", "Elektromos"),
    _r(r"eger", "Számítógépes egér", "Biztos", "Elektromos"),
    _r(r"elektromos", "Elektromos készülék", "Bizonytalan", "Elektromos"),
    _r(r"elekt\.? hut", "Elektromos hűtőláda", "Biztos", "Háztartási gép"),
    _r(r"futoventil", "Fűtőventilátor", "Biztos", "Háztartási gép"),
    _r(r"vizparas", "Párásító", "Biztos", "Háztartási gép"),
    _r(r"ruhaszarit", "Ruhaszárító", "Biztos", "Háztartási gép"),
    _r(r"vakuumozo", "Vákuumozó", "Biztos", "Háztartási gép"),
    _r(r"laminalogep", "Laminálógép", "Biztos", "Háztartási gép"),
    _r(r"botmixer", "Botmixer", "Biztos", "Háztartási gép"),
    _r(r"konyhai ro", "Konyhai robotgép", "Valószínű", "Háztartási gép"),
    _r(r"mosogep fe", "Mosógép / mosógép-kiegészítő", "Bizonytalan", "Háztartási gép"),
    _r(r"hajszarit", "Hajszárító", "Biztos", "Háztartási gép"),
    _r(r"hidr\.? auto", "Hidraulikus autóemelő", "Biztos", "Autó"),
]

_EXCLUDES = [
    _r(r"csiszolo?pa", "", "", ""),
    _r(r"aa elem|gombelem|tronic.*elem|super elem|elem micro|elem mignon", "", "", ""),
    _r(r"butan gazp", "", "", ""),
    _r(r"kabelkotoz", "", "", ""),
    _r(r"csavar 4x4|facsavar", "", "", ""),
    _r(r"ragaszt", "", "", ""),
    _r(r"szil\.? fuga|szerelo?rag|rag\.? szalag", "", "", ""),
    _r(r"vakszegecs|sarokvas|szogcsatl|tepozaras", "", "", ""),
    _r(r"zsinor|kotel", "", "", ""),
    _r(r"munkkeszty|vedoszemu|sportszemu|terd?elo|terdtamasz|kineziol", "", "", ""),
    _r(r"autos|szelvedo|e-bike tis|teli szelvedo", "", "", ""),
    _r(r"kemping|grill", "", "", ""),
    _r(r"novhuzat|zseles", "", "", ""),
    _r(r"matrica|ablakmatri|foliateker|gyertya|illatgyertya", "", "", ""),
    _r(r"karacs|dekor|fuzet|koszontolap|legyezotar", "", "", ""),
    _r(r"memoriafej|szamrejtveny|puzzle|lego|pluss|gyermek lo|jatek", "", "", ""),
    _r(r"tarolo|rendszerez|mosokosar|vallfa|wc-uloke|furdokad", "", "", ""),
    _r(r"takaro|takaropony|hatizsak|turahatizs|taska|kulacs|sportkulac", "", "", ""),
    _r(r"hajkefe|kornom|kornos", "", "", ""),
    _r(r"papirtorlo|konyhai torlo", "", "", ""),
    _r(r"mosogatogep|mosogatoszer|mosogatotabletta", "", "", ""),
    _r(r"mosogep tabletta|mosogep tiszt|mosogep apolo", "", "", ""),
]

_PRE_EXCLUDES = [
    _r(r"olaj", "", "", ""),
    _r(r"lollos|candy|nyaloka", "", "", ""),
    _r(r"szunyog|rovar", "", "", ""),
    _r(r"macsk|kutya", "", "", ""),
]

_BROAD_RULES = [
    _r(r"furesz", "Fűrész", "Biztos", "Szerszám"),
    _r(r"furo", "Fúró", "Biztos", "Szerszám"),
    _r(r"csiszol", "Csiszoló", "Biztos", "Szerszám"),
    _r(r"kalapacs", "Kalapács", "Biztos", "Kéziszerszám"),
    _r(r"kulcs", "Kulcs", "Valószínű", "Kéziszerszám"),
    _r(r"fogo", "Fogó", "Biztos", "Kéziszerszám"),
    _r(r"ollo", "Olló", "Biztos", "Kéziszerszám"),
    _r(r"\baso\b", "Ásó", "Biztos", "Kerti"),
    _r(r"\bkapa\b", "Kapa", "Biztos", "Kerti"),
    _r(r"funyiro|sarlo|motoros kapalo", "Fűnyíró / sarló / motoros kapáló", "Biztos", "Kerti gép"),
    _r(r"lampa", "Lámpa", "Valószínű", "Elektromos"),
    _r(r"izzo", "Izzó", "Valószínű", "Elektromos"),
    _r(r"\btolto\b", "Töltő", "Valószínű", "Elektromos"),
    _r(r"kabel", "Kábel", "Valószínű", "Elektromos"),
    _r(r"ventil", "Ventilátor", "Valószínű", "Elektromos"),
    _r(r"hosut|hutogep", "Hűtő / hősütő", "Valószínű", "Háztartási gép"),
    _r(r"parasit", "Párásító", "Valószínű", "Háztartási gép"),
    _r(r"porsziv", "Porszívó", "Biztos", "Háztartási gép"),
    _r(r"kavefozo", "Kávéfőző", "Biztos", "Háztartási gép"),
    _r(r"vasalo", "Vasaló", "Biztos", "Háztartási gép"),
    _r(r"homero", "Hőmérő", "Valószínű", "Mérőműszer"),
    _r(r"merleg", "Mérleg", "Valószínű", "Mérőműszer"),
    _r(r"\bradio\b", "Rádió", "Valószínű", "Elektromos"),
    _r(r"fejhallgato", "Fejhallgató", "Valószínű", "Elektromos"),
    _r(r"monitor", "Monitor", "Valószínű", "Elektromos"),
    _r(r"nyomtato", "Nyomtató", "Valószínű", "Elektromos"),
    _r(r"router|modem", "Router / modem", "Valószínű", "Elektromos"),
    _r(r"kamera", "Kamera", "Valószínű", "Elektromos"),
    _r(r"riaszto", "Riasztó", "Valószínű", "Elektromos"),
    _r(r"mozgaserzekelo", "Mozgásérzékelő", "Valószínű", "Elektromos"),
    _r(r"multimeter|feszultsegmero", "Multiméter", "Valószínű", "Mérőműszer"),
    _r(r"hoszivattyu|kazan|vizmelegito|legkondi|legtisztito|szellozteto", "Háztartási gép", "Valószínű", "Háztartási gép"),
]

_CLOTHING_KEYWORDS = [
    "pizsama", "zokni", "triko", "nadrag", "dzseki", "kapucni", "papucs",
    "bakancs", "boxer", "melle", "felso", "also", "haloing", "rovnad",
    "bermuda", "munknad", "munkzok",
]


def _is_clothing(name: str) -> bool:
    n = _norm(name)
    if n.startswith(("f ", "ff ", "l ", "n ", "gy ", "gyermek ")):
        return True
    return any(keyword in n for keyword in _CLOTHING_KEYWORDS)


def classify_item(name: str) -> tuple[str, str, str] | None:
    n = _norm(name)
    if _is_clothing(name):
        return None
    for pattern, _, _, _ in _PRE_EXCLUDES:
        if pattern.search(n):
            return None
    for pattern, interpretation, confidence, category in _SPECIFIC_RULES:
        if pattern.search(n):
            return interpretation, confidence, category
    for pattern, _, _, _ in _EXCLUDES:
        if pattern.search(n):
            return None
    for pattern, interpretation, confidence, category in _BROAD_RULES:
        if pattern.search(n):
            return interpretation, confidence, category
    return None


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def build_warranty_rows(receipts: list[dict], output_root: Path) -> list[dict]:
    today = date.today()
    rows: list[dict] = []
    for receipt in receipts:
        moment = receipt_datetime(receipt)
        if moment is None:
            continue
        purchase = moment.date()
        expiry = _add_years(purchase, 3)
        days_left = (expiry - today).days
        status = "Aktív" if days_left >= 0 else "Lejárt"
        pdf_path = pdf_path_for(receipt, Path(output_root))
        store = store_name(receipt)
        receipt_id = str(receipt.get("id") or "")
        for item in parse_items(receipt):
            classified = classify_item(item["name"])
            if classified is None:
                continue
            interpretation, confidence, category = classified
            if confidence == "Biztos":
                note = "Egyértelmű terméknév a nyugtán."
            elif confidence == "Valószínű":
                note = "A terméknév a nyugtán rövidített; cikkszám/ár alapján következtetés."
            else:
                note = "A blokkról nem derül ki egyértelműen; következtetés, nem hivatalos terméknév."
            rows.append(
                {
                    "date": purchase,
                    "store": store,
                    "original": item["name"],
                    "interpretation": interpretation,
                    "article_id": str(item.get("art_id") or ""),
                    "price": float(item["line_total"]),
                    "expiry": expiry,
                    "status": status,
                    "days_left": days_left,
                    "confidence": confidence,
                    "category": category,
                    "pdf": pdf_path,
                    "receipt_id": receipt_id,
                    "note": note,
                }
            )
    rows.sort(key=lambda row: (row["date"], row["original"]), reverse=True)
    return rows


def _header_style(cell):
    from openpyxl.styles import Alignment, Font, PatternFill

    cell.font = Font(bold=True, color="FFFFFF", size=11)
    cell.fill = PatternFill("solid", fgColor="1F4E79")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_table(ws, title: str, rows: list[dict], start_row: int = 3) -> int:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    headers = [
        "Dátum",
        "Bolt",
        "Eredeti tételnév",
        "Értelmezés (mi lehet)",
        "Cikkszám",
        "Ár (Ft)",
        "Garancia lejár",
        "Státusz",
        "Hátralévő napok",
        "Bizonyosság",
        "Kategória",
        "Nyugta PDF",
        "Nyugta ID",
        "Megjegyzés",
    ]
    ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=16, color="1F4E79")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col, value=header)
        _header_style(cell)

    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    active_fill = PatternFill("solid", fgColor="C6EFCE")
    expired_fill = PatternFill("solid", fgColor="FFC7CE")
    link_font = Font(color="0563C1", underline="single")
    red_font = Font(color="C00000")
    confidence_colors = {"Biztos": "006100", "Valószínű": "9C6500", "Bizonytalan": "9C0006"}

    for row_index, row in enumerate(rows, start_row):
        values = [
            row["date"],
            row["store"],
            row["original"],
            row["interpretation"],
            row["article_id"],
            row["price"],
            row["expiry"],
            row["status"],
            row["days_left"],
            row["confidence"],
            row["category"],
            None,
            row["receipt_id"],
            row["note"],
        ]
        for col, value in enumerate(values, 1):
            cell = ws.cell(row=row_index, column=col, value=value)
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=(col in (2, 3, 4, 14)))
        ws.cell(row=row_index, column=1).number_format = "yyyy-mm-dd"
        ws.cell(row=row_index, column=5).number_format = "@"
        ws.cell(row=row_index, column=6).number_format = '#,##0" Ft"'
        ws.cell(row=row_index, column=7).number_format = "yyyy-mm-dd"
        ws.cell(row=row_index, column=8).fill = active_fill if row["status"] == "Aktív" else expired_fill
        ws.cell(row=row_index, column=9).number_format = "0"
        if row["days_left"] < 0:
            ws.cell(row=row_index, column=9).font = red_font
        ws.cell(row=row_index, column=10).font = Font(color=confidence_colors.get(row["confidence"], "000000"))
        ws.cell(row=row_index, column=13).number_format = "@"

        link_cell = ws.cell(row=row_index, column=12)
        if row["pdf"].is_file():
            link_cell.value = "Megnyitás"
            link_cell.hyperlink = row["pdf"].resolve().as_uri()
            link_cell.font = link_font
        else:
            link_cell.value = "PDF hiányzik"
            link_cell.font = red_font

    widths = [12, 30, 34, 38, 12, 13, 14, 10, 14, 13, 16, 13, 24, 55]
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:N{max(2, start_row + len(rows) - 1)}"
    return start_row + len(rows)


def _write_summary(ws, rows: list[dict], active_rows: list[dict]) -> None:
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    ws["A1"] = "Műszaki cikk / szerszám 3 éves garancia – összesítő"
    ws["A1"].font = Font(bold=True, size=16, color="1F4E79")
    ws.merge_cells("A1:D1")
    ws["A2"] = "Készült:"
    ws["B2"] = date.today()
    ws["B2"].number_format = "yyyy-mm-dd"
    ws["A3"] = "Összes érintett tétel:"
    ws["B3"] = len(rows)
    ws["A4"] = "Aktív garancia:"
    ws["B4"] = len(active_rows)
    ws["A5"] = "Lejárt garancia:"
    ws["B5"] = len(rows) - len(active_rows)
    ws["A6"] = "Összes érték:"
    ws["B6"] = sum(row["price"] for row in rows)
    ws["B6"].number_format = '#,##0" Ft"'
    ws["A7"] = "Aktív tételek értéke:"
    ws["B7"] = sum(row["price"] for row in active_rows)
    ws["B7"].number_format = '#,##0" Ft"'
    for cell in ("A2", "A3", "A4", "A5", "A6", "A7"):
        ws[cell].font = Font(bold=True)

    category_totals = defaultdict(lambda: [0, 0.0])
    for row in rows:
        category_totals[row["category"]][0] += 1
        category_totals[row["category"]][1] += row["price"]
    ws["D2"] = "Kategória"
    ws["E2"] = "Darab"
    ws["F2"] = "Összeg"
    for cell in ("D2", "E2", "F2"):
        _header_style(ws[cell])
    for i, (category, (count, total)) in enumerate(sorted(category_totals.items()), 3):
        ws.cell(row=i, column=4, value=category)
        ws.cell(row=i, column=5, value=count)
        cell = ws.cell(row=i, column=6, value=total)
        cell.number_format = '#,##0" Ft"'

    year_totals = defaultdict(lambda: [0, 0.0])
    for row in rows:
        year_totals[row["date"].year][0] += 1
        year_totals[row["date"].year][1] += row["price"]
    ws["H2"] = "Év"
    ws["I2"] = "Darab"
    ws["J2"] = "Összeg"
    for cell in ("H2", "I2", "J2"):
        _header_style(ws[cell])
    for i, (year, (count, total)) in enumerate(sorted(year_totals.items(), reverse=True), 3):
        ws.cell(row=i, column=8, value=year)
        ws.cell(row=i, column=9, value=count)
        cell = ws.cell(row=i, column=10, value=total)
        cell.number_format = '#,##0" Ft"'

    confidence_totals = defaultdict(int)
    for row in rows:
        confidence_totals[row["confidence"]] += 1
    ws["L2"] = "Bizonyosság"
    ws["M2"] = "Darab"
    for cell in ("L2", "M2"):
        _header_style(ws[cell])
    for i, (confidence, count) in enumerate(sorted(confidence_totals.items()), 3):
        ws.cell(row=i, column=12, value=confidence)
        ws.cell(row=i, column=13, value=count)

    widths = {"A": 24, "B": 14, "C": 2, "D": 18, "E": 10, "F": 14, "G": 2, "H": 10, "I": 10, "J": 14, "K": 2, "L": 14, "M": 10}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def _write_methodology(ws) -> None:
    from openpyxl.styles import Alignment, Font

    ws["A1"] = "Módszertan és értelmezés"
    ws["A1"].font = Font(bold=True, size=16, color="1F4E79")
    paragraphs = [
        "A kimutatás a Lidl Plus-ból letöltött nyugták tételsorai alapján készült.",
        "A nyugtán a terméknevek gyakran rövidítettek. Az „Eredeti tételnév” oszlop a nyugtán szereplő szöveg, az „Értelmezés (mi lehet)” oszlop következtetés, nem a gyártó hivatalos termékneve.",
        "Bizonyosság: Biztos = egyértelmű terméknév; Valószínű = rövidített, de jellegzetes név; Bizonytalan = a blokkból nem derül ki egyértelműen.",
        "A garancia lejárata a vásárlás napja + 3 év. A tényleges garancia a termék csomagolásán / garancialevelén szereplő feltételek szerint alakulhat.",
        "A 3 éves garancia a Lidl non-food / műszaki cikkeire jellemző; egyes termékeknél ettől eltérhet.",
        "A „Nyugta PDF” hivatkozás a helyi nyugtak mappára mutat. Ha átmozgatod a mappát vagy másik gépre viszed, a hivatkozások elavulhatnak.",
        "A kimutatás nem tartalmazza az élelmiszereket, a ruházatot, a háztartási fogyóeszközöket, a játékokat és a nyilvánvaló kiegészítőket.",
        "A besorolás szabályalapú; ha egy tétel hiányzik vagy hibásan szerepel, a lidl/warranty.py szabályai igazíthatók.",
    ]
    for i, text in enumerate(paragraphs, 3):
        cell = ws.cell(row=i, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[i].height = 34
    ws.column_dimensions["A"].width = 120


def export_warranty_excel(
    rows: list[dict],
    path: Path,
) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    active_rows = sorted(
        [row for row in rows if row["status"] == "Aktív"],
        key=lambda row: (row["expiry"], row["original"]),
    )
    workbook = Workbook()
    all_sheet = workbook.active
    all_sheet.title = "Műszaki garancia"
    _write_table(all_sheet, "Műszaki cikk / szerszám – 3 éves garancia", rows)

    active_sheet = workbook.create_sheet("Aktív garanciák")
    _write_table(active_sheet, "Aktív 3 éves garanciák (lejárat szerint)", active_rows)

    summary_sheet = workbook.create_sheet("Összesítő")
    _write_summary(summary_sheet, rows, active_rows)

    methodology_sheet = workbook.create_sheet("Módszertan")
    _write_methodology(methodology_sheet)

    try:
        workbook.save(path)
        return path
    except PermissionError:
        alternative = path.with_name(
            f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"
        )
        workbook.save(alternative)
        return alternative
