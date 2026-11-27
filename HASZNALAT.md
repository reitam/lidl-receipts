# Használati útmutató – Lidl Plus e-nyugta letöltő

Ez a leírás végigvezet az első bejelentkezéstől a kész PDF-ekig. Az alábbiakban
a `C:\Lidl` csak példaútvonal – használd a saját projektmappádat.

> Rövid verzió:
> 1. `.\lidl.cmd login` → bejelentkezés a böngészőben, callback URL beillesztése
> 2. `.\lidl.cmd all` → letöltés + PDF + Excel
>
> Vagy grafikusan: `.\start_lidl.bat` → http://127.0.0.1:8765/
> (a részletek a „Webes felület” szakaszban).

---

## 0. Mi ez?

A Lidl Plus fiókodhoz tartozó **összes elektronikus nyugtát** letölti a gépedre:

- nyugtánként egy **PDF** a `nyugtak\<év>\` mappába,
- egy **Excel** (`nyugtak_index_HU.xlsx`) a nyugtákról, a tételekről és a havi
  összesítőről,
- a Lidl teljes nyers válaszát JSON-ban a `data\receipts\HU\` mappába.

Nem hivatalos eszköz: a Lidl Plus mobilapp belső API-ját használja. Csak a
**saját** fiókod adatait éri el, és minden adat a gépeden marad.

---

## 1. Első telepítés (csak egyszer)

Nyiss egy PowerShellt, és futtasd:

```powershell
cd C:\Lidl
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Ez létrehozza a `.venv` mappát, és telepíti a szükséges Python-csomagokat
(requests, Playwright, qrcode, python-barcode, openpyxl). Körülbelül 1–2 perc.

Ha kész, ezt írja ki: `Kész. Következő lépés: ...`

> A későbbi futtatásokhoz már nem kell a `setup.ps1`, elég a `lidl.cmd`.

---

## 2. Bejelentkezés (egyszer, vagy ha lejár a token)

```powershell
cd C:\Lidl
.\lidl.cmd login
```

### Mi történik ezután?

1. **Megnyílik a Lidl bejelentkező oldala** a böngésződben
   (`accounts.lidl.com`).
2. **Jelentkezz be** a Lidl-fiókodba:
   - telefonszám vagy e-mail cím,
   - jelszó,
   - az SMS-ben kapott kód.
3. Sikeres belépés után a böngésző megpróbálja megnyitni a Lidl Plus
   mobilappot. Ha a Chrome/Edge rákérdez („Open Lidl Plus?” /
   „Megnyitás?”), kattints az **Open / Megnyitás** gombra.
   Az eszköz a callback URL-t **automatikusan elkapja** – nem kell F12,
   Network, sem URL-másolás.
4. Ha minden rendben, ezt látod:

   ```
   Sikeres bejelentkezés. Token mentve: ...\data\token_HU.json
   ```

### Ha az automatikus elfogás nem működik

- `.\lidl.cmd login --manual` – kézi mód: a callback URL-t a böngésző
  címsorából kell bemásolni (a régi módszer).
- `.\lidl.cmd login --clean` – friss, ideiglenes Chrome/Edge profil.
- `.\lidl.cmd login --no-browser` – nem nyit böngészőt; a kiírt URL-t a saját
  böngésződben nyisd meg (pl. ahol már be vagy jelentkezve a `lidl.hu`-ra).
- `.\lidl.cmd login --incognito` – inkognitó ablak.
- Ha a token lejárt, a `.\lidl.cmd all` **automatikusan elindítja a loginot**.

### Fontos tudnivalók

- A `com.lidlplus.app://` protokoll-kezelőt csak a login idejére
  regisztráljuk, utána automatikusan eltávolítjuk. Nem marad a rendszeren.
- A **jelszavad nem kerül fájlba**. Csak egy tokent tárolunk helyben, amivel a
  későbbi letöltések már böngésző nélkül mennek.
- **Ha a „Tovább” gomb szürke és nem történik semmi:** az oldal a Google
  reCAPTCHA tokentre vár. Várj 10–15 másodpercet; ha nem indul el, nyomj `F5`-öt,
  és próbáld újra. A jelszót ne hagyd automatikusan kitöltve – töröld ki (X), és
  írd be kézzel, mert az autofill miatt a gomb inaktív maradhat.
