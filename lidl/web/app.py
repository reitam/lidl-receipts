"""Webes felület a Lidl Plus e-nyugta archívumhoz (FastAPI)."""

from __future__ import annotations

import math
import re
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, config
from ..auth import AuthError, TokenStore, refresh_access_token
from ..jobs import ACTIONS, JobManager
from ..notify import send as send_notify
from ..receipt import receipt_datetime, receipt_total
from ..receipt import store_name as receipt_store_name
from ..scheduler import Scheduler, next_run_at
from .data import ReceiptStore, format_amount
from .loginflow import LoginFlowStore
from .security import SESSION_COOKIE, Auth

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

PER_PAGE = 50
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _safe_next(value: str | None) -> str:
    target = str(value or "/")
    if not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


def _num(value: float) -> str:
    return f"{float(value or 0):,.0f}".replace(",", "\u00a0")


def _dt(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not value:
        return ""
    try:
        return value.strftime(fmt)
    except AttributeError:
        return str(value)


def create_app(
    store: ReceiptStore,
    manager: JobManager,
    auth: Auth,
    settings_loader=config.load_settings,
    flows: LoginFlowStore | None = None,
) -> FastAPI:
    app = FastAPI(title="Lidl Plus e-nyugták", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["ft"] = format_amount
    templates.env.filters["num"] = _num
    templates.env.filters["dt"] = _dt
    templates.env.filters["ts"] = lambda value: (
        datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M") if value else ""
    )

    if flows is None:
        flows = LoginFlowStore(TokenStore(config.token_path(store.country)))

    def context(request: Request, **extra) -> dict:
        settings = settings_loader()
        base = {
            "request": request,
            "version": __version__,
            "auth_enabled": auth.enabled,
            "csrf": auth.csrf,
            "settings": settings,
            "country": store.country,
            "data_dir": store.data_dir,
            "output_dir": store.output_dir,
            "token_exists": store.token_exists(),
            "current_job": manager.current(),
            "next_run": next_run_at(settings),
            "active": "",
            "msg": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", ""),
        }
        base.update(extra)
        return base

    def page(request: Request, name: str, status_code: int = 200, **extra) -> HTMLResponse:
        return templates.TemplateResponse(
            request, name, context(request, **extra), status_code=status_code
        )

    def flash(path: str, msg: str, kind: str = "ok", **params) -> RedirectResponse:
        query = {"msg": msg, "kind": kind}
        query.update({key: value for key, value in params.items() if value not in (None, "")})
        separator = "&" if "?" in path else "?"
        return RedirectResponse(f"{path}{separator}{urllib.parse.urlencode(query)}", status_code=303)

    def csrf_failed(request: Request) -> HTMLResponse:
        return page(
            request,
            "error.html",
            status_code=403,
            title="Érvénytelen kérés",
            message="A biztonsági token nem egyezik. Töltsd újra az oldalt, és próbáld újra.",
        )

    # -- auth ----------------------------------------------------------
    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        path = request.url.path
        public = (
            path.startswith("/static/")
            or path in ("/health", "/login", "/favicon.ico")
        )
        if public or not auth.enabled:
            return await call_next(request)
        if auth.valid(request.cookies.get(SESSION_COOKIE)):
            return await call_next(request)
        if path.endswith(".json") or path.startswith("/api/"):
            return JSONResponse({"error": "Bejelentkezés szükséges."}, status_code=401)
        target = _safe_next(request.url.path)
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(
            f"/login?next={urllib.parse.quote(target, safe='')}", status_code=303
        )

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/"):
        if not auth.enabled:
            return RedirectResponse("/", status_code=303)
        return page(request, "login.html", next=_safe_next(next), active="login")

    @app.post("/login")
    def login_submit(
        request: Request,
        password: str = Form(""),
        next: str = Form("/"),
        csrf: str = Form(""),
    ):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        token = auth.login(password)
        if not token:
            return page(
                request,
                "login.html",
                status_code=401,
                next=_safe_next(next),
                active="login",
                error="Hibás jelszó.",
            )
        response = RedirectResponse(_safe_next(next), status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=7 * 24 * 3600,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form("")):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        auth.logout(request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    # -- Lidl bejelentkezés (PKCE beillesztéssel) ----------------------
    @app.get("/auth", response_class=HTMLResponse)
    def auth_page(request: Request):
        return page(
            request,
            "auth.html",
            flow=flows.current(),
            token_exists=store.token_exists(),
            active="auth",
        )

    @app.post("/auth/start")
    def auth_start(request: Request, csrf: str = Form("")):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        settings = settings_loader()
        flows.start(
            str(settings.get("country") or store.country),
            str(settings.get("language") or "hu"),
        )
        return RedirectResponse("/auth", status_code=303)

    @app.post("/auth/finish", response_class=HTMLResponse)
    def auth_finish(request: Request, pasted: str = Form(""), csrf: str = Form("")):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        try:
            flows.finish(pasted)
        except AuthError as exc:
            return page(
                request,
                "auth.html",
                status_code=400,
                flow=flows.current(),
                token_exists=store.token_exists(),
                active="auth",
                error=str(exc),
                pasted=pasted,
            )
        return flash("/", "Sikeres bejelentkezés, a token elmentve.")

    @app.post("/auth/cancel")
    def auth_cancel(request: Request, csrf: str = Form("")):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        flows.cancel()
        return RedirectResponse("/auth", status_code=303)

    @app.post("/auth/check")
    def auth_check(request: Request, csrf: str = Form("")):
        """A refresh token kipróbálása; siker esetén azonnal menti az újat."""
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        token_store = TokenStore(store.data_dir / f"token_{store.country}.json")
        token = token_store.load()
        if token is None:
            return flash("/auth", "Nincs mentett token – jelentkezz be.", "err")
        try:
            token = refresh_access_token(token)
            token_store.save(token)
        except AuthError as exc:
            return flash("/auth", f"A token nem használható: {exc}", "err")
        return flash("/auth", "A token érvényes, sikeresen frissítve.")

    # -- áttekintés ----------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, job: str = ""):
        stats = store.stats()
        recent = []
        for receipt in store.receipts[:6]:
            recent.append(
                {
                    "receipt": receipt,
                    "moment": receipt_datetime(receipt),
                    "total": receipt_total(receipt),
                    "store": receipt_store_name(receipt),
                    "pdf": store.pdf_path(receipt),
                    "item_count": len(store.items(receipt)),
                }
            )
        job_obj = manager.current() or (manager.get(job) if job else None)
        history = manager.history(1)
        return page(
            request,
            "dashboard.html",
            active="dashboard",
            stats=stats,
            recent=recent,
            job=job_obj,
            last_job=history[0] if history else None,
            actions=ACTIONS,
            now=datetime.now(),
        )

    # -- nyugták -------------------------------------------------------
    @app.get("/receipts", response_class=HTMLResponse)
    def receipts_page(
        request: Request,
        q: str = "",
        year: str = "",
        store_filter: str = Query("", alias="store"),
        page_no: str = "1",
    ):
        year_value = int(year) if str(year).isdigit() else None
        results = store.search(q, year_value, store_filter)
        total = len(results)
        pages = max(1, math.ceil(total / PER_PAGE))
        try:
            current = min(max(1, int(page_no)), pages)
        except (TypeError, ValueError):
            current = 1
        start = (current - 1) * PER_PAGE
        rows = []
        for receipt in results[start : start + PER_PAGE]:
            rows.append(
                {
                    "receipt": receipt,
                    "moment": receipt_datetime(receipt),
                    "total": receipt_total(receipt),
                    "store": receipt_store_name(receipt),
                    "item_count": len(store.items(receipt)),
                    "pdf": store.pdf_path(receipt),
                }
            )
        return page(
            request,
            "receipts.html",
            active="receipts",
            rows=rows,
            total=total,
            page=current,
            pages=pages,
            q=q,
            year=str(year_value or ""),
            store=store_filter,
            years=store.years(),
            stores=store.stores(),
        )

    @app.get("/receipts/{receipt_id}", response_class=HTMLResponse)
    def receipt_detail(request: Request, receipt_id: str):
        receipt = store.get(receipt_id)
        if receipt is None:
            return page(
                request,
                "error.html",
                status_code=404,
                title="Nincs ilyen nyugta",
                message=f"A(z) {receipt_id} azonosító nem található az archívumban.",
            )
        items = store.items(receipt)
        return page(
            request,
            "receipt.html",
            active="receipts",
            receipt=receipt,
            moment=receipt_datetime(receipt),
            total=receipt_total(receipt),
            store=receipt_store_name(receipt),
            items=items,
            pdf=store.pdf_path(receipt),
            jpg=store.jpg_path(receipt),
        )

    def _receipt_file(receipt_id: str, suffix: str):
        receipt = store.get(receipt_id)
        if receipt is None:
            return None
        path = store.pdf_path(receipt)
        if suffix == ".jpg":
            path = path.with_suffix(".jpg")
        return path if path.is_file() else None

    @app.get("/receipts/{receipt_id}/pdf")
    def receipt_pdf(receipt_id: str):
        path = _receipt_file(receipt_id, ".pdf")
        if path is None:
            return JSONResponse({"error": "A PDF még nem készült el."}, status_code=404)
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @app.get("/receipts/{receipt_id}/jpg")
    def receipt_jpg(receipt_id: str):
        path = _receipt_file(receipt_id, ".jpg")
        if path is None:
            return JSONResponse({"error": "A JPG még nem készült el."}, status_code=404)
        return FileResponse(path, media_type="image/jpeg", filename=path.name)

    @app.get("/receipts/{receipt_id}/json")
    def receipt_json(receipt_id: str):
        receipt = store.get(receipt_id)
        if receipt is None:
            return JSONResponse({"error": "Nincs ilyen nyugta."}, status_code=404)
        path = store.data_dir / "receipts" / store.country / f"{receipt_id}.json"
        if not path.is_file():
            return JSONResponse({"error": "A nyers JSON nem található."}, status_code=404)
        return FileResponse(path, media_type="application/json", filename=path.name)

    @app.get("/receipts/{receipt_id}/preview", response_class=HTMLResponse)
    def receipt_preview(receipt_id: str):
        receipt = store.get(receipt_id)
        if receipt is None:
            return HTMLResponse("<p>Nincs ilyen nyugta.</p>", status_code=404)
        return HTMLResponse(store.preview_html(receipt))

    # -- kimutatások ---------------------------------------------------
    @app.get("/reports", response_class=HTMLResponse)
    def reports_page(request: Request):
        warranty = store.warranty_rows()
        active = [row for row in warranty if row["status"] == "Aktív"]
        files = store.report_paths()
        return page(
            request,
            "reports.html",
            active="reports",
            warranty_total=len(warranty),
            warranty_active=len(active),
            warranty_value=sum(row["price"] for row in active),
            warranty_expired=len(warranty) - len(active),
            files={key: path.is_file() for key, path in files.items()},
            stats=store.stats(),
        )

    @app.get("/reports/warranty", response_class=HTMLResponse)
    def warranty_page(request: Request, status: str = "active", q: str = ""):
        rows = store.warranty_rows()
        needle = q.strip().casefold()
        filtered = []
        for row in rows:
            if status == "active" and row["status"] != "Aktív":
                continue
            if status == "expired" and row["status"] == "Aktív":
                continue
            if needle:
                haystack = " ".join(
                    str(row.get(key) or "")
                    for key in ("original", "interpretation", "article_id", "store", "category")
                ).casefold()
                if needle not in haystack:
                    continue
            filtered.append(row)
        return page(
            request,
            "warranty.html",
            active="reports",
            rows=filtered,
            total=len(rows),
            active_count=sum(1 for row in rows if row["status"] == "Aktív"),
            status=status if status in ("active", "expired", "all") else "all",
            q=q,
        )

    # -- fájlletöltések ------------------------------------------------
    @app.get("/files/{kind}")
    def download(kind: str, request: Request):
        files = store.report_paths()
        if kind not in files:
            return JSONResponse({"error": "Ismeretlen fájl."}, status_code=404)
        path = files[kind]
        if not path.is_file():
            return JSONResponse({"error": "A fájl még nem készült el."}, status_code=404)
        media = "application/pdf" if path.suffix == ".pdf" else None
        return FileResponse(path, media_type=media, filename=path.name)

    # -- feladatok -----------------------------------------------------
    @app.post("/jobs/start")
    def job_start(
        request: Request,
        action: str = Form(""),
        csrf: str = Form(""),
    ):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        job, error = manager.start(action, source="manual")
        if job is None:
            return flash("/", error or "Nem sikerült elindítani.", "err")
        return flash("/", f"Elindult: {job.label}.", "ok", job=job.id)

    @app.post("/jobs/{job_id}/stop")
    def job_stop(request: Request, job_id: str, csrf: str = Form("")):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        if not manager.stop(job_id):
            return flash("/", "Ez a feladat már nem fut.", "err")
        return flash("/", "Leállítás kérve.", "ok", job=job_id)

    @app.get("/jobs/{job_id}.json")
    def job_state(job_id: str):
        job = manager.get(job_id)
        if job is None:
            return JSONResponse({"error": "Nincs ilyen feladat."}, status_code=404)
        return JSONResponse(job.to_dict())

    @app.get("/jobs/{job_id}/log", response_class=PlainTextResponse)
    def job_log(job_id: str):
        job = manager.get(job_id)
        if job is None:
            return PlainTextResponse("Nincs ilyen feladat.", status_code=404)
        return PlainTextResponse(manager.log_text(job))

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs_page(request: Request):
        return page(
            request,
            "jobs.html",
            active="jobs",
            jobs=manager.history(40),
            actions=ACTIONS,
        )

    # -- beállítások ---------------------------------------------------
    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        return page(
            request,
            "settings.html",
            active="settings",
            cfg=settings_loader(),
            weekdays=config.WEEKDAY_NAMES,
            password_set=auth.enabled,
        )

    @app.post("/settings/schedule")
    def settings_schedule(
        request: Request,
        csrf: str = Form(""),
        schedule_enabled: str = Form(""),
        schedule_time: str = Form("19:00"),
        weekday: list[str] = Form(default=[]),
    ):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        if not TIME_RE.match(schedule_time.strip()):
            return flash("/settings", "Hibás időpont (ÓÓ:PP formátum kell).", "err")
        days = sorted(
            {int(value) for value in weekday if str(value).isdigit() and 0 <= int(value) <= 6}
        )
        settings = settings_loader()
        settings["schedule"] = {
            "enabled": schedule_enabled == "1",
            "time": schedule_time.strip(),
            "weekdays": days or [0, 1, 2, 3, 4, 5, 6],
        }
        config.save_settings(settings)
        return flash("/settings", "Az ütemezés mentve.")

    @app.post("/settings/ntfy")
    def settings_ntfy(
        request: Request,
        csrf: str = Form(""),
        ntfy_enabled: str = Form(""),
        ntfy_url: str = Form(""),
        ntfy_topic: str = Form(""),
        ntfy_token: str = Form(""),
        ntfy_on_manual: str = Form(""),
    ):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        settings = settings_loader()
        settings["ntfy"] = {
            "enabled": ntfy_enabled == "1",
            "url": ntfy_url.strip(),
            "topic": ntfy_topic.strip() or "lidl",
            "token": ntfy_token.strip(),
            "on_manual": ntfy_on_manual == "1",
        }
        config.save_settings(settings)
        return flash("/settings", "Az értesítés beállításai mentve.")

    @app.post("/settings/test-ntfy")
    def settings_test_ntfy(request: Request, csrf: str = Form("")):
        if not auth.csrf_ok(csrf):
            return csrf_failed(request)
        settings = settings_loader()
        ok = send_notify(
            settings,
            "Lidl: teszt",
            "Ez egy tesztértesítés a Lidl e-nyugta felületről.",
            tags=["white_check_mark"],
        )
        if ok:
            return flash("/settings", "A tesztértesítés elküldve.")
        return flash(
            "/settings",
            "Nem sikerült elküldeni (kapcsold be az ntfy-t, és ellenőrizd az URL-t/topicot).",
            "err",
        )

    # -- egyéb ---------------------------------------------------------
    @app.get("/health")
    def health():
        stats = store.stats()
        running = manager.current()
        history = manager.history(20)
        latest = running or (history[0] if history else None)
        last_success = next(
            (job.finished_iso for job in history if job.status == "done"), ""
        )
        return {
            "status": "ok",
            "version": __version__,
            "country": store.country,
            "token": stats["token"],
            "receipts": stats["receipts"],
            "pdfs": stats["pdfs"],
            "last_job": latest.to_dict(False) if latest else None,
            "last_success": last_success,
        }

    @app.get("/favicon.ico")
    def favicon():
        return PlainTextResponse("", status_code=204)

    return app


def _make_notifier(store: ReceiptStore, settings_loader):
    def notify(job) -> None:
        settings = settings_loader()
        cfg = settings.get("ntfy") or {}
        if not cfg.get("enabled"):
            return
        if job.status == "stopped":
            return
        is_error = job.status == "error"
        if job.source != "schedule" and not is_error and not cfg.get("on_manual"):
            return

        if is_error:
            token_markers = (
                "A Lidl elutasította a tokent",
                "Nincs mentett bejelentkezés",
                "refresh token",
                "HTTP 401",
            )
            token_problem = any(marker in job.output for marker in token_markers)
            if token_problem:
                title = "Lidl: bejelentkezés szükséges"
                message = (
                    "A token lejárt vagy visszavonták. Nyisd meg a felületet, "
                    "majd: Lidl fiók → Bejelentkezés indítása."
                )
                tags = ["key"]
            else:
                title = "Lidl: hiba a frissítésben"
                message = f"{job.label}: {job.status}. Nézd meg a naplót a felületen."
                tags = ["warning"]
            priority = "high"
        else:
            count, total = store.new_receipts_since(job.started_at)
            title = "Lidl: frissítés kész"
            parts = [f"{job.label}: kész ({job.duration})."]
            if count:
                parts.append(f"{count} új nyugta, {format_amount(total)}.")
            else:
                parts.append("Nincs új nyugta.")
            message = " ".join(parts)
            tags = ["shopping_cart"]
            priority = "default"
        send_notify(settings, title, message, tags=tags, priority=priority)

    return notify


def run_server(
    host: str = "0.0.0.0",
    port: int = 8101,
    open_browser: bool = False,
) -> None:
    import uvicorn

    config.ensure_dirs()
    settings = config.load_settings()
    store = ReceiptStore(
        config.DATA_DIR,
        config.OUTPUT_DIR,
        country=str(settings.get("country") or config.COUNTRY),
        language=str(settings.get("language") or config.LANGUAGE),
    )
    manager = JobManager(
        config.DATA_DIR,
        config.OUTPUT_DIR,
        settings_loader=config.load_settings,
        on_finish=None,
    )
    manager.on_finish = _make_notifier(store, config.load_settings)
    auth = Auth(config.UI_PASSWORD)
    flows = LoginFlowStore(TokenStore(config.token_path(store.country)))
    app = create_app(store, manager, auth, config.load_settings, flows)
    scheduler = Scheduler(manager, config.load_settings)
    scheduler.start()

    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print(f"Lidl web: {url}")
    print(f"Adatok:   {config.DATA_DIR}")
    print(f"Kimenet:  {config.OUTPUT_DIR}")
    if auth.enabled:
        print("A felület jelszóval védett (LIDL_UI_PASSWORD).")
    if open_browser:
        import threading

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        scheduler.stop()
