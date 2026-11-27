# Docker telepítés

A teljes eszköz egyetlen konténerben fut: letöltés, PDF/JPG render,
Excel/CSV jegyzék, garancia-kimutatás, valamint a webes felület.
A token, a nyers nyugták és a kész fájlok **volume-on** élnek, ezért a
konténer újraindítása vagy frissítése nem veszít adatot.

```
.
├── data/       → /data a konténerben: token, receipts/HU, logs, config.json
└── nyugtak/    → /nyugtak: PDF/JPG, XLSX/CSV kimutatások
```

A webes felület a **8765** porton figyel.

## Gyors indítás

```bash
git clone https://github.com/reitam/lidl-receipts.git
cd lidl-receipts
cp .env.example .env
mkdir -p data nyugtak
docker compose up -d --build
```

Az első build 5–10 perc (Chromium + függőségek). Az image letöltési mérete
~600–700 MB, a lemezen kicsomagolva ~2 GB (Chromium). Ellenőrzés:

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok","version":"2.0.0","token":false,"receipts":0,"pdfs":0,...}
```

Ezután: http://127.0.0.1:8765/

> A kötetek alapból a compose projektmappájához relatívak (`./data`,
> `./nyugtak`). Szerveren az `.env`-ben abszolút útvonalat is megadhatsz,
> pl. `LIDL_DATA_PATH=/srv/lidl/data`.

## Beállítások

| Változó | Jelentés |
|---|---|
| `LIDL_UI_PASSWORD` | A felület jelszava. Üresen hagyva nincs jelszó – ilyenkor a hálózat véd. |
| `LIDL_BIND` | `0.0.0.0` = minden interfész; konkrét IP is megadható. |
| `LIDL_DATA_PATH` / `LIDL_OUTPUT_PATH` | A két perzisztens mappa. |
| `LIDL_APP_VERSION` | Csak 401/426 hiba esetén kell kitölteni (a Lidl app verziója). |
| `LIDL_UID` / `LIDL_GID` | A konténer és a fájlok tulajdonosa (alap: 1000). |

A jelszó csak környezeti változóból jön; nem kerül a `config.json`-ba.

## Első bejelentkezés

1. Nyisd meg a felületet, majd a **Lidl fiók** menüpontot.
2. **Bejelentkezés indítása** – a szerver generál egy authorize URL-t.
3. Nyisd meg az URL-t a saját böngésződben (bármelyik gépen vagy telefonon).
4. Jelentkezz be; a böngésző végül a `com.lidlplus.app://callback?...`
   címre próbál menni (hibás oldal) – ez normális.
5. Másold ki a **teljes URL-t** a címsorból, illeszd be a felületre, és
   nyomd meg a **Bejelentkezés befejezése** gombot.

A token a `data/token_HU.json` fájlba kerül, a volume-on marad.

Ha a felület nem elérhető, konténerből is megy:

```bash
docker compose exec -it lidl python -m lidl login --manual
```

## Ha lejár a token

A hozzáférési token óránként jár le, de a refresh token automatikusan
megújítja – ehhez nem kell csinálni semmit. A **refresh token** viszont
hetek/hónapok alatt lejárhat, vagy visszavonható (jelszóváltás, kijelentkezés,
Lidl-oldali változás). Ilyenkor:

- a letöltés `401`-gyel elhasal,
- a felület tetején megjelenik, hogy nincs érvényes token,
- ntfy esetén jön a **„Lidl: bejelentkezés szükséges”** értesítés.

Teendő: **Lidl fiók → Bejelentkezés indítása**, majd a fenti 5 lépés.
A meglévő token ellenőrizhető a **Token ellenőrzése** gombbal is (frissíti,
és ha nem megy, azonnal jelzi).

> **Fontos:** a refresh token minden frissítésnél **rotálódik** – a régi
> azonnal érvénytelenné válik. Ezért **egyszerre csak egy példány**
> használja ugyanazt a tokent. Ha a szerver mellett a helyi gépen is
> futtatsz `fetch`/`all` parancsot, a két példány elveheti egymás tokent.
> A szerver bevezetése után a helyi gépen ne indíts letöltést.

Ha a Lidl `426`-ot ad (App-Version hiba), állítsd a `LIDL_APP_VERSION`-t a
Lidl app aktuális verziójára, és indítsd újra a konténert.

## Ütemezés és értesítés

A **Beállítások** oldalon:

- **Automatikus frissítés:** napok + időpont. A teljes frissítés
  (letöltés + PDF + jegyzék + garancia) fut le. Ha a konténer a megadott idő
  után indul újra, legfeljebb 6 órán belül pótolja.
- **ntfy:** szerver URL, topic, opcionális token. Az ütemezett futásról és
  minden hibáról küld; a kézi futtatásról csak bekapcsolva.

A beállítások a `data/config.json`-ba mentődnek, tehát túlélik az
újraindítást.

## Mentés

A `data/` és `nyugtak/` mappa a lényeg. Mentéskor a konténert nem kell
leállítani, de a `data/token_HU.json` és a `config.json` írása miatt
érdemes rövid időre megállítani, vagy restic/Backrest snapshotot használni.

Ha a szerveren a Docker volume-okat és a bind mountokat Backrest menti,
vedd fel ezt a két mappát is a tervbe.

## Frissítés

```bash
git pull
docker compose up -d --build
```

Az adatokhoz nem nyúl; a meglévő PDF-eket nem generálja újra, csak a
hiányzókat.

## Hibaelhárítás

| Tünet | Megoldás |
|---|---|
| `Permission denied` a /data vagy /nyugtak alatt | `sudo chown -R 1000:1000 data nyugtak`, vagy állítsd a `LIDL_UID`/`LIDL_GID` értékét |
| `Executable doesn't exist ... chromium` | Az image-ből hiányzik a böngésző: `docker compose build --no-cache` |
| A PDF szövege kilóg / más a tördelés | Hiányzik a `fonts-liberation`; az alap image-ben benne van |
| `HTTP 401` a letöltésnél | Lejárt/visszavont token: Lidl fiók → új bejelentkezés |
| `HTTP 426` / App-Version hiba | `LIDL_APP_VERSION` beállítása, majd `docker compose up -d` |
| A konténer nem érhető el kívülről | `LIDL_BIND`, tűzfal, reverse proxy |
| Ütköző port | A `compose.yaml`-ben a `8765:8765` bal oldalát írd át |
| Az ntfy teszt nem megy | URL/topic ellenőrzése; a konténer érje el a szervert |
| Lassú az első PDF | Az első rendernél indul a Chromium; utána gyors |

## Biztonság

- A felület alapból **jelszó nélkül** indul – csak megbízható hálózaton
  (VPN, Tailscale, LAN) használd. Nyilvános internetre ne tedd ki.
- Jelszó: `LIDL_UI_PASSWORD`; a sessionök a memóriában élnek, a konténer
  újraindításakor lejárnak. Minden POST CSRF-védett.
- A `data/token_HU.json` olyan, mint egy jelszó: ne kerüljön gitbe, és a
  volume maradjon a konténer felhasználójáé.
- Az image nem tartalmaz titkot; minden érzékeny adat a volume-on van.

## Architektúra

- x86_64 (a Chromium miatt; armv7/Raspberry Pi 3 nem ajánlott).
- Egy konténer, egy Python-folyamat, beépített ütemező.
- A PDF-render a beépített Chromiummal, a Lidl HTML-jéből készül.