- Ha a böngésző nem kérdez rá a Lidl Plus megnyitására, használd a
  `--manual` módot.
- A bejelentkezési kód egyszer használatos és gyorsan lejár; ha hibát kapsz,
  egyszerűen futtasd újra a `.\lidl.cmd login --force` parancsot.

---

## 3. Első próba: 3 nyugta

Mielőtt az összeset letöltjük, érdemes megnézni 3 nyugtán, hogy a PDF rendben
van-e:

```powershell
.\lidl.cmd fetch --limit 3
.\lidl.cmd render --limit 3
```

Ezután nyisd meg a `nyugtak\` mappát (az évszámos almappát), és nézz meg egy
PDF-et. Ha a nyugta olvasható, a tételek és az összeg rendben vannak, jöhet a
teljes letöltés.

Állapot ellenőrzése bármikor:

```powershell
.\lidl.cmd status
```

---

## 4. Teljes letöltés

```powershell
.\lidl.cmd all
```

Ez három dolgot csinál:

1. **fetch** – letölti az összes nyugtát, amit a Lidl fiókodban talál
   (inkrementálisan: ami már megvan, azt kihagyja),
2. **render** – minden nyugtából PDF-et készít a `nyugtak\<év>\` mappába,
3. **export** – elkészíti az Excel/CSV jegyzéket.

A letöltés nyugtánként egy kérést indít, ezért 100 nyugta kb. 1–2 perc. A
végén összefoglalót ír ki (letöltve / kihagyva / hibák).

### Hol találom az eredményt?

```
C:\Lidl\
  nyugtak\
    2025\
      2025-03-14_17-22_Lidl-Budapest-Vaci-ut_12345Ft_<id>.pdf
    2026\
      2026-11-08_14-32_Lidl-Budaors_8765Ft_<id>.pdf
    nyugtak_index_HU.xlsx     ← ezt nyisd meg Excelben
    nyugtak_index_HU.csv
    nyugtak_tetelek_HU.csv
    muszaki_garancia_HU.xlsx  ← műszaki cikk / szerszám garancia kimutatás
  data\
    token_HU.json             ← titkos, ne oszd meg
    receipts\HU\<id>.json     ← nyers adatok
