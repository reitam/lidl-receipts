"""Kompatibilitási réteg: a régi helyi dashboard helyén a webes felület fut.

A ``python -m lidl dashboard`` és a ``start_lidl.bat`` változatlanul
működik, csak már az új FastAPI-s felületet indítja 127.0.0.1-en.
"""

from __future__ import annotations


def run_server(port: int = 8765, open_browser: bool = True) -> None:
    from .web.app import run_server as web_run

    web_run(host="127.0.0.1", port=port, open_browser=open_browser)


def create_server(*_args, **_kwargs):
    raise RuntimeError(
        "A régi dashboard szerver megszűnt. Indítsd: python -m lidl serve "
        "(--host 0.0.0.0 --port 8765) vagy python -m lidl dashboard"
    )
