# WebNauticalChart — Sjökort Runn

Webbaserad sjökortsvisare: en statisk sida som visar Runns Båtförbunds sjökort
över Runn med användarens GPS-position. Öppnas i mobil/dator, låses upp med en
köpkod, och fungerar offline. Publiceras gratis via GitHub Pages.

- **Live:** https://rallyhagge.github.io/Runn/
- **Repo:** github.com/RallyHagge/Runn (gren `master`, Pages från mappen `/docs`)
- **Mål:** överlämnas till Runns Båtförbund (Sjökortssektionen) för framtida
  drift. Se `README.md` — den är skriven för föreningen, håll den begriplig.

## Arbetssätt (viktigt)
- Kommunicera på **svenska**. Tider i svensk lokaltid (se globala ~/CLAUDE.md).
- **Håll den här CLAUDE.md uppdaterad** vid varje meningsfull ändring (stående
  önskemål från användaren: dokumentera alltid projektstatus i CLAUDE.md).
- Uppdatera även `README.md` när något ändras som påverkar föreningens drift.

## Arkitektur & nyckelfiler
```
docs/                     ← allt som publiceras (GitHub Pages, mapp /docs)
  index.html              sida; refererar app.js/style.css med ?v=N (cache-bust)
  app.js                  Leaflet-karta, GPS, upplåsning, service-worker-styrning
  style.css
  sw.js                   service worker (offline-cache)
  manifest.webmanifest    PWA/hemskärm; name "Sjökort Runn"
  chart/tiles/            KRYPTERADE rutor (.bin), z8–z16, ~3900 st (~18 MB)
  chart/bounds.json       kartans WGS84-hörn
  chart/tiles-manifest.json  rut-lista + versionsstämpel (offline-cachen)
  access/codes.json       inslagna nycklar (INGEN klartext) — en per köpkod
  icons/  img/  vendor/leaflet/
scripts/
  prepare_chart.py        källbild → krypterade tiles + bounds + manifest
  access.py               delad krypto (KDF/AES). Params måste matcha app.js
  mint_code.py            skapar köpkoder
  make_icon.py            ritar app-ikonen
source/                   HEMLIGT, gitignore: chart.png/.pgw, master.key,
                          issued_codes.csv  (+ node_modules, .claude ignoreras)
```

## Vanliga kommandon
```
# Uppdatera kartan till ny utgåva (kräver source/chart.png + .pgw):
py -3 scripts/prepare_chart.py source/chart.png --epsg 3021 --tiles --encrypt
# Skapa en köpkod:
py -3 scripts/mint_code.py --note "namn"
# Rita om ikonen:
py -3 scripts/make_icon.py
# Beroenden:
py -3 -m pip install -r requirements.txt   # pillow, pyproj, rasterio, cryptography
```
Deploy = `git add -A && git commit && git push` (Pages bygger om på ~30 s).
Bumpa `?v=N` i `docs/index.html` för css/js vid ändring.

## Koordinatsystem
Källa: OCAD-export `Sjökort Runn 2023 1-25000.png` + `.pgw` i
`C:\Users\andhag\OneDrive - Triona AB\Dokument\`. **EPSG:3021 (RT90 2,5 gon V)**,
~1,06 m/px. `prepare_chart.py` warpar till Web Mercator (EPSG:3857) för exakt
inpassning i Leaflet.

## Kodskydd (invariants — ändra inte lättvindigt)
- Rutorna är AES-256-GCM-krypterade under **`source/master.key`**. Varje köpkod
  wrappar nyckeln via PBKDF2 (150k iter). `codes.json` är ofarligt publikt.
- **Läs koder i `source/issued_codes.csv`** (klartext), INTE i codes.json.
- **Kartuppdateringar invaliderar aldrig koder** — samma master.key återanvänds.
- Byt ALDRIG normaliseringsregeln (`normalizeCode`/`normalize_code`) eller
  KDF-parametrarna — då slutar alla utfärdade koder gälla.
- **`source/master.key` måste säkerhetskopieras** (utan den går inga nya koder
  att skapa). Checka aldrig in den.
- Spärra kod: ta bort dess `label`-block ur codes.json + push. Slår igenom nästa
  gång enheten är online (offline-cachad nyckel lever kvar tills dess).

## Offline (service worker)
Efter upplåsning förladdar `sw.js` alla rutor (~18 MB) → hela kartan funkar
offline. App-skal + codes.json = network-first; rutor = cache-first.
`tiles-manifest.json` versionsstämplas per körning → ny karta laddas om
automatiskt hos användarna. Bumpa `SHELL_CACHE`-namnet i sw.js om app-skalet
behöver tvingas om.

## Testning
Riktig webbläsartest via Playwright (installerat lokalt, ej i git):
starta `py -3 -m http.server` i `docs/`, kör ett litet Playwright-skript mot
`http://localhost:...` (secure context → WebCrypto funkar). I Chromium
renderas allt korrekt; iOS-specifika saker (safe-area/helskärm) syns inte där.

## Status (uppdatera denna sektion löpande)
Senast: 2026-07-11 (kväll).
- Klart & live: karta, exakt inpassning, GPS, lagerväljare (Sjökort/Satellit,
  Esri World Imagery), kodskydd, hjälp-ruta, app-ikon, offline, köplänk.
