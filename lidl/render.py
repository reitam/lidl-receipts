"""Nyugták renderelése PDF-be (vagy JPG-be) a Lidl által adott nyomtatott HTML-ből."""

from __future__ import annotations

import base64
import io
import re
from datetime import datetime
from pathlib import Path

import requests

from .receipt import (
    parse_items,
    receipt_currency,
    receipt_datetime,
    receipt_stem,
    receipt_total,
    store_name,
)

PAGE_CSS = """
html, body { margin: 0; padding: 0; background: #ffffff; }
body {
  width: 300px;
  padding: 14px 12px 18px;
  font-family: "Courier New", "Consolas", monospace;
  color: #111;
}
.copy-label {
  text-align: center;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.4px;
  margin: 0 0 14px;
}
.logo { display: block; margin: 0 auto 12px; max-width: 150px; height: auto; }
.receipt { font-family: inherit; font-size: 12.5px; line-height: 1.25; white-space: pre-wrap; }
.receipt pre { margin: 0; font-family: inherit; font-size: inherit; line-height: inherit; white-space: pre; }
.codes { margin-top: 12px; text-align: center; }
.codes img { display: block; margin: 8px auto; max-width: 100%; }
.code-label { font-family: inherit; font-size: 10px; color: #333; margin-top: 4px; word-break: break-all; }
.paper-footer {
  margin-top: 14px;
  text-align: center;
  font-weight: 700;
  font-size: 12.5px;
  line-height: 1.45;
}
.fallback { font-family: inherit; font-size: 13px; line-height: 1.45; }
.fallback h2 { font-size: 15px; margin: 0 0 8px; }
.fallback table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }
.fallback td, .fallback th { padding: 2px 0; text-align: left; vertical-align: top; }
.fallback .num { text-align: right; white-space: nowrap; }
"""


def _png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _qr_png(text: str, box_size: int = 3) -> bytes:
    import qrcode

    qr = qrcode.QRCode(box_size=box_size, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


_BARCODE_FORMATS = {
    "ITF": "itf",
    "CODE128": "code128",
    "CODE_128": "code128",
    "CODE39": "code39",
    "CODE_39": "code39",
    "EAN13": "ean13",
    "EAN_13": "ean13",
    "EAN8": "ean8",
    "EAN_8": "ean8",
    "UPCA": "upca",
    "UPC_A": "upca",
}


def _barcode_png(text: str, fmt: str) -> bytes | None:
    import barcode
    from barcode.writer import ImageWriter

    name = _BARCODE_FORMATS.get(fmt.upper()) or _BARCODE_FORMATS.get(
        fmt.upper().replace("_", "")
    )
    if not name:
        return None
    try:
        cls = barcode.get_barcode_class(name)
        instance = cls(text, writer=ImageWriter())
        buffer = io.BytesIO()
        instance.write(
            buffer,
            options={
                "write_text": False,
                "module_height": 6.0,
                "module_width": 0.22 if name in ("code128", "code39") else 0.18,
                "quiet_zone": 2.0,
            },
        )
        return buffer.getvalue()
    except Exception:
        return None


def _codes_html(codes: list[dict] | None) -> str:
    parts = ['<div class="codes">']
    for code in codes or []:
        if not isinstance(code, dict):
            continue
        fmt = str(code.get("format") or "").upper()
        text = str(code.get("code") or code.get("value") or "")
        if not text:
            continue
        if fmt in ("QR_CODE", "QRCODE", "QR"):
            png = _qr_png(text)
        else:
            png = _barcode_png(text, fmt)
        if not png:
            continue
        parts.append(f'<img src="{_png_data_url(png)}" alt="{fmt}"/>')
        label = code.get("label")
        if label and str(code.get("codeType") or "") != "Fiscal":
            parts.append(f'<div class="code-label">{_escape(str(label))}</div>')
    parts.append("</div>")
    return "".join(parts)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _body_fragment(document: str) -> str:
    match = re.search(r"<body[^>]*>(.*)</body>", document, re.S | re.I)
    if match:
        return match.group(1)
    # Nincs <body>: a dokumentumhéjat levágjuk, a tartalmat megtartjuk.
    cleaned = re.sub(r"(?is)<head\b.*?</head>", "", document)
    cleaned = re.sub(r"(?is)</?(?:html|body)\b[^>]*>", "", cleaned)
    return cleaned


def _document_styles(document: str) -> str:
    return "".join(re.findall(r"(?is)<style\b[^>]*>.*?</style>", document))


def _logo_data_url(logo_url: str, cache_dir: Path) -> str:
    if not logo_url:
        return ""
    if logo_url.startswith("data:"):
        return logo_url
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(logo_url.split("?")[0]).suffix or ".png"
    cache_path = cache_dir / f"lidl-logo{suffix}"
    if not cache_path.exists():
        try:
            response = requests.get(logo_url, timeout=20)
            response.raise_for_status()
            cache_path.write_bytes(response.content)
        except Exception:
            return ""
    mime = "image/png"
    if suffix.lower() in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif suffix.lower() == ".svg":
        mime = "image/svg+xml"
    return f"data:{mime};base64," + base64.b64encode(cache_path.read_bytes()).decode("ascii")


def _fallback_html(receipt: dict) -> str:
    moment = receipt_datetime(receipt)
    total = receipt_total(receipt)
    currency = receipt_currency(receipt)
    lines = [
        '<div class="fallback">',
        "<h2>Lidl Plus – elektronikus nyugta</h2>",
        f"<div><b>Dátum:</b> {_escape(moment.strftime('%Y-%m-%d %H:%M') if moment else 'ismeretlen')}</div>",
        f"<div><b>Bolt:</b> {_escape(store_name(receipt) or 'ismeretlen')}</div>",
        f"<div><b>Nyugta ID:</b> {_escape(str(receipt.get('id') or ''))}</div>",
        "<table><tr><th>Termék</th><th class='num'>Menny.</th><th class='num'>Egységár</th><th class='num'>Összeg</th></tr>",
    ]
    for item in parse_items(receipt):
        lines.append(
            "<tr>"
            f"<td>{_escape(item['name'])}</td>"
            f"<td class='num'>{item['quantity']:g}</td>"
            f"<td class='num'>{item['unit_price']:.2f}</td>"
            f"<td class='num'>{item['line_total']:.2f}</td>"
            "</tr>"
        )
    lines.append(
        f"<tr><th colspan='3'>Összesen</th><th class='num'>{total:.2f} {_escape(currency)}</th></tr>"
    )
    lines.append("</table></div>")
    return "".join(lines)


def build_page(
    receipt: dict,
    logo_cache_dir: Path | None = None,
    paper_copy: bool = True,
) -> str:
    document = receipt.get("htmlPrintedReceipt") or ""
    document_styles = _document_styles(document)
    if document.strip():
        content = _body_fragment(document)
    else:
        content = _fallback_html(receipt)

    copy_html = (
        '<div class="copy-label">BIZONYLAT MÁSOLAT</div>' if paper_copy else ""
    )

    logo_html = ""
    if logo_cache_dir is not None and not paper_copy:
        logo_url = str(receipt.get("logoUrl") or "")
        data_url = _logo_data_url(logo_url, logo_cache_dir)
        if data_url:
            logo_html = f'<img class="logo" src="{data_url}" alt="Lidl"/>'

    footer_html = (
        '<div class="paper-footer">'
        "!!! NEM ADÓÜGYI BIZONYLAT !!!<br>"
        "KÖSZÖNJÜK A VÁSÁRLÁST 😊"
        "</div>"
        if paper_copy
        else ""
    )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{PAGE_CSS}</style>{document_styles}</head><body>"
        f"{copy_html}{logo_html}<div class='receipt'>{content}</div>"
        f"{_codes_html(receipt.get('codes'))}{footer_html}"
        "</body></html>"
    )


