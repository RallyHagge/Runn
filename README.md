# Sjökort Runn — webbaserad sjökortsvisare

En enkel webbsida som visar Runns Båtförbunds sjökort över Runn tillsammans med
din egen GPS-position. Fungerar i vanlig webbläsare på dator, iPhone och Android —
ingen app behöver installeras.

**Live:** https://rallyhagge.github.io/Runn/

## Funktioner

- **Kodskydd:** kartan öppnas med en unik köpkod (se "Sälja sjökortet" nedan).
- Sjökortet i full upplösning (laddas som "tiles" — bara det som syns hämtas).
- Lagerväljare uppe till höger: **Sjökort** eller **Satellit** (flygfoto).
- Knapp nere till höger som centrerar kartan på din position och följer dig.
- Kartan är exakt inpassad: originalet är omprojicerat till samma koordinatsystem
  som webbkartor använder (Web Mercator), så positionen stämmer i hela kartan.

## Så fungerar det tekniskt

Det här är en helt statisk webbsida (ingen server behövs). Allt ligger i mappen
`docs/` och publiceras gratis via **GitHub Pages**.

```
docs/
  index.html        # sidan
  app.js            # kartlogik (Leaflet) + GPS + upplåsning med kod
  style.css         # utseende
  chart/
    tiles/          # sjökortet i KRYPTERADE rutor (.bin), z8–z16  ← genereras
    bounds.json     # kartans geografiska hörn                     ← genereras
  access/
    codes.json      # inslagna nycklar, en per köpkod   ← uppdateras av mint_code.py
  vendor/leaflet/   # kartbiblioteket Leaflet (medföljer)
scripts/
  prepare_chart.py  # gör om en ny sjökortsexport till krypterade tiles + bounds.json
  mint_code.py      # skapar nya köpkoder
  access.py         # delade krypto-funktioner (används av de två ovan)
source/             # HEMLIGT, checkas ej in av git. Innehåller:
  chart.png/.pgw    #   originalbilden + world-fil
  master.key        #   huvudnyckeln (se nedan – säkerhetskopiera!)
  issued_codes.csv  #   liggare över utfärdade koder
```

## Uppdatera med en ny version av sjökortet

När Runns Båtförbund gör en ny utgåva av sjökortet gör man så här. Allt sköts av
ett enda skript, `scripts/prepare_chart.py`.

### 1. Engångsinstallation (första gången på en dator)

- Installera **Python 3** från https://www.python.org/ (bocka i "Add to PATH").
- Öppna en terminal i projektmappen och kör:
  ```
  py -3 -m pip install -r requirements.txt
  ```

### 2. Exportera sjökortet som en georefererad bild

Från kartprogrammet (t.ex. OCAD) exporteras kartan som en **bild med world-fil**:

- en `.png` (eller `.tif`) med själva kartbilden, och
- en world-fil bredvid med samma namn (`.pgw` för png, `.tfw` för tif) som
  innehåller kartans position/skala.

Notera vilket **koordinatsystem** exporten är i. För tidigare Runn-sjökort har det
varit **RT90 2,5 gon V**, vars EPSG-kod är **3021**. (Är exporten i SWEREF99 TM är
koden 3006; i WGS84/lat-long är den 4326.)

### 3. Lägg bilden i `source/` och kör skriptet

Lägg bild + world-fil i mappen `source/`, döp dem gärna till `chart.png`/`chart.pgw`,
och kör (byt ut `--epsg 3021` mot rätt kod om exporten bytt system):

```
py -3 scripts/prepare_chart.py source/chart.png --epsg 3021 --tiles --encrypt
```

Skriptet skriver om `docs/chart/tiles/` (krypterat) och `docs/chart/bounds.json`.
Det tar en minut eller två och skriver ut hur många rutor som skapades.
Redan utfärdade koder fortsätter fungera efteråt (samma huvudnyckel återanvänds).

### 4. Publicera

Ladda upp ändringen till GitHub (via GitHub Desktop eller kommandoraden):

