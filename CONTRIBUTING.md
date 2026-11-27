# Közreműködés

Köszönjük, hogy javítanál vagy kiegészítenéd a projektet!

## Hibajegy / ötlet

- Előbb nézd meg a meglévő issue-kat.
- Írd le a verziót, az operációs rendszert és a reprodukálás lépéseit.
- **Soha ne küldj** tokent, nyugta-PDF-et, vásárlási adatot vagy jelszót.
  Szintetikus adatokkal dolgozz.

## Fejlesztés

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s tests
```

- A kód Python 3.14+, típusannotációkkal; a felület magyar nyelvű.
- A külső függőségeket tartsd minimálisan; a stdlib-et részesítsd előnyben.
- A felhasználói felület szövegei magyarul, a kód azonosítói angolul vannak.
- A PR-hoz rövid leírás és – ha van – teszt tartozzon.

## Formázás

- 4 spaces, nincs tab.
- A hosszú sorokat törd (kb. 100 karakter).
- A nyilvános API-k és a viselkedés dokumentálva legyen a doksikban.

## Licenc

A hozzájárulásod a projekt MIT licence alatt kerül publikálásra.
