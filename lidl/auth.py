"""Lidl Plus bejelentkezés (OAuth2 authorization code + PKCE).

A Lidl Plus nem ad nyilvános API-t, ezért a hivatalos mobilapp
kommunikációját utánozzuk. A jelszó kizárólag a böngészőben, a Lidl saját
bejelentkező oldalán kerül felhasználásra; itt csak a visszakapott egyszeri
kódot váltjuk tokenre, és a refresh tokent tároljuk helyben.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .protocol import register as register_protocol, unregister as unregister_protocol

AUTH_BASE = "https://accounts.lidl.com"
CLIENT_ID = "LidlPlusNativeClient"
CLIENT_SECRET = "secret"
REDIRECT_URI = "com.lidlplus.app://callback"
SCOPES = "openid profile offline_access lpprofile lpapis"


class AuthError(RuntimeError):
    """Bejelentkezési / token hiba."""


@dataclass
class TokenData:
    refresh_token: str
    access_token: str = ""
    expires_at: float = 0.0
    country: str = "HU"
    language: str = "hu"
    device_id: str = field(default_factory=lambda: secrets.token_hex(8))

    @property
    def access_valid(self) -> bool:
        # 60 mp ráhagyás, hogy ne járjon le egy hosszabb letöltés közben.
        return bool(self.access_token) and time.time() < self.expires_at - 60


class TokenStore:
    """A refresh tokent egy helyi JSON fájlban tárolja."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> TokenData | None:
        if not self.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AuthError(f"A tokenfájl nem olvasható: {self.path} ({exc})") from exc
        token = raw.get("refresh_token", "")
        if not token:
            return None
        return TokenData(
            refresh_token=token,
            access_token=raw.get("access_token", ""),
            expires_at=float(raw.get("expires_at", 0) or 0),
            country=raw.get("country", "HU"),
            language=raw.get("language", "hu"),
            device_id=raw.get("device_id") or secrets.token_hex(8),
        )

    def save(self, data: TokenData) -> None:
        """Atomikus írás: előbb temp fájl, majd csere."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "refresh_token": data.refresh_token,
            "access_token": data.access_token,
            "expires_at": data.expires_at,
            "country": data.country,
            "language": data.language,
            "device_id": data.device_id,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_pkce_pair() -> tuple[str, str]:
    """Visszaadja a (code_verifier, code_challenge) párt (S256)."""
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_login_url(
    country: str,
    language: str,
    code_challenge: str,
    state: str | None = None,
    nonce: str | None = None,
) -> str:
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "Country": country.upper(),
        "language": f"{language.lower()}-{country.upper()}",
        "force": "false",
        "track": "false",
    }
    if state:
        params["state"] = state
    if nonce:
        params["nonce"] = nonce
    return f"{AUTH_BASE}/connect/authorize?{urllib.parse.urlencode(params)}"


def extract_code(text: str) -> str:
    """A visszairányított URL-ből (vagy önmagában beillesztett kódból) kinyeri a kódot."""
    text = text.strip().strip('"').strip("'")
    if not text:
        raise AuthError("Nem kaptam kódot.")
    match = re.search(r"[?&#]code=([^&\s]+)", text)
    if match:
        return urllib.parse.unquote(match.group(1))
    if re.fullmatch(r"[A-Za-z0-9._~-]{6,}", text):
        return text
    raise AuthError(
        "A beillesztett szövegben nem találtam 'code=' részt. "
        "A böngésző címsorából másold ki a teljes com.lidlplus.app://callback... URL-t."
    )


def extract_state(text: str) -> str | None:
    match = re.search(r"[?&#]state=([^&\s]+)", text)
    return urllib.parse.unquote(match.group(1)) if match else None


def _basic_auth_header() -> str:
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode("ascii")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _token_request(payload: dict[str, str], timeout: float = 60) -> dict:
    try:
        response = requests.post(
            f"{AUTH_BASE}/connect/token",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AuthError(f"Nem sikerült elérni a Lidl bejelentkező szerverét: {exc}") from exc

    if response.status_code in (400, 401):
        raise AuthError(
            "A Lidl elutasította a tokent (lejárt vagy visszavont refresh token, "
            f"vagy hibás visszairányítási kód). HTTP {response.status_code}: "
            f"{response.text[:200]} – futtasd újra: python -m lidl login --force"
        )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise AuthError(f"Token hiba (HTTP {response.status_code}): {response.text[:300]}") from exc
    return response.json()


def exchange_code(code: str, code_verifier: str, country: str, language: str) -> TokenData:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    data = _token_request(payload)
    return TokenData(
        refresh_token=data["refresh_token"],
        access_token=data.get("access_token", ""),
        expires_at=time.time() + float(data.get("expires_in", 3600)),
        country=country.upper(),
        language=language.lower(),
    )


def refresh_access_token(token: TokenData) -> TokenData:
    """Refresh token -> új access token. A refresh token minden hívásnál rotálódik."""
    data = _token_request(
        {"grant_type": "refresh_token", "refresh_token": token.refresh_token}
    )
    token.access_token = data.get("access_token", "")
    token.expires_at = time.time() + float(data.get("expires_in", 3600))
    # Rotáció: az új refresh tokent azonnal menteni kell, a régi már halott.
    token.refresh_token = data.get("refresh_token") or token.refresh_token
    return token


def _find_browser() -> tuple[str, str] | None:
    """Chrome vagy Edge telepítési útvonala."""
    candidates = [
        ("chrome", Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"),
        ("chrome", Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe"),
        ("chrome", Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"),
        ("edge", Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"),
        ("edge", Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe"),
    ]
    for name, path in candidates:
        if path.is_file():
            return name, str(path)
    for name, exe in (("chrome", "chrome.exe"), ("edge", "msedge.exe")):
        found = shutil.which(exe)
        if found:
            return name, found
    return None


def open_browser(url: str, incognito: bool = False) -> tuple[Path, subprocess.Popen] | None:
    """Megnyitja az URL-t egy friss Chrome/Edge ablakban.

    Külön ideiglenes profilt használ, így nem öröklődnek a régi cookie-k,
    bejelentkezések és kiterjesztések – ezért nem lesz üres az oldal.
    Alapból normál (nem inkognitó) ablakot nyit, mert az inkognitó blokkolhatja
    a reCAPTCHA-hoz szükséges third-party cookie-kat.
    Visszaadja a profilkönyvtárat és a folyamatot, hogy a login után lehessen
    takarítani.
    """
    browser = _find_browser()
    if browser is None:
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return None

    name, executable = browser
    profile_dir = Path(tempfile.mkdtemp(prefix="lidl-login-"))
    args = [executable]
    if incognito:
        args.append("--incognito" if name == "chrome" else "--inprivate")
    args.extend(
        [
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            url,
        ]
    )
    try:
        process = subprocess.Popen(args, close_fds=True)
        return profile_dir, process
    except OSError:
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return None


def _close_browser(opened: tuple[Path, subprocess.Popen] | None) -> None:
    if opened is None:
        return
    profile_dir, process = opened
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        pass
    shutil.rmtree(profile_dir, ignore_errors=True)


def login_manual(
    store: TokenStore,
    country: str = "HU",
    language: str = "hu",
    incognito: bool = False,
    open_browser_window: bool = True,
) -> TokenData:
    """Egyszeri, böngészős bejelentkezés; a callback URL-t a felhasználó illeszti be."""
    verifier, challenge = new_pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    url = build_login_url(country, language, challenge, state=state, nonce=nonce)

    print()
    print("=" * 78)
    print("LIDL PLUS BEJELENTKEZÉS")
    print("=" * 78)
    print()
    if open_browser_window:
        if incognito:
            print("1. Megnyílik a Lidl bejelentkező oldala egy friss, inkognitó")
            print("   Chrome/Edge ablakban (kiterjesztések és régi cookie-k nélkül).")
        else:
            print("1. Megnyílik a Lidl bejelentkező oldala egy friss, elkülönített")
            print("   Chrome/Edge ablakban (kiterjesztések és régi cookie-k nélkül).")
        print("   Ha nem nyílik meg, másold be az alábbi URL-t egy friss ablakba.")
    else:
        print("1. Nyisd meg az alábbi URL-t a SAJÁT böngésződben, abban a")
        print("   profilban, ahol már be vagy jelentkezve a lidl.hu oldalra.")
        print("   (A meglévő Lidl-session miatt így elkerülhető a login oldal.)")
    print()
    print(url)
    print()
    print("2. Jelentkezz be a Lidl-fiókodba (telefonszám/e-mail + jelszó + SMS-kód).")
    print("   Ha a jelszó automatikusan kitöltődik, töröld ki (X), és írd be")
    print("   kézzel – különben a Tovább gomb inaktív maradhat.")
    print()
    print("3. Sikeres belépés után a böngésző egy hibás oldalt mutat:")
    print("   'com.lidlplus.app://callback?...' – ez teljesen normális.")
    print("   Másold ki a TELJES URL-t a böngésző címsorából,")
    print("   és illeszd be ide.")
    print()
    print("=" * 78)

    opened = open_browser(url, incognito=incognito) if open_browser_window else None
    if open_browser_window and opened is None:
        print("\n(A böngészőt nem sikerült automatikusan megnyitni – nyisd meg")
        print("az URL-t kézzel egy friss ablakban.)")

    pasted = input("\nCallback URL (vagy csak a code): ").strip()
    callback_state = extract_state(pasted)
    if callback_state is not None and callback_state != state:
        raise AuthError(
            "A visszairányítási state nem egyezik (lejárt vagy másik bejelentkezésből "
            "származó URL). Indítsd újra a login parancsot."
        )
    code = extract_code(pasted)
    token = exchange_code(code, verifier, country, language)
    store.save(token)
    _close_browser(opened)
    print(f"\nSikeres bejelentkezés. Token mentve: {store.path}")
    return token


def login_capture(
    store: TokenStore,
    country: str = "HU",
    language: str = "hu",
    mode: str = "default",
    timeout: float = 600,
) -> TokenData:
    """Bejelentkezés automatikus callback-elfogással.

    A com.lidlplus.app:// sémára ideiglenesen regisztrál egy Windows
    protokoll-kezelőt. A böngészőben a sikeres login után a callback URL-t
    a kezelő elmenti, így nem kell DevTools/Network/másolás.
    """
    verifier, challenge = new_pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    url = build_login_url(country, language, challenge, state=state, nonce=nonce)
    callback_file = store.path.parent / f"callback_{country.upper()}.txt"
    callback_file.parent.mkdir(parents=True, exist_ok=True)
    callback_file.unlink(missing_ok=True)

    print()
    print("=" * 78)
    print("LIDL PLUS BEJELENTKEZÉS")
    print("=" * 78)
    print()
    if mode == "clean":
        print("1. Megnyílik egy friss, ideiglenes Chrome/Edge ablak.")
    elif mode == "incognito":
        print("1. Megnyílik egy friss, inkognitó Chrome/Edge ablak.")
    elif mode == "no-browser":
        print("1. Nyisd meg az alábbi URL-t a saját böngésződben:")
        print()
        print(url)
        print()
    else:
        print("1. Megnyílik a Lidl bejelentkező oldala a böngésződben.")
    print("2. Jelentkezz be a Lidl-fiókodba (telefonszám/e-mail + jelszó + SMS-kód).")
    print()
    print("3. Amikor a böngésző rákérdez, hogy megnyitja-e a Lidl Plus-t")
    print("   („Open Lidl Plus?” / „Megnyitás”), kattints az Open/Megnyitás")
    print("   gombra. Ezt az eszköz automatikusan elkapja – nem kell F12,")
    print("   Network vagy URL-másolás.")
    print()
    print("=" * 78)

    try:
        register_protocol(callback_file)
    except Exception as exc:
        unregister_protocol()
        print(f"\nA protokoll-kezelőt nem sikerült regisztrálni ({exc}).")
        print("Átváltok a manuális módra.")
        return login_manual(
            store,
            country=country,
            language=language,
            incognito=(mode == "incognito"),
            open_browser_window=True,
        )

    opened = None
    try:
        if mode == "clean":
            opened = open_browser(url, incognito=False)
            if opened is None:
                print(url)
        elif mode == "incognito":
            opened = open_browser(url, incognito=True)
            if opened is None:
                print(url)
        elif mode == "no-browser":
            pass
        else:
            try:
                if not webbrowser.open(url):
                    print(url)
            except Exception:
                print(url)

        deadline = time.time() + timeout
        callback = ""
        while time.time() < deadline:
            if callback_file.is_file():
                try:
                    callback = callback_file.read_text(encoding="utf-8").strip()
                except OSError:
                    callback = ""
                if callback:
                    break
            time.sleep(0.5)

        if not callback:
            raise AuthError(
                "Nem érkezett vissza a callback URL. Ha a böngésző nem kérdezett "
                "rá a Lidl Plus megnyitására, próbáld a manuális módot: "
                "python -m lidl login --manual"
            )

        callback_state = extract_state(callback)
        if callback_state is not None and callback_state != state:
            raise AuthError(
                "A visszairányítási state nem egyezik (lejárt vagy másik "
                "bejelentkezésből származó URL). Indítsd újra a login parancsot."
            )

        code = extract_code(callback)
        token = exchange_code(code, verifier, country, language)
        store.save(token)
        print(f"\nSikeres bejelentkezés. Token mentve: {store.path}")
        return token
    finally:
        unregister_protocol()
        callback_file.unlink(missing_ok=True)
        if opened is not None:
            _close_browser(opened)