```
git add docs/chart
git commit -m "Uppdatera sjökortet till <årtal>-utgåvan"
git push
```

Efter någon minut är den nya kartan live på sidan. Om din egen webbläsare visar den
gamla kartan: stäng fliken helt och öppna igen (den cachar ibland).

## Sälja sjökortet — köpkoder

Kartan är krypterad. Varje köpare får en **unik kod** som låser upp den i
webbläsaren. Ingen inloggning, inga konton, ingen koppling till mail.

### Skapa en kod till en köpare

När någon swishat, kör:

```
py -3 scripts/mint_code.py --note "Köparens namn eller Swish-ref"
```

Skriptet skriver ut en kod, t.ex. `RUNN-A7K9-2FMP-QX34`. **Skicka den koden till
köparen via SMS eller mail.** Publicera sedan den uppdaterade kodlistan:

```
git add docs/access/codes.json
git commit -m "Ny köpkod"
git push
```

Efter någon minut fungerar koden på sidan. Köparen skriver in den en gång; den
sparas sedan i webbläsaren och fungerar på alla köparens egna enheter.

Skapa flera koder samtidigt med `--count`, t.ex. `--count 20`.

Alla utfärdade koder antecknas i `source/issued_codes.csv` (din privata liggare).

### Spärra en kod

1. Slå upp koden i `source/issued_codes.csv` och notera dess `label` (t.ex.
   `2026-07-10 #3`).
2. Öppna `docs/access/codes.json`, ta bort det block i `entries` som har samma
   `label`, spara.
3. `git add docs/access/codes.json && git commit -m "Spärra kod" && git push`.

Koden slutar då fungera för nya inloggningar. (Obs: någon som redan låst upp på
sin enhet har kvar kartan tills de rensar webbläsardata — full återkallning
kräver ny huvudnyckel, se nedan.)

### VIKTIGT: huvudnyckeln `source/master.key`

Filen `source/master.key` är den hemliga nyckel som allt bygger på.

- **Säkerhetskopiera den** på ett säkert ställe (t.ex. föreningens lösenordskvalv).
  Utan den kan du inte skapa nya koder, och alla befintliga koder slutar gå att
  förnya.
- **Checka aldrig in den** i git och dela den inte publikt. (Den ligger i `source/`
  som är utesluten från git.)
- Vill du **byta nyckel** helt (t.ex. om en gammal utgåva läckt): radera
  `master.key`, kör `prepare_chart.py ... --encrypt` igen (skapar ny nyckel +
  krypterar om allt) och utfärda nya koder. Gamla koder slutar då fungera.

## GitHub Pages-inställning (redan gjord)

Sidan publiceras från `master`-grenen, mappen `/docs`
(Settings → Pages → Deploy from a branch). Detta behöver bara sättas en gång.

## Hur kodskyddet fungerar (kort teknisk översikt)

Sidan är statisk (ingen server). Kartrutorna krypteras med en huvudnyckel med
AES-256-GCM. Varje köpkod "slår in" (wrappar) huvudnyckeln via nyckelhärledning
(PBKDF2) — de inslagna kopiorna i `docs/access/codes.json` är ofarliga att
publicera, de är värdelösa utan en giltig kod. I webbläsaren packas nyckeln upp
när rätt kod skrivs in, och rutorna dekrypteras lokalt.

Det skyddar mot att någon utan kod bara hämtar kartan. Det kan däremot – precis
som en utskickad OCAD-fil – inte hindra en betalande kund från att medvetet dela
kartan vidare. Vill man låsa en kod till en enskild enhet krävs en server-lösning
(t.ex. Cloudflare Workers); hör av dig så kan det byggas till utan att resten görs om.

## Attribution / licenser

- Sjökort © Runns Båtförbund, Sjökortssektionen.
- Kartbibliotek: [Leaflet](https://leafletjs.com/).
- Satellitlagret: Esri World Imagery (visas med attribution i kartans hörn — låt
  den stå kvar, den krävs enligt Esris villkor).