```

Az Excel három munkalapot tartalmaz:

- **Nyugták** – dátum, bolt, összeg, tételek száma, PDF helye, megjegyzés,
- **Tételek** – minden vásárolt termék, mennyiség, egységár, összeg, adó,
  valamint a kedvezménysorok (`Típus = Kedvezmény`, negatív összeggel),
- **Havi összesítő** – havi költés és nyugták száma.

> A **Nyugták** munkalap `Összeg` oszlopa a mérvadó. A **Tételek** összege
> eltérhet a nyugta végösszegétől, mert a Lidl a kosár-szintű kuponokat nem
> mindig osztja fel az egyes tételekre.
>
> Ha egy nyugtánál a Lidl `BROKEN_HTML` adatot ad (nem küld tételeket), arról
> csak egy összegző PDF készül; ezt a **Megjegyzés** oszlop jelzi. Később a
> `.\lidl.cmd fetch --full` újra letöltheti, hátha a Lidl helyreállítja.
>
> A PDF alján megtalálható a Lidl **visszaküldési vonalkódja** (CODE128),
> amelyet a Lidl API `codes` mezőjéből generálunk. A PDF papír-hű: a
> „BIZONYLAT MÁSOLAT” fejléc, a vonalkód, valamint a papír lábléc
> (`!!! NEM ADÓÜGYI BIZONYLAT !!!`, `KÖSZÖNJÜK A VÁSÁRLÁST 😊`) is rajta van.
> A digitális nyugta HTML-je és a papírnyugta lábléce között kisebb eltérések
> lehetnek; a visszáruzáshoz a nyugtaszám, a tranzakcióadatok és a vonalkód
> a lényeg.

### Műszaki cikk / szerszám garancia kimutatás

A `nyugtak\muszaki_garancia_HU.xlsx` a nyugták tételsorai alapján gyűjti ki a
műszaki cikkeket és szerszámokat, amelyekre jellemzően **3 év garancia**
vonatkozik. Munkalapok:

- **Műszaki garancia** – minden érintett tétel: dátum, bolt, eredeti tételnév,
  értelmezés (mi lehet), cikkszám, ár, garancia lejárata, státusz, hátralévő
  napok, bizonyosság, kategória, nyugta-PDF hivatkozás,
- **Aktív garanciák** – csak a még nem lejárt tételek, lejárat szerint,
- **Összesítő** – darabszámok, értékek, kategória/év/bizonyosság bontás,
- **Módszertan** – hogyan készült a besorolás.

A két legfontosabb oszlop:

- **Eredeti tételnév** – pontosan az, ami a nyugtán szerepel (gyakran rövidítve),
- **Értelmezés (mi lehet)** – következtetés a cikkszám/ár/kontextus alapján.

A **Bizonyosság** oszlop jelzi, mennyire egyértelmű a besorolás:
`Biztos` / `Valószínű` / `Bizonytalan`. A garancia lejárata a vásárlás napja
+ 3 év; a tényleges feltételek a termék csomagolásán/garancialevelén vannak.
A **Nyugta PDF** oszlopban a „Megnyitás” hivatkozás közvetlenül a nyugta
PDF-jét nyitja meg.

Frissítéskor a `.\lidl.cmd all` ezt a kimutatást is újragenerálja. Külön:
`.\lidl.cmd warranty`.

### Webes felület

A parancsok gombokkal is futtathatók. A legegyszerűbb indítás:

```powershell
.\start_lidl.bat
```

Ez elindítja a helyi szervert, és megnyitja a **http://127.0.0.1:8765/**
oldalt. Ha a szerver már fut, csak a böngészőt nyitja meg. Másik port:
`.\start_lidl.bat 8766`; böngésző nélkül: `.\start_lidl.bat 8765 --no-open`.

A felület:

- **Áttekintés** – token, nyugták, költés, PDF-ek, éves bontás; a műveletek
  gombjai (teljes frissítés, letöltés, render, jegyzék, garancia) élő
  naplóval és leállítással.
- **Nyugták** – keresés a tételek között is (ékezetfüggetlen), év/bolt szűrő,
  nyugta részletei, beágyazott előnézet, PDF/JPG/JSON letöltés.
- **Kimutatások** – jegyzék, garancia (aktív/lejárt, kereshető),
  Excel/CSV letöltéssel.
- **Futások** – az utolsó 50 feladat naplóval.
- **Lidl fiók** – bejelentkezés a callback URL beillesztésével.
- **Beállítások** – napi ütemezés, ntfy értesítés.

A szerver csak localhoston figyel; a terminálban `Ctrl+C`-vel állítható le.
Haladóknak: `.\lidl.cmd dashboard` (helyi) vagy `.\lidl.cmd serve` (hálózat).

### Docker

A teljes eszköz konténerben is fut: `docker compose up -d --build`, a felület
a `http://<szerver>:8765/` címen, az adatok volume-on. Részletek:
[DOCKER.md](DOCKER.md).

---

## 5. Későbbi frissítés

A Lidl fiókodban idővel új nyugták jelennek meg. Elég ugyanezt futtatni:

```powershell
.\lidl.cmd all
```

Csak az új nyugtákat tölti le, a meglévő PDF-eket nem készíti újra. A
`warranty` lépés a műszaki/szerszám garancia kimutatást is frissíti.

> Ha a `muszaki_garancia_HU.xlsx` vagy a `nyugtak_index_HU.xlsx` nyitva van
> Excelben, a tool `_ÉÉÉÉHHNN_ÓÓPPMM` utótaggal menti a frissített verziót.
> Zárd be az Excelt, hogy a fő fájl frissüljön.

Ha valamit mégis újra akarsz tölteni, illetve újrarenderelni:

```powershell
.\lidl.cmd fetch --full      # minden nyugta újraletöltése
.\lidl.cmd render --force    # minden PDF újragenerálása
```

---

## 6. Parancsok gyorsan

