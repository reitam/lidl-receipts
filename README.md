# Lidl Plus e-nyugta archívum

[![tests](https://github.com/reitam/lidl-receipts/actions/workflows/tests.yml/badge.svg)](https://github.com/reitam/lidl-receipts/actions/workflows/tests.yml)

Nem hivatalos, önálló eszköz a **Lidl Plus fiókhoz tartozó elektronikus
vásárlási nyugták** letöltésére, papír-hű PDF-ek készítésére és kereshető
Excel/CSV archívum építésére – webes felülettel, ütemezett frissítéssel és
Docker-támogatással.

> **English:** an unofficial, self-hosted Lidl Plus e-receipt downloader and
> archiver with paper-faithful PDF rendering, Excel/CSV indexes, a warranty
> report, a built-in web UI, a scheduler, ntfy notifications and Docker
> support. Hungarian Lidl receipts are the primary target.

> **Nem hivatalos eszköz.** A Lidl nem biztosít nyilvános exportot; ez az
> eszköz a Lidl Plus mobilapp által használt, közösség által feltárt API-t
> utánozza. Csak a **saját** fiókod adatait éri el, és minden adat nálad
> marad. Az API bármikor változhat. A Lidl és a Lidl Plus a Lidl
> védjegyei; ez a projekt nem áll kapcsolatban a Lidllel.

## Mit tud?

- **Letöltés** – a fiókhoz tartozó összes e-nyugta nyers JSON-ja, inkrementálisan.
- **Papír-hű PDF** – a Lidl appban látható nyugta HTML-jéből, a visszaküldési
  vonalkóddal és a papír lábléccel; opcionálisan JPG is.
- **Excel/CSV jegyzék** – nyugták és tételek, havi összesítővel.
- **Garancia-kimutatás** – a műszaki/szerszám jellegű tételek 3 éves
  garanciával, aktív/lejárt bontásban.
- **Webes felület** – áttekintés, kereshető nyugtalista (a tételek között is),
  nyugta-előnézet, PDF/JPG/JSON letöltés, riportok, futásnapló, beállítások.
- **Ütemezés + ntfy** – napi automatikus frissítés, értesítés sikerrel/hibával
  (például lejárt token esetén).
- **Docker** – egy konténer, volume-on tárolt adatokkal; a token és a nyugták
  túlélik az újraindítást.

## Gyors indítás (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
.\lidl.cmd login     # bejelentkezés a böngészőben
.\lidl.cmd all       # letöltés + PDF + Excel + garancia
```

Vagy grafikusan:

```powershell
.\start_lidl.bat
```

Ez elindítja a helyi webes felületet: **http://127.0.0.1:8765/**

Részletes, lépésről lépésre útmutató: **[HASZNALAT.md](HASZNALAT.md)**

## Docker

```bash
git clone https://github.com/reitam/lidl-receipts.git
cd lidl-receipts
cp .env.example .env
mkdir -p data nyugtak
docker compose up -d --build
```

A felület: `http://<szerver>:8765/`. A részletek (volume-ok, jogosultságok,
token-lejárat, mentés, hibaelhárítás): **[DOCKER.md](DOCKER.md)**.

## Bejelentkezés

A Lidl OAuth2 + PKCE folyamatot használ; a jelszó és az SMS-kód kizárólag a
Lidl saját oldalán kerül felhasználásra. Az eszköz csak a visszakapott
egyszeri kódot váltja tokenre, és a refresh tokent tárolja helyben
(`data/token_HU.json`).

- Windowson a callback URL-t egy ideiglenes `com.lidlplus.app://`
  protokoll-kezelő kapja el, így nem kell másolni.
- Dockerben a felület **Lidl fiók** oldalán indítható a folyamat, és a
  callback URL-t kell beilleszteni (a böngésző a hoston marad).

A refresh token minden frissítésnél rotálódik. **Egyszerre csak egy példány
használja ugyanazt a tokent** – különben a két példány elveheti egymásét.

## Parancsok

| Parancs | Mit csinál |
|---|---|
| `python -m lidl login` | Bejelentkezés (automatikus callback-elfogással, Windowson) |
| `python -m lidl login --manual` | Callback URL kézi beillesztése |
| `python -m lidl login --force` | Új token kérése |
| `python -m lidl fetch` | Nyugták letöltése (csak az újakat) |
| `python -m lidl fetch --full` | Minden nyugta újraletöltése |
| `python -m lidl render` | Hiányzó PDF-ek elkészítése |
| `python -m lidl render --format both` | PDF és JPG |
| `python -m lidl export` | Excel/CSV jegyzék |
| `python -m lidl warranty` | 3 éves garancia-kimutatás |
| `python -m lidl all` | fetch + render + export + warranty |
| `python -m lidl status` | Token, nyugták, időszak, PDF-ek |
| `python -m lidl dashboard` | Helyi webes felület (127.0.0.1:8765) |
| `python -m lidl serve` | Webes felület hálózaton (0.0.0.0:8765) |

## Kimenet

```
nyugtak/
  2025/
    2025-03-14_17-22_Lidl-Budapest-Vaci-ut_12345Ft_<id>.pdf
  2026/
    2026-11-08_14-32_Lidl-Budaors_8765Ft_<id>.pdf
  nyugtak_index_HU.xlsx     ← Nyugták / Tételek / Havi összesítő
  nyugtak_index_HU.csv
  nyugtak_tetelek_HU.csv
  muszaki_garancia_HU.xlsx  ← műszaki/szerszám 3 éves garancia
data/
  token_HU.json             ← titkos, ne oszd meg
  receipts/HU/<id>.json     ← a Lidl teljes nyers válasza
```

## Hogyan működik?

- **Bejelentkezés:** OAuth2 authorization code + PKCE a `accounts.lidl.com`
  oldalon. A böngészős lépés a reCAPTCHA és az SMS-es 2FA miatt manuális.
- **Token:** a refresh token minden frissítésnél rotálódik; az eszköz
  azonnal menti az újat.
- **Nyugták:** `GET /api/v2/HU/tickets` (lapozva) és
  `GET /api/v3/HU/tickets/{id}` (részletek).
- **Renderelés:** Playwright + Chrome/Edge (Windows) vagy a beépített
  Chromium (Docker), headless módban. A PDF 324 px széles, papír-hű.
- **Tárolás:** nincs adatbázis; a JSON-ok a forrás, a PDF/XLSX belőlük készül.

## Hibaelhárítás

| Hiba | Megoldás |
|---|---|
| `Nincs mentett bejelentkezés` | `.\lidl.cmd login` |
| `A Lidl elutasította a tokent` | Lejárt/visszavont token: új login |
| `HTTP 426` / App-Version hiba | `LIDL_APP_VERSION` beállítása |
| `HTTP 429` | Átmeneti Lidl-korlátozás; várj, majd újra |
| Nem indul a böngésző | Telepítsd a Chrome-ot vagy az Edge-et |
| Dockerben nincs PDF | Nézd meg a `docker compose logs -f lidl` kimenetét |

## Adatvédelem

A token és a nyugták személyes adatok. A `data/` és a `nyugtak/` nincs a
repóban (`.gitignore`, `.dockerignore`), és a naplók sem tartalmazzák a
tokenet. A webes felületet ne tedd ki nyilvános internetre; használj VPN-t
(pl. Tailscale) vagy legalább erős jelszót (`LIDL_UI_PASSWORD`).

## Licenc

MIT – lásd [LICENSE](LICENSE). A függőségek és azok licencei:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Köszönet

Az API feltárása a közösség munkája, elsősorban
[Andre0512/lidl-plus](https://github.com/Andre0512/lidl-plus) és az azt
tovább vívő projektek. Ez a repo a magyar nyugtákhoz igazított, karcsú
letöltőt/renderelőt adja hozzá.