- **Öppen punkt:** iOS helskärmsläge — remsa i nederkant. ORSAK DIAGNOSTISERAD
  med v13:s diagnostik (mörk body-bakgrund + teknisk info-rad i ?-rutan):
  användarens iPhone (390×844) rapporterade `fönster 390×797, synligt 390×797,
  skärm 390×844, safe-botten 34px` och remsan blev MÖRK + skärmdump visar
  kartan ända upp under klockan. Alltså: **iOS ankrar innehållet i skärmens
  överkant men gör layout-viewporten exakt statusfältshöjden (47 pt) för
  kort** → nedersta 47 pt blir bar sidbakgrund. Både innerHeight och
  visualViewport ljuger; screen.height är sann.
  **v14 FALSIFIERAD:** min-h 844px applicerades (tech-raden bekräftade) men
  remsan bestod, och Leaflet-attributionen (kartans nederkant) försvann ur
  bild → **iOS klipper webbvyn fysiskt vid 797 pt**; innehåll under linjen
  renderas aldrig, iOS fyller de nedersta 47 pt med sidans bakgrundsfärg.
  Webbvyn är alltså (skärm − statusfält) hög men placerad vid y=0 (innehållet
  låg under klockan) — buggen är kopplad till statusfältsläget
  `black-translucent`.
  **v15 FUNGERADE för nederkanten:** med `apple-mobile-web-app-status-bar-
  style: black` placeras vyn under statusfältet och kartan når skärmens
  botten (skärmdump bekräftar, attribution synlig). MEN: överkanten fick ett
  ljusblått fält bakom klockan — exakt `#cfe3ee` = #map:s bakgrundsfärg, dvs
  iOS tycks hämta statusfältets färg från sidan (inte svart som begärt).
  Användaren vill ha kartan ända ut även upptill.
  **v16 FALSIFIERAD (på iOS 26.5):** `black-translucent` +
  `height=device-height` i viewport-taggen gav toppen tillbaka (karta under
  klockan) men remsan i botten kom tillbaka. Tech-raden bekräftade att
  viewporten förblev 390×797 trots device-height — tricket biter inte
  längre. Telefonen kör **iOS 26.5**.
  **v17:** tech-raden i ?-rutan visar nu även OS-version (iOS/Android, ur
  user agent). OBS: på användarens iPhone med iOS 26.5 (enligt
  Inställningar) säger user agent "OS 18_7" — **Apple fryser versionen i
  UA:n**, så tech-radens OS-siffra är bara ungefärlig; Inställningar är
  facit.
  **v18 BEKRÄFTAD för botten:** webbsökning bekräftade att
  `black-translucent` är **deprecated hos Apple** (märkt för borttagning) →
  ingen fix att vänta på; på iOS 26.5 får man toppen ELLER botten
  kant-i-kant, aldrig båda. Valet: statusfältsläge `black` (=v15-läget).
  Efter användarens ominstallation: **botten fungerar, toppen ljusblå**
  (`#cfe3ee` = #map:s bakgrund — iOS hämtar färgen från sidans översta
  element). Användaren tycker ljusblått uppe är fel. VIKTIGT LÄRT:
  statusfälts-METAN kräver ominstallation, men v18-koden nådde appen via
  vanlig omladdning (network-first-SW funkar).
  **v19 FALSIFIERAD:** 1 px hög svart fast list överst (z 3000) tog INTE
  över statusfältsfärgen — listen rendererades bara som en tunn svart
  linje under det ljusblå fältet (skärmdump). Alltså: iOS läser varken
  översta elementet, synliga pixlar (login-skärmen är mörk men fältet
  ljusblått redan där) eller body/theme-color — sannolikt första elementet
  som FYLLER sidytan, dvs #map. Bonusbevis: v19 nådde appen via vanlig
  omstart, så sidinnehåll läses live (bara metataggar bakas vid install).
  **v20 (deployad, väntar på test):** #map:s background-color är nu SVART
  (→ statusfältet ska smälta ihop med notchen); vattenfärgen `#cfe3ee`
  utanför kortkanten flyttad till nytt lager `.map-water` (div skapad av
  app.js som första barn i kartcontainern, under Leaflet-panes z 400).
  Visuellt oförändrad karta. 1 px-listen borttagen. Test: force-quit +
  öppna igen; om fältet ändå är ljusblått → ominstallation; om ljusblått
  även då är fältfärgen något annat och vi återställer till #cfe3ee-fält
  (fullt acceptabelt utseende). Device-height-injektionen borttagen ur
  app.js (v18).
  Falsifierade spår (testa ALDRIG om): negativ bottom med env(safe-area-
  inset-bottom) (v11); max(innerHeight, visualViewport) (v13 — båda ljuger,
  rapporterar 797); min-height = screen.height (v14 — iOS klipper webbvyn
  fysiskt vid 797, innehåll under linjen renderas aldrig); viewport-taggen
  height=device-height (v16 — ignoreras på iOS 26.5).
  Tidigare falsifierat: negativ bottom med env(safe-area-inset-bottom) (v11 —
  insetet rapporteras men positioneringen utgår från den korta viewporten);
  max(innerHeight, visualViewport) (v13 — båda rapporterar 797); min-height =
  screen.height (v14 — innehåll under 797-linjen renderas aldrig).
- Två testkoder i drift (en generisk, en till Peter Eriksson). Se
  `source/issued_codes.csv` för klartext. Ta bort testkoder ur
  `docs/access/codes.json` före skarp försäljning.
- Mail till Peter Eriksson är skickat (2026-07-11).

<!-- Skriv ALDRIG köpkoder i klartext här (filen är publik i repot). -->

