"""Parancssori felület: python -m lidl <parancs>."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import config
from .api import ApiError, LidlClient, fetch_all
from .auth import AuthError, TokenStore, login_capture, login_manual
from .export import export_index
from .receipt import enrich_receipts, receipt_datetime, receipt_total
from .render import render_receipts
from .warranty import build_warranty_rows, export_warranty_excel
try:  # a borkimutatás opcionális (a publikus buildből kimarad)
    from .wine import build_wine_rows, export_wine_excel, monthly_summary

    WINE_AVAILABLE = True
except ImportError:  # pragma: no cover
    build_wine_rows = export_wine_excel = monthly_summary = None
    WINE_AVAILABLE = False

ROOT = config.ROOT
DATA_DIR = config.DATA_DIR
OUTPUT_DIR = config.OUTPUT_DIR

DEFAULT_COUNTRY = config.COUNTRY
DEFAULT_LANGUAGE = config.LANGUAGE


def token_store(country: str) -> TokenStore:
    return TokenStore(DATA_DIR / f"token_{country.upper()}.json")


def receipts_dir(country: str) -> Path:
    return DATA_DIR / "receipts" / country.upper()


def load_receipts(country: str) -> list[dict]:
    path = receipts_dir(country)
    receipts: list[dict] = []
    for file in sorted(path.glob("*.json")):
        try:
            receipts.append(json.loads(file.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            print(f"Figyelem: kihagytam egy olvashatatlan fájlt ({file.name}): {exc}")
    receipts.sort(key=lambda item: receipt_datetime(item) or datetime.min, reverse=True)
    return enrich_receipts(receipts)


def require_login(country: str) -> None:
    if not token_store(country).exists():
        raise AuthError(
            "Nincs mentett bejelentkezés. Először futtasd: python -m lidl login"
        )


def cmd_login(args: argparse.Namespace) -> int:
    store = token_store(args.country)
    if store.exists() and not args.force:
        print(f"Már van mentett bejelentkezés: {store.path}")
        print("Új tokenhez futtasd: python -m lidl login --force")
        return 0
    if args.manual:
        login_manual(
            store,
            country=args.country,
            language=args.language,
            incognito=args.incognito,
            open_browser_window=not args.no_browser,
        )
    else:
        if args.no_browser:
            mode = "no-browser"
        elif args.clean:
            mode = "clean"
        elif args.incognito:
            mode = "incognito"
        else:
            mode = "default"
        login_capture(
            store,
            country=args.country,
            language=args.language,
            mode=mode,
            timeout=args.timeout,
        )
    return 0


def _fetch_once(args: argparse.Namespace) -> dict:
    require_login(args.country)
    client = LidlClient(token_store(args.country))
    return fetch_all(
        client,
        receipts_dir(args.country),
        force=args.full,
        limit=args.limit,
        delay=args.delay,
    )


def cmd_fetch(args: argparse.Namespace) -> int:
    try:
        stats = _fetch_once(args)
    except AuthError as exc:
        if getattr(args, "no_auto_login", False):
            raise
        print(f"\nA token nem használható ({exc}). Bejelentkezés következik...")
        login_capture(
            token_store(args.country),
            country=args.country,
            language=args.language,
        )
        stats = _fetch_once(args)
    print()
    print(f"Nyugták az API szerint: {stats['total']}")
    print(f"Újonnan letöltve:      {stats['downloaded']}")
    print(f"Kihagyva (már megvolt): {stats['skipped']}")
    if stats["errors"]:
        print(f"Hibás nyugták:         {len(stats['errors'])}")
        for ticket_id, error in stats["errors"][:10]:
            print(f"  - {ticket_id}: {error}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    receipts = load_receipts(args.country)
    if not receipts:
        print("Nincs letöltött nyugta. Futtasd előbb: python -m lidl fetch")
        return 1
    if args.limit:
        receipts = receipts[: args.limit]
    formats: tuple[str, ...]
    if args.format == "both":
        formats = ("pdf", "jpg")
    else:
        formats = (args.format,)
    stats = render_receipts(
        receipts,
        OUTPUT_DIR,
        formats=formats,
        force=args.force,
        logo_cache_dir=DATA_DIR,
        quality=args.quality,
    )
    print()
    print(f"Renderelve: {stats['done']}, kihagyva: {stats['skipped']}, hiba: {len(stats['errors'])}")
    for receipt_id, error in stats["errors"][:10]:
        print(f"  - {receipt_id}: {error}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    receipts = load_receipts(args.country)
    if not receipts:
        print("Nincs letöltött nyugta. Futtasd előbb: python -m lidl fetch")
        return 1
    paths = export_index(receipts, OUTPUT_DIR, OUTPUT_DIR, country=args.country.upper())
    print("Jegyzék elkészült:")
    for path in paths.values():
        print(f"  {path}")
    return 0


def cmd_warranty(args: argparse.Namespace) -> int:
    receipts = load_receipts(args.country)
    if not receipts:
        print("Nincs letöltött nyugta. Futtasd előbb: python -m lidl fetch")
        return 1
    rows = build_warranty_rows(receipts, OUTPUT_DIR)
    output = getattr(args, "output", None) or (
        OUTPUT_DIR / f"muszaki_garancia_{args.country.upper()}.xlsx"
    )
    requested = Path(output)
    path = export_warranty_excel(rows, requested)
    active = sum(1 for row in rows if row["status"] == "Aktív")
    print("Műszaki garancia kimutatás elkészült:")
    print(f"  {path}")
    if path != requested:
        print("  FIGYELEM: a fő Excel zárolva volt (valószínűleg nyitva van")
        print("           Excelben), ezért időbélyeges néven mentettem.")
    print(f"  Összes érintett tétel: {len(rows)}")
    print(f"  Aktív garancia:        {active}")
    print(f"  Lejárt garancia:       {len(rows) - active}")
    return 0


def cmd_wine(args: argparse.Namespace) -> int:
    if not WINE_AVAILABLE:
        print("A borkimutatás ebben a buildben nem elérhető.")
        return 1
    receipts = load_receipts(args.country)
    if not receipts:
        print("Nincs letöltött nyugta. Futtasd előbb: python -m lidl fetch")
        return 1
    rows = build_wine_rows(receipts, args.year, OUTPUT_DIR)
    summary = monthly_summary(rows, args.year)
    output = getattr(args, "output", None) or (
        OUTPUT_DIR / f"bor_kimutatas_{args.year}.xlsx"
    )
    requested = Path(output)
    path = export_wine_excel(rows, args.year, requested)
    print(f"Borvásárlások {args.year} – havi bontás:")
    print(f"  {'Hónap':<9} {'Tételek':>8} {'Palack':>8} {'Összeg':>12}")
    for row in summary:
        print(
            f"  {row['month']:<9} {row['items']:>8} "
            f"{row['bottles']:>8g} {row['total']:>10,.0f} Ft".replace(",", " ")
        )
    total = sum(row["total"] for row in summary)
    bottles = sum(row["bottles"] for row in summary)
    print(f"  {'Összesen':<9} {sum(r['items'] for r in summary):>8} "
          f"{bottles:>8g} {total:>10,.0f} Ft".replace(",", " "))
    print(f"\nExcel: {path}")
    if path != requested:
        print("FIGYELEM: a fő Excel zárolva volt; időbélyeges néven mentettem.")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    require_login(args.country)
    fetch_code = cmd_fetch(args)
    if fetch_code:
        return fetch_code
    render_code = cmd_render(args)
    if render_code:
        return render_code
    export_code = cmd_export(args)
    if export_code:
        return export_code
    return cmd_warranty(args)


def cmd_status(args: argparse.Namespace) -> int:
    store = token_store(args.country)
    print(f"Bejelentkezés: {'van' if store.exists() else 'NINCS'} ({store.path})")
    receipts = load_receipts(args.country)
    print(f"Letöltött nyugták: {len(receipts)}")
    if receipts:
        dated = [item for item in receipts if receipt_datetime(item)]
        if dated:
            oldest = min(dated, key=receipt_datetime)
            newest = max(dated, key=receipt_datetime)
            print(f"Időszak: {receipt_datetime(oldest):%Y-%m-%d} – {receipt_datetime(newest):%Y-%m-%d}")
        total = sum(receipt_total(item) for item in receipts)
        print(f"Összeg: {total:,.0f} Ft".replace(",", " "))
    pdfs = list(OUTPUT_DIR.glob("*/*.pdf"))
    print(f"PDF fájlok: {len(pdfs)}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """A régi helyi vezérlőpult helyén is a webes felület indul."""
    from .web.app import run_server

    run_server(host="127.0.0.1", port=args.port, open_browser=not args.no_open)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .web.app import run_server

    run_server(host=args.host, port=args.port, open_browser=args.open)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lidl",
        description="Lidl Plus elektronikus nyugták letöltése (nem hivatalos eszköz).",
    )
    parser.add_argument("--country", default=DEFAULT_COUNTRY, help="Országkód (alap: HU)")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE, help="Nyelvkód (alap: hu)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Bejelentkezés (automatikus callback-elfogással)")
    login.add_argument("--force", action="store_true", help="Új token kérése akkor is, ha van mentett")
    login.add_argument(
        "--manual",
        action="store_true",
        help="Kézi callback URL beillesztése (ha az automatikus elfogás nem működik)",
    )
    login.add_argument(
        "--clean",
        action="store_true",
        help="Friss, ideiglenes Chrome/Edge profil használata",
    )
    login.add_argument(
        "--incognito",
        action="store_true",
        help="Inkognitó ablak használata (friss profillal)",
    )
    login.add_argument(
        "--no-browser",
        action="store_true",
        help="Ne nyisson böngészőt; az URL-t a saját böngésződben nyisd meg",
    )
    login.add_argument(
        "--timeout",
        type=float,
        default=600,
        help="Várakozás a callbackre másodpercben (alap: 600)",
    )
    login.set_defaults(func=cmd_login)

    fetch = subparsers.add_parser("fetch", help="Nyugták letöltése")
    fetch.add_argument("--full", action="store_true", help="Minden nyugtát újra letölt")
    fetch.add_argument("--limit", type=int, default=None, help="Csak az első N nyugta (teszthez)")
    fetch.add_argument("--delay", type=float, default=0.25, help="Késleltetés nyugtánként mp-ben")
    fetch.add_argument(
        "--no-auto-login",
        action="store_true",
        help="Lejárt token esetén ne indítson automatikus bejelentkezést",
    )
    fetch.set_defaults(func=cmd_fetch)

    render = subparsers.add_parser("render", help="Nyugták renderelése PDF/JPG fájlokká")
    render.add_argument("--format", choices=["pdf", "jpg", "both"], default="pdf")
    render.add_argument("--force", action="store_true", help="Meglévő fájlok felülírása")
    render.add_argument("--quality", type=int, default=90, help="JPG minőség (1-100)")
    render.add_argument("--limit", type=int, default=None, help="Csak az első N nyugta")
    render.set_defaults(func=cmd_render)

    export = subparsers.add_parser("export", help="CSV/Excel jegyzék készítése")
    export.set_defaults(func=cmd_export)

    warranty = subparsers.add_parser(
        "warranty", help="Műszaki cikk / szerszám 3 éves garancia Excel"
    )
    warranty.add_argument(
        "--output",
        type=Path,
        default=None,
        help="A kimeneti Excel útvonala (alap: nyugtak/muszaki_garancia_HU.xlsx)",
    )
    warranty.set_defaults(func=cmd_warranty)

    if WINE_AVAILABLE:
        wine = subparsers.add_parser(
            "wine", help="Borvásárlások éves/havi kimutatása Excelben"
        )
        wine.add_argument(
            "--year",
            type=int,
            default=datetime.now().year,
            help="A kimutatás éve (alap: aktuális év)",
        )
        wine.add_argument(
            "--output",
            type=Path,
            default=None,
            help="A kimeneti Excel útvonala (alap: nyugtak/bor_kimutatas_<év>.xlsx)",
        )
        wine.set_defaults(func=cmd_wine)

    all_cmd = subparsers.add_parser(
        "all", help="Letöltés + renderelés + jegyzék + garancia kimutatás"
    )
    all_cmd.add_argument("--full", action="store_true", help="Minden nyugtát újra letölt")
    all_cmd.add_argument("--format", choices=["pdf", "jpg", "both"], default="pdf")
    all_cmd.add_argument("--force", action="store_true", help="Meglévő fájlok felülírása")
    all_cmd.add_argument("--quality", type=int, default=90)
    all_cmd.add_argument("--limit", type=int, default=None)
    all_cmd.add_argument("--delay", type=float, default=0.25)
    all_cmd.add_argument(
        "--no-auto-login",
        action="store_true",
        help="Lejárt token esetén ne indítson automatikus bejelentkezést",
    )
    all_cmd.set_defaults(func=cmd_all)

    status = subparsers.add_parser("status", help="Állapot összefoglaló")
    status.set_defaults(func=cmd_status)

    dashboard = subparsers.add_parser(
        "dashboard", help="Helyi böngészős vezérlőpult indítása (127.0.0.1)"
    )
    dashboard.add_argument("--port", type=int, default=8765, help="A helyi szerver portja")
    dashboard.add_argument(
        "--no-open",
        action="store_true",
        help="Ne nyissa meg automatikusan a böngészőt",
    )
    dashboard.set_defaults(func=cmd_dashboard)

    serve = subparsers.add_parser(
        "serve", help="Webes felület indítása (konténerben: 0.0.0.0)"
    )
    serve.add_argument(
        "--host", default=os.environ.get("LIDL_HOST", "0.0.0.0"), help="Figyelő cím"
    )
    serve.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LIDL_PORT", "8765")),
        help="Port (alap: 8765)",
    )
    serve.add_argument("--open", action="store_true", help="Böngésző megnyitása induláskor")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config.ensure_dirs()
        return int(args.func(args) or 0)
    except (AuthError, ApiError) as exc:
        print(f"\nHiba: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nMegszakítva.", file=sys.stderr)
        return 130
