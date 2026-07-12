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
# OBS: uppdatera även CHART_EDITION i docs/app.js (visas i attribution + ?-rutan)
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
Kartobjektet exponeras som `window.runnMap` (testkrok, inget känsligt i det) —
t.ex. `runnMap.getZoom()`. OBS: i en DOLD flik (t.ex. Claude Codes
browserpanel: `document.hidden === true`, rAF körs aldrig) fullbordas inga
ANIMERADE kartoperationer — testa med `{ animate: false }` där. Upplåsning i
test: fyll `#login-code` med en giltig kod (source/issued_codes.csv), dispatcha
`input` + `submit`.

## iOS helskärm (invariants — LÖST 2026-07-12 efter v11–v20, ändra inte!)
Testat på iPhone 390×844 med iOS 26.5. Tre saker är bärande och hänger ihop:
1. **`apple-mobile-web-app-status-bar-style: black`** (index.html). ALDRIG
   `black-translucent`: det är deprecated hos Apple och ger en död, oåtkomlig
   47 pt-remsa i skärmens NEDERKANT (webbvyn görs statusfältshöjden för kort
   men ankras i överkant; innehåll under linjen renderas aldrig).
2. **`#map { background: #000 }`** (style.css). iOS färgar statusfältet efter
   bakgrundsfärgen hos första elementet som fyller sidytan (= #map) — svart
   fält smälter ihop med notchen. Inte theme-color, inte body, inte synliga
   pixlar, inte översta elementet (1 px-list testad) — bara denna.
3. **`.map-water`** (div, skapas i app.js som första barn i kartcontainern):
   bär den ljusblå vattenfärgen `#cfe3ee` utanför sjökortets kant, under
   Leaflet-panes (z 400). Utan den syns #map:s svarta bakgrund i kartan.
Falsifierat (testa ALDRIG om): negativ bottom med env(safe-area-inset-bottom)
(v11); max(innerHeight, visualViewport) som min-höjd (v13 — båda ljuger,
rapporterar skärm−47); min-height = screen.height (v14 — webbvyn klipps
fysiskt); viewport-taggen height=device-height (v16 — ignoreras numera);
1 px-list överst för statusfältsfärgen (v19).
Bra att veta: statusfälts-METAN läses bara när appen läggs på hemskärmen
(ändring ⇒ användare måste ominstallera hemskärmsappen), men HTML/JS/CSS når
appen via vanlig omstart (network-first-SW). ?-rutans tech-rad visar version
+ viewportmått; dess OS-siffra kommer ur user agent som Apple fryser (visar
"18.7" på iOS 26.5) — Inställningar är facit. iPhone-mått: statusfält 47 pt,
hemindikator-inset 34 pt.

## Status (uppdatera denna sektion löpande)
Senast: 2026-07-12.
- Klart & live: karta, exakt inpassning, GPS, lagerväljare (Sjökort/Satellit,
  Esri World Imagery), kodskydd, hjälp-ruta, app-ikon, offline, köplänk,
  iOS helskärm (se invariants-sektionen ovan; bekräftad av användaren på
  riktig iPhone: svart statusfält uppe, kartan ända ner i botten).
- Hemskärmsinstruktionerna i ?-rutan (v23): iOS-enheter ser bara Safari-
  stegen, Android bara Chrome-stegen, och datorer ser inget hemskärmsavsnitt
  alls (rubrik + ingress + listor döljs).
- Tech-raden i ?-rutan (v24): ligger allra sist i rutan (efter reset-länken)
  och visar även webbläsare + version (Safari/Chrome/Firefox/Edge ur user
  agent; i iOS helskärm saknar UA:n webbläsarnamn → visar "Safari").
- Om-/hjälprutan (v22): visar sjökortets utgåva (`CHART_EDITION` i app.js —
  samma konstant som kartans attribution) samt enhetens aktiveringskod
  strax ovanför reset-länken (användarens önskemål: så kan man slå upp sin
  kod på en aktiverad enhet för att aktivera fler). Kodraden döljs när ingen
  komplett kod finns sparad. Ett tryck på koden markerar hela (user-select:
  all) för enkel kopiering.
- Knapplayout för VÄNSTERHANDS-manövrering (v21, användarens önskemål):
  nere från vänster: Aktuell plats (x14), zooma in (x74), zooma ut (x134) —
  egna runda knappar; Leaflets zoomkontroll avstängd (`zoomControl: false`).
  Hjälp-knappen (?) nere till höger. Ändra inte utan användarens ok.
- Två testkoder i drift (en generisk, en till Peter Eriksson). Se
  `source/issued_codes.csv` för klartext. **Användarens beslut 2026-07-12:
  koderna får ligga kvar permanent** — ta INTE bort dem ur
  `docs/access/codes.json`.
- Mail till Peter Eriksson är skickat (2026-07-11).

<!-- Skriv ALDRIG köpkoder i klartext här (filen är publik i repot). -->