| Parancs | Mit csinál |
|---|---|
| `.\lidl.cmd login` | Bejelentkezés böngészőben |
| `.\lidl.cmd login --force` | Új token kérése (lejárt token esetén) |
| `.\lidl.cmd fetch` | Nyugták letöltése (csak az újakat) |
| `.\lidl.cmd fetch --limit 3` | Csak az első 3 nyugta (teszthez) |
| `.\lidl.cmd render` | PDF-ek elkészítése a hiányzókból |
| `.\lidl.cmd render --format both` | PDF és JPG is |
| `.\lidl.cmd export` | Excel/CSV jegyzék újragenerálása |
| `.\lidl.cmd warranty` | Műszaki/szerszám 3 éves garancia Excel |
| `.\lidl.cmd dashboard` | Helyi webes felület (127.0.0.1:8765) |
| `.\lidl.cmd serve` | Webes felület hálózaton (0.0.0.0:8765) |
| `.\lidl.cmd all` | Letöltés + PDF + jegyzék + garancia kimutatás |
| `.\lidl.cmd status` | Állapot: token, nyugták, időszak, PDF-ek |

A `lidl.cmd` helyett használhatod a hosszabb formát is:

```powershell
.\.venv\Scripts\python.exe -m lidl all
```

---

## 7. Ha valami nem működik

| Hibaüzenet / jelenség | Megoldás |
|---|---|
| `Nincs mentett bejelentkezés` | Futtasd: `.\lidl.cmd login` |
| `A Lidl elutasította a tokent` | Futtasd: `.\lidl.cmd login --force` |
| `HTTP 426` / App-Version hiba | `set LIDL_APP_VERSION=17.0.0`, majd `.\lidl.cmd fetch` |
| `HTTP 429` | A Lidl átmenetileg korlátoz; várj 10–15 percet, majd újra |
| Nem nyílik meg a böngésző | A terminálban kiírt URL-t másold be kézzel egy friss ablakba |
| A „Tovább” gomb szürke, nem történik semmi | Az oldal a Google reCAPTCHA-ra vár. Várj 10–15 mp-et, majd `F5`; a jelszót írd be kézzel, autofill nélkül |
| `Túlterheltek vagyunk` üzenet | Túl sok próbálkozás történt; várj 10–15 percet, és utána próbáld újra |
| `accounts.lidl.com/error/500` | Ne nyomj `F5`-öt (újraküldi a felhasznált tranzakciót). Indíts új `login` parancsot; ha friss login után is 500, használd a `--no-browser` módot a `lidl.hu`-s sessionnel |
| A Lidl Plus login oldal nem működik, de a `lidl.hu` login igen | `.\lidl.cmd login --no-browser`, majd a kiírt URL-t nyisd meg a már bejelentkezett `lidl.hu`-s böngésződben |
| Google-belépésnél a consent után elakad | A Google engedélyezés után a Lidl visszairányítása akadhat el. Ilyenkor várd ki a korlátozást, majd használd a jelszavas loginot (kevesebb átirányítás) |
| Az inkognitó ablakban elakad | Használd az alapértelmezett böngészőt, vagy a `--clean` módot |
| A `com.lidlplus.app` megnyitását nem kérdezi meg a böngésző | `.\lidl.cmd login --manual` (kézi callback-másolás) |
| `Nem sikerült elindítani a Chrome/Edge böngészőt` | Telepítsd a Chrome-ot vagy az Edge-et |
| Egy nyugta PDF-je hiányzik | `.\lidl.cmd render --force` |
| Az Excel nem nyílik meg | A `nyugtak_index_HU.xlsx` fájlt nyisd meg, ne a CSV-t |
| A token hónapok után lejárt | `.\lidl.cmd login --force` |

Ha egy nyugta letöltése hibás lett, a többi ettől még letöltődik; a hiba a
futás végén kilistázódik. Ilyenkor elég újra futtatni a `fetch`-et.

### Ha a reCAPTCHA teljesen megakad (haladó)

A Lidl a „Tovább” előtt Google reCAPTCHA Enterprise tokent kér. Ha a gomb
sokáig szürke marad, a reCAPTCHA nem válaszol. Ilyenkor a böngészőben, a
password-lépésnél nyisd meg a fejlesztői eszközöket (`F12`), válts a
**Console** fülre, és illeszd be ezt (a jelszót előtte írd be kézzel a mezőbe):