def pdf_path_for(receipt: dict, output_root: Path) -> Path:
    moment = receipt_datetime(receipt)
    year = str(moment.year) if moment else "ismeretlen"
    return Path(output_root) / year / f"{receipt_stem(receipt)}.pdf"


def _launch_browser(playwright):
    errors: list[str] = []
    for options in (
        {"channel": "chrome"},
        {"channel": "msedge"},
        {},
    ):
        try:
            return playwright.chromium.launch(headless=True, **options)
        except Exception as exc:
            errors.append(f"{options or 'bundled chromium'}: {exc}")
    raise RuntimeError(
        "Nem sikerült elindítani a Chrome/Edge böngészőt a PDF-generáláshoz.\n"
        + "\n".join(errors)
    )


def render_receipts(
    receipts: list[dict],
    output_root: Path,
    formats: tuple[str, ...] = ("pdf",),
    force: bool = False,
    logo_cache_dir: Path | None = None,
    quality: int = 90,
    progress=None,
    paper_copy: bool = True,
) -> dict:
    """A megadott nyugtákat PDF/JPG fájlokká rendereli. Visszaadja a statisztikát."""
    from playwright.sync_api import sync_playwright

    say = progress or (lambda message: print(message))
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    todo: list[tuple[dict, list[tuple[str, Path]]]] = []
    skipped = 0
    for receipt in receipts:
        targets: list[tuple[str, Path]] = []
        for fmt in formats:
            path = pdf_path_for(receipt, output_root)
            if fmt == "jpg":
                path = path.with_suffix(".jpg")
            targets.append((fmt, path))
        if not force and all(path.exists() for _, path in targets):
            skipped += 1
            continue
        todo.append((receipt, targets))

    say(f"Renderelés: {len(todo)} nyugta (kihagyva: {skipped}).")
    done = 0
    errors: list[tuple[str, str]] = []

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        context = browser.new_context(
            viewport={"width": 324, "height": 100}, device_scale_factor=2
        )
        page = context.new_page()
        for index, (receipt, targets) in enumerate(todo, 1):
            receipt_id = str(receipt.get("id") or "")
            try:
                page.set_content(
                    build_page(
                        receipt,
                        logo_cache_dir=logo_cache_dir,
                        paper_copy=paper_copy,
                    ),
                    wait_until="load",
                    timeout=30000,
                )
                page.wait_for_timeout(120)
                for fmt, path in targets:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if fmt == "pdf":
                        height_px = page.evaluate(
                            "Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"
                        )
                        width_mm = 324 * 25.4 / 96
                        height_mm = max(60.0, float(height_px) * 25.4 / 96 + 2)
                        page.pdf(
                            path=str(path),
                            width=f"{width_mm:.2f}mm",
                            height=f"{height_mm:.2f}mm",
                            print_background=True,
                            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                        )
                    else:
                        page.screenshot(
                            path=str(path), full_page=True, type="jpeg", quality=quality
                        )
                done += 1
            except Exception as exc:
                errors.append((receipt_id, str(exc)))
            if index % 10 == 0 or index == len(todo):
                say(f"  {index}/{len(todo)} (kész: {done})")
        browser.close()

    return {"total": len(todo), "done": done, "skipped": skipped, "errors": errors}


def receipt_year(receipt: dict) -> str:
    moment: datetime | None = receipt_datetime(receipt)
    return str(moment.year) if moment else "ismeretlen"
