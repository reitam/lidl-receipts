"""Ideiglenes Windows protokoll-kezelő a com.lidlplus.app:// sémára.

A login idejére regisztráljuk, hogy a böngésző által megnyitott
com.lidlplus.app://callback?... URL-t egy kis szkript elmentse. A login
végén automatikusan eltávolítjuk.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCHEME = "com.lidlplus.app"


def _winreg():
    try:
        import winreg
    except ImportError as exc:  # nem Windows
        raise RuntimeError("A protokoll-kezelő csak Windowson működik.") from exc
    return winreg


def _pythonw() -> str:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return str(candidate if candidate.is_file() else executable)


def capture_script() -> Path:
    return Path(__file__).resolve().parent / "capture_callback.py"


def _key_path() -> str:
    return rf"Software\Classes\{SCHEME}"


def register(callback_file: Path) -> None:
    """Regisztrálja a com.lidlplus.app:// kezelőt az aktuális felhasználónak."""
    winreg = _winreg()
    command = (
        f'"{_pythonw()}" "{capture_script()}" '
        f'"{Path(callback_file).resolve()}" "%1"'
    )
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _key_path()) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{SCHEME}")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(key, r"shell\open\command") as command_key:
            winreg.SetValueEx(command_key, "", 0, winreg.REG_SZ, command)


def _delete_tree(winreg, root, path: str) -> None:
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    subkey = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree(winreg, root, f"{path}\\{subkey}")
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def unregister() -> None:
    """Eltávolítja a kezelőt (ha létezik)."""
    try:
        winreg = _winreg()
    except RuntimeError:
        return
    _delete_tree(winreg, winreg.HKEY_CURRENT_USER, _key_path())


def is_registered() -> bool:
    try:
        winreg = _winreg()
    except RuntimeError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _key_path()):
            return True
    except FileNotFoundError:
        return False
