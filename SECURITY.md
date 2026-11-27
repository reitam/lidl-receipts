# Biztonsági irányelvek

## Támogatott verziók

A legutolsó kiadást (és a `main` ágat) támogatjuk. Hibát a legfrissebb
verzióval ellenőrizz.

## Sebezhetőség bejelentése

**Kérjük, ne nyiss nyilvános issue-t sebezhetőségről.** Használd a GitHub
**Security → Report a vulnerability** (privát sebezhetőség-bejelentés)
funkcióját. Ha ez nem elérhető, jelezd röviden, személyes adatot nem
tartalmazó üzenetben.

A bejelentésben lehetőleg add meg:

- az érintett verziót / commitot,
- a reprodukálás lépéseit,
- a várt és a tényleges viselkedést,
- a lehetséges hatást (pl. adatszivárgás, jogosultság-emelés).

## Ne küldj személyes adatot

A token és a nyugták személyes adatok. **Soha ne csatolj** valódi
`token_HU.json`-t, nyugta-PDF-et, vásárlási adatot vagy jelszót issue-hoz,
PR-hoz vagy hibajelentéshez. A hibát szintetikus adatokkal reprodukáld.

## Hatókör

- a bejelentkezési folyamat (OAuth2 + PKCE, callback-kezelés),
- a webes felület (auth, CSRF, session, fájlelérés),
- a konténer és a volume-jogosultságok,
- a Lidl HTML-feldolgozása (pl. nem várt bemenet).

A Lidl API nem hivatalos; annak változása nem biztonsági hiba, de jelezhető.