```js
fetch('/api/rules?client_id=LidlPlusNativeClient&country_code=HU')
  .then(r => r.json())
  .then(rules => grecaptcha.enterprise.execute(rules.reCaptchaConfig.key, { action: 'login' }))
  .then(token => {
    document.querySelector('input[name="ReCaptchaToken"]').value = token;
    document.querySelector('form').submit();
  })
  .catch(err => console.error('reCAPTCHA hiba:', err));
```

Ez a Lidl oldalának saját reCAPTCHA-kulcsával kér friss tokent, majd
beküldi az űrlapot. Ha itt is hibát kapsz, vagy a `grecaptcha` nem létezik,
akkor a Google reCAPTCHA valószínűleg blokkolva van a hálózaton/böngészőben –
ilyenkor próbálj másik hálózatot, vagy a „Folytatás Google fiókkal” gombot, ha
a Lidl-fiókod össze van kötve Google-fiókkal.

### Ha a Lidl Plus login oldal 500-as hibát ad, vagy nem megy

A sima `lidl.hu` login **másik OAuth klienst** használ, és az gyakran akkor is
működik, amikor a Lidl Plus login oldala elakad. Ilyenkor használd a meglévő
`lidl.hu` session-t:

1. Nyisd meg a `https://www.lidl.hu/` oldalt a **saját Chrome-profilodban**, és
   jelentkezz be (ha még nem tetted meg).
2. A terminálban futtasd:
   ```powershell
   .\lidl.cmd login --no-browser
   ```
3. A kiírt URL-t **ugyanabban a Chrome-profilban** nyisd meg egy új lapon.
   Ha a meglévő Lidl-session-t elfogadja, a login oldal helyett rögtön a
   `com.lidlplus.app://callback?code=...` címre ugrik. A login idejére
   regisztrált protokoll-kezelő ezt **automatikusan elkapja**; ha a böngésző
   rákérdez, kattints az **Open / Megnyitás** gombra.
4. Ha a böngésző nem adja át a callbacket (nincs felugró ablak, nincs mentés),
   akkor használd a `.\lidl.cmd login --manual` módot, és a callback URL-t a
   fejlesztői eszközökkel kapd el:
   - `F12` → **Network** fül → **Preserve log** bekapcsolása,
   - nyisd meg újra ugyanazt az authorize URL-t,
   - keresd meg a piros/failed `callback?code=...` kérést,
   - jobb klikk → **Copy** → **Copy link address** (vagy Headers → Request URL),
   - illeszd be a terminálba.

> **Fontos:** a hibaoldalon ne nyomj `F5`-öt! Az újraküldi a már felhasznált
> tranzakciót, és 500-as hibát okozhat. Mindig indíts új `login` parancsot.

---

## 8. Adatvédelem

- A `data\token_HU.json` fájl hozzáférést ad a Lidl-fiókodhoz. **Ne oszd meg,
  ne küldd el, ne tedd fel git repóba.**
- A `data\` és a `nyugtak\` mappát a `.gitignore` kizárja, tehát véletlenül sem
  kerülnek verziókezelésbe.
- A jelszó nem kerül fájlba; a bejelentkezés a Lidl saját oldalán történik.
- Ha más gépen is szeretnéd használni: telepítsd újra, és ott is futtass egy
  `login`-t. A tokenfájlt nem érdemes átmásolni, mert a Lidl rotálja.
- A tokenfájl tartalmazza a refresh tokent, ami hozzáférést ad a Lidl-fiókod
  nyugtáihoz. Kezeld úgy, mint egy jelszót.

---

## 9. Több ország?

A Lidl Plus fiók egy országhoz tartozik. Ha külföldön is vásároltál ugyanezzel
a fiókkal, előfordulhat, hogy az adott ország külön lekérdezést igényel. Ilyenkor
a parancsok végére teheted:

```powershell
.\lidl.cmd --country AT --language de fetch
```

Magyar fióknál erre nincs szükség, az alapértelmezés `HU` / `hu`.

---

## 10. Miért kell kézzel bejelentkezni?

A Lidl bejelentkező oldala reCAPTCHA-t és SMS-es kétfaktoros azonosítást
használ. Ezeket szándékosan nem lehet teljesen automatizálni, ezért az első
lépés mindig egy valódi böngészőben történik. Utána a mentett token már
böngésző nélkül működik – egészen addig, amíg a Lidl azt vissza nem vonja.
