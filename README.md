# Forever AH Flip

Auktionshausdaten aus **World of Warcraft: Forever** auswerten - im Browser, ohne Installation,
ohne Upload.

Drei Datenquellen:

| Quelle | Was sie liefert |
|---|---|
| **Battle.net-API** (`collector/`) | Jede einzelne Auktion aller Auktionshaeuser, stuendlich, ohne dass ein Rechner laufen muss. Im Aufbau. |
| **TSM Desktop App** (`AppData.lua`) | Marktwerte, Historie und *Verkaeufe pro Tag* fuer ~7.000 Items. Braucht den eigenen PC. |
| **Eigener Scan** (`addon/AHDump`) | Momentaufnahme mit Verkaeufernamen. Nur wenn man selbst am Auktionator steht. |

| Teil | Was es macht |
|---|---|
| `collector/` | Python-Paket: sammelt ueber die Battle.net-API und baut die Dateien fuer die Anzeige. |
| `web/` | Die Oberflaeche: React, TypeScript, Vite, shadcn/ui. Markttabelle und Preisverlauf. |
| `viewer/index.html` | Aelterer Einzeldatei-Viewer fuer TSM-Daten und eigene Dumps, ohne Verlauf. |
| `addon/AHDump` | In-Game-Addon. `/ahdump` macht einen Full-Scan des Auktionshauses. |
| `tools/Convert-AHDump.ps1` | Optional: macht aus `AHDump.lua` eine CSV fuer Excel, Pandas & Co. |

## Sammler ueber die Battle.net-API

Blizzard veroeffentlicht die Forever-Auktionshaeuser seit dem 6. November 2026 selbst. Forever
hat keine Realms, sondern Rulesets, und je Ruleset 15 Auktionshaeuser:

```
/data/wow/ruleset/index                   Namespace dynamic-forever-<region>
/data/wow/ruleset/{id}
/data/wow/ruleset/{id}/auctions/          Index der Haeuser, Schraegstrich am Ende noetig
/data/wow/ruleset/{id}/auctions/{haus}    jede einzelne Auktion, bis ~9 MB
```

Die Pfade sind von der Community kartiert, nicht von Blizzard dokumentiert. **Ohne gueltigen
Token antwortet die API auf jeden Pfad mit 404** - auch auf Pfade, die es sicher gibt. Ein 404
sagt also nur mit Token etwas aus. Genau dafuer gibt es `verify`.

Was die API tatsaechlich liefert - Rulesets, alle 15 Auktionshaeuser mit Fraktion und
Groesse, die Felder einer Auktion, Stapelware, Antwortzeiten - steht gemessen in
[`docs/forever-api.md`](docs/forever-api.md). Kurz: `quantity` ist bei normalen Auktionen
immer 1, Stapelware liegt auf einem eigenen Endpunkt, die Ruleset-ID im Pfad filtert nichts,
und die Daten werden stuendlich um :19 neu gebaut.

### Gesammelt wird ein Haus

**Haus 114, Auktionshaus der Horde im Ruleset Normal** - PvE Horde. Aenderbar ueber
`FOREVER_HOUSE`.

Ein Durchlauf holt Auktionen und Stapelware, verdichtet beides und schreibt je Stand eine
Datei, die danach nie wieder angefasst wird (Zeiten in UTC):

```
data/warehouse/                                  = Branch `data`
  items/house=114/dt=2026-11-17/081855.parquet   je Item eine Zeile: Angebote, Menge,
                                                 guenstigster Preis, p25, Median, Gebote
  sales/house=114/dt=2026-11-17/081855.parquet   je Item: verkauft, abgelaufen, unklar, neu
  runs/house=114/dt=2026-11-17/081855.parquet    eine Zeile Protokoll
  latest/house=114.json                          Zeiger auf den juengsten Stand
data/state/house114.parquet                      rohe Momentaufnahme, nur bis zum naechsten Lauf
```

160.000 bis 270.000 Auktionen werden so zu gut 6.000 Zeilen und 100 KB je Stand, rund
2,4 MB am Tag. Die rohen Einzelauktionen bleiben nicht liegen - sie werden nur gebraucht,
um zwei aufeinanderfolgende Staende zu vergleichen.

Eine Datei je Stand statt einer wachsenden Tagesdatei ist Absicht: das Warehouse liegt in
Git, und eine Datei, die 24-mal am Tag neu geschrieben wird, legt 24-mal ihren Inhalt in die
Historie.

### Betrieb in GitHub Actions

Der Workflow [`collect`](.github/workflows/collect.yml) laeuft dreimal je Stunde
(`2,22,42 * * * *`). Blizzard baut die Daten stuendlich gegen :19 neu; der erste Versuch
kommt kurz danach, die anderen fangen Verspaetungen des Schedulers ab. Gibt es nichts
Neues, schickt der Sammler `If-Modified-Since`, bekommt `304` und schreibt nichts.

| Was | Wo |
|---|---|
| Code | Branch `main` |
| Daten | Branch `data`, ohne gemeinsame Historie mit `main`, ein Commit je Stand |
| Vergleichsstand | Actions-Cache (`state-...`), weil er sich jedes Mal komplett aendert |
| Zugangsdaten | Repository-Secrets `BLIZZARD_CLIENT_ID` und `BLIZZARD_CLIENT_SECRET` |

Geht der Cache verloren, fehlen fuer genau einen Stand die Verkaeufe - Preise und Mengen
sind davon nicht betroffen.

Der Workflow checkt vom Branch `data` nur `latest/` aus, nicht den Bestand. Sonst wuerde
jeder Lauf alles herunterladen, was je gesammelt wurde. Der Sammler liest aus
`latest/house=114.json`, welcher Stand der juengste ist, und `git add --sparse` nimmt die
neuen Dateien auf, obwohl sie ausserhalb des ausgecheckten Ausschnitts liegen.

Git als Datenspeicher ist eine Uebergangsloesung: der Branch waechst um rund 1,3 GB im
Jahr, und GitHub raet, unter 1 GB zu bleiben. Weil jede Datei unveraendert bleibt und
`data` keine gemeinsame Historie mit `main` hat, ist der Ausstieg einfach - Dateien in
einen Objektspeicher kopieren, Branch loeschen.

Ohne Git lesen geht auch, jede Datei ist direkt abrufbar (Teilabrufe und CORS inklusive,
bis zu fuenf Minuten zwischengespeichert):

```
https://raw.githubusercontent.com/jofri99/forever-ah-flip/data/latest/house=114.json
https://raw.githubusercontent.com/jofri99/forever-ah-flip/data/items/house=114/dt=2026-11-17/091854.parquet
```

Die Daten lokal haben:

```powershell
git fetch origin data
git worktree add data/warehouse data      # einmalig
git -C data/warehouse pull                # danach zum Aktualisieren
```

Lokal sammelt man dann besser nicht in dasselbe Verzeichnis, sonst kollidieren die Dateien
beim naechsten `pull`. Fuer Experimente: `$env:AH_DATA_DIR = "data/dev"`.

### Stammdaten der Items

Die Auktionsdaten kennen nur Item-IDs. `names` holt dazu alles, was Blizzards statische API
(`static-forever-eu`) hergibt - auf Englisch, damit die Namen zu denen anderer Quellen
passen. Die Sprache steht in `BLIZZARD_LOCALE`; wird sie geaendert, holt `names` die
betroffenen Items von selbst neu:

```powershell
python -m collector names              # alle noch ungeprueften Items
python -m collector names --limit 500
```

| Spalte | Inhalt |
|---|---|
| `name`, `quality` | Name, Qualitaet (`COMMON`, `RARE`, ...) |
| `sell_price` | was ein Haendler zahlt, in Kupfer |
| `purchase_price`, `purchase_quantity` | Listenpreis beim Haendler und fuer wie viele Stueck |
| `item_class`, `item_subclass`, `inventory_type` | Einordnung und Ausruestungsplatz |
| `level`, `required_level`, `is_stackable`, `is_equippable`, `max_count` | weitere Eckdaten |
| `icon` | Adresse des Icons |
| `raw` | die vollstaendige Antwort als JSON: Ruestung, Schaden, Attribute, Haltbarkeit, Anforderungen |
| `locale` | in welcher Sprache `name` und `raw` abgerufen wurden |

Abgelegt wird je Tag eine Datei, `ref/items/dt=2026-11-17.parquet`, mit den an dem Tag
geprueften IDs. Was keine eigene Spalte hat, laesst sich aus `raw` ziehen:

```sql
SELECT name, raw->>'$.preview_item.armor.value' AS ruestung
FROM read_parquet('data/warehouse/ref/items/*.parquet')
WHERE status = 200 AND inventory_type = 'WRIST';
```

Zwei Dinge sollte man wissen:

- **Die API kennt nur gut die Haelfte.** Von 6.572 Items im Markt fand sie 3.773: bei den
  alten IDs 52 %, bei den neuen Forever-Items 83 %. Auch Fehlanzeigen (`status = 404`) werden
  abgelegt, damit sie nicht stuendlich neu abgefragt werden; nach einer Woche gibt es einen
  neuen Versuch.
- **`purchase_price` ist ein Listenpreis.** Er steht bei jedem Item, auch wenn es kein
  Haendler fuehrt. Ob und wo es etwas zu kaufen gibt, weiss diese API nicht.

In Actions traegt der Workflow nach jedem neuen Stand die Stammdaten neu aufgetauchter Items
nach. `publish` schreibt daraus `names.json` und haengt `vendor_sell` und `vendor_buy` (je
Stueck) an `market.parquet`.

### ForeverDB als zweite Quelle

[ForeverDB](https://foreverdb.net/developers) kennt, was Blizzards API fehlt: im Markt waren
alle 2.735 Luecken dort vorhanden, ueberwiegend Ausruestung. Der Schluessel steht als
`FOREVERDB_API_KEY` in der `.env`.

```powershell
python -m collector foreverdb                    # die Item-Liste, 238 Anfragen
python -m collector foreverdb vendors quests     # weitere Listen
python -m collector foreverdb items --max-requests 50
python -m collector foreverdb-details            # Details der Items, die Blizzard nicht kennt
python -m collector foreverdb-details --scope market --max-requests 500
```

Abgelegt wird unter `data/local/foreverdb/`, eine Zeile JSON je Eintrag. Der Abzug haelt
2,2 Sekunden Abstand zwischen den Anfragen, speichert nach jeder Seite und macht nach einem
Abbruch dort weiter. Gemessen an der API:

- Die Liste gibt hoechstens 100 Eintraege je Anfrage her, mehr wird mit 400 abgelehnt.
- Details wie Haendlerpreis, Attribute, Effekte, Bindung und Entzauberung gibt es nur einzeln,
  eine Anfrage je Item. `foreverdb-details` holt sie in `item_details.jsonl`, die
  meistgehandelten Items zuerst, schreibt jedes sofort weg und ueberspringt beim naechsten
  Lauf, was schon da ist. Fuer die rund 2.800 Luecken im Markt sind das gut 100 Minuten.
- Nicht alles dort ist fuer Forever bestaetigt. Die Entzauberungs-Ergebnisse etwa tragen den
  Vermerk `Classic data (CMaNGOS), not confirmed in Forever`.
- Erlaubt sind 30 Anfragen je Minute und 5.000 am Tag.

Drei Regeln des Anbieters bestimmen, wohin diese Daten duerfen:

- Ein persoenlicher oder Plugin-Schluessel darf nicht auf einer Website eingesetzt werden.
  Fuer eine oeffentliche Seite braucht es einen Website-Schluessel.
- Der Schluessel gehoert nie in ausgelieferten Code.
- Die Antworten sind mit dem Schluessel markiert, eine Weiterveroeffentlichung ist
  nachverfolgbar.

Darum liegt der Abzug in `data/local/` und nicht im Warehouse: er verlaesst diesen Rechner
nicht. `publish` nimmt die Namen von dort nur als Lueckenfueller, wenn der Abzug vorhanden
ist - in Actions also nie. Die oeffentliche Seite zeigt damit nur Blizzards Namen.

### Lokale Datenbank

Staende, Stammdaten und der Abzug von ForeverDB liegen in verschiedenen Formaten an
verschiedenen Orten. `db` legt eine DuckDB-Datei darueber, in der sich alles mit SQL
verknuepfen laesst:

```powershell
python -m collector db                                   # baut data/local/forever.duckdb
python -m collector sql "SELECT * FROM latest LIMIT 10"  # Abfrage ohne weiteres Werkzeug
python -m collector sql --file abfrage.sql --rows 200
```

Die Datei enthaelt keine Daten, nur Sichten auf die vorhandenen Dateien. Nach einem
`git -C data/warehouse pull` oder einem neuen Abzug ist sie deshalb ohne Neubau aktuell, und
es gibt keine zweite Kopie, die veralten koennte. Neu gebaut werden muss sie nur, wenn sich
die Sichten aendern oder das Projekt in einen anderen Ordner zieht.

| Sicht | Inhalt |
|---|---|
| `snapshots` | jeder Stand jedes Items: Angebote, Menge, Preise |
| `sales` | Verkaeufe, Ablaeufe und Neuzugaenge zwischen zwei Staenden |
| `runs` | Protokoll der Sammellaeufe |
| `blizzard_items` | Stammdaten aus Blizzards API, `raw` als JSON |
| `foreverdb_items` | die Item-Liste von ForeverDB; weitere Listen als `foreverdb_vendors` usw. |
| `foreverdb_item_details` | einzeln abgezogene Details: Haendlerpreis, Attribute, Bindung, Entzauberung |
| `items` | beide Quellen zusammengefuehrt: Blizzard gilt zuerst, ForeverDB fuellt auf - auch den Haendlerpreis |
| `latest` | der juengste Stand mit Namen und Haendlerpreisen |
| `history` | `snapshots` mit Namen und den Verkaeufen seit dem Stand davor |
| `sold_daily` | Verkaeufe je Item und Tag, mit `hours_covered` |

Dazu zwei Helfer: `money(123456)` ergibt `12g 34s 56c`, `gold(123456)` ergibt `12.35`.

```sql
-- Was hat sich heute am meisten verkauft?
SELECT name, qty_sold, money(value_sold) AS umsatz, hours_covered
FROM sold_daily WHERE day = current_date ORDER BY value_sold DESC LIMIT 20;

-- Angebote unter dem, was ein Haendler zahlt
SELECT name, n_listings, money(min_price) AS angebot, money(vendor_sell) AS haendler
FROM latest WHERE vendor_sell > min_price ORDER BY vendor_sell - min_price DESC;

-- In die vollstaendige Antwort greifen
SELECT name, raw->>'$.preview_item.armor.value' AS armor
FROM blizzard_items WHERE inventory_type = 'CHEST' AND quality = 'RARE';
```

Die Datei laesst sich auch mit DBeaver, der DuckDB-Kommandozeile oder einer
DuckDB-Erweiterung fuer VS Code oeffnen. DuckDB erlaubt dabei nur ein Programm, das schreibt:
solange ein anderes die Datei offen hat, schlaegt `db` fehl und sagt das.

### Dateien fuer die Anzeige

Eine Datei je Stand ist gut zum Sammeln und schlecht zum Anzeigen: der Verlauf eines Items
ueber 14 Tage laege in 336 Dateien. `publish` baut daraus eine Form, die ein Browser mit
wenigen Teilabrufen lesen kann:

```powershell
python -m collector publish            # 14 Tage nach web/public/data
python -m collector publish --days 30
```

| Datei | Inhalt |
|---|---|
| `hourly.parquet` | alle Staende des Zeitfensters mit Preisen, Mengen und Verkaeufen, nach Item sortiert und in Zeilengruppen von 8192 geschnitten |
| `market.parquet` | der juengste Stand, eine Zeile je Item, dazu Tief, Hoch, Veraenderung und Verkaeufe der letzten 24 Stunden |
| `meta.json` | Zeitraum, Anzahl Staende, Dateigroessen |

Wer ein Item will, liest am Ende von `hourly.parquet` nach, in welcher Zeilengruppe es
liegt, und holt nur die. Zeit steht als Unix-Sekunden drin, Preise als `DOUBLE` - beides
kommt im Browser als gewoehnliche Zahl an. Komprimiert wird mit Snappy, weil schlanke
Parquet-Leser das ohne Zusatzpaket verstehen.

`sales_hours_24h` in `market.parquet` sagt, wie viele der letzten 24 Stunden durch
Vergleiche gedeckt sind. Steht dort 6, sind die Verkaufszahlen ein Viertel der Wahrheit.

Die Dateien sind abgeleitet und jederzeit neu baubar, `web/public/data/` steht deshalb in
`.gitignore`.

### Die Oberflaeche

`web/` ist eine React-App: TypeScript, Vite, Tailwind und shadcn/ui. Sie zeigt den Markt
als Tabelle und den Preisverlauf eines Items als Diagramm. Gebraucht wird Node.js.

```powershell
git -C data/warehouse pull          # frische Daten holen
python -m collector publish         # Dateien fuer die Anzeige bauen
cd web
npm install                         # einmalig
npm run dev                         # http://localhost:5173
```

- Die Tabelle laesst sich nach jeder Spalte sortieren, nach Name oder ID durchsuchen und
  auf Einzelstuecke oder Stapelware einschraenken. Fehlende Werte stehen immer am Ende.
  Von den gut 6.000 Zeilen stehen nur die sichtbaren im Dokument.
- Ein Klick oder Enter auf einer Zeile oeffnet den Verlauf: guenstigster Preis, Median und
  darunter die verkaufte Menge je Stand - oder die Zahl der Angebote, solange es keine
  Verkaufsdaten gibt.
- Die Adresse merkt sich das Item (`#12359:commodity`). Ein Verlauf laesst sich verlinken,
  und die Zurueck-Taste schliesst ihn wieder.
- Zeiten stehen in Ortszeit. Hell und dunkel folgen dem System, der Knopf oben rechts
  oder die Taste `d` schaltet um.

```
web/src/
  lib/data.ts        liest meta.json, market.parquet und gezielt aus hourly.parquet
  lib/rows.ts        Filtern und Sortieren als reine Funktionen
  lib/format.ts      Gold/Silber/Kupfer, Prozente, Ortszeit fuer das Diagramm
  components/        Tabelle, Detailansicht, Diagramm; ui/ kommt von shadcn
  hooks/             das gewaehlte Item in der Adresse
```

Das Diagramm zeichnet TradingViews `lightweight-charts`, die Parquet-Dateien liest
`hyparquet`. Die Diagramm-Bibliothek wird erst geladen, wenn jemand ein Item oeffnet. Sie
steht unter Apache-2.0 und verlangt die Namensnennung samt Link, die im Diagramm und in
der Fusszeile steht.

Der Entwicklungsserver von Vite beantwortet Teilabrufe - ohne die muesste die Seite fuer
jedes Diagramm die ganze `hourly.parquet` laden. `python -m http.server` kann das nicht.

Die Oberflaeche ist englisch beschriftet. Namen kommen aus `names.json`; wo weder Blizzard
noch ein lokaler Abzug von ForeverDB einen kennt, steht `Item 2589` da. Die Detailansicht zeigt ausserdem, was ein Haendler zahlt, und weist darauf
hin, wenn das guenstigste Angebot darunter liegt.

### Wie Verkaeufe entstehen

Auktionen haben IDs. Verschwindet eine zwischen zwei Staenden, wird sie danach eingeordnet,
wie viel Restzeit sie zuletzt hatte:

| zuletzt gesehen | Restzeit | nach einer Stunde verschwunden |
|---|---|---|
| `VERY_LONG` | ueber 12 h | **verkauft** - ablaufen konnte sie nicht |
| `LONG` | 2 bis 12 h | **verkauft** |
| `MEDIUM` | 30 min bis 2 h | **unklar** - koennte auch abgelaufen sein |
| `SHORT` | unter 30 min | **abgelaufen** |

Die Grenzen haengen am Abstand der Staende: liegen drei Stunden dazwischen, zaehlt `LONG`
nicht mehr als verkauft. Stornierte Auktionen sind von gekauften nicht zu unterscheiden und
laufen unter "verkauft" mit.

Warum nicht weiter TSM: dessen Daten sind Aggregate je Item, nur fuer die eigenen
Realm-Fraktionen und bis zu eine Stunde alt. Die API liefert jede Auktion mit ihrer ID - und
weil Auktions-IDs ueber zwei Abrufe hinweg vergleichbar sind, laesst sich daraus selbst
ausrechnen, was verkauft wurde statt nur abgelaufen ist.

## Schnellstart mit TSM-Daten

Wer die TSM Desktop App laufen hat, braucht sonst nichts:

1. `viewer/index.html` im Browser oeffnen
2. `Interface\AddOns\TradeSkillMaster_AppHelper\AppData.lua` hineinziehen

Die App schreibt diese Datei etwa stuendlich neu - einfach erneut hineinziehen.

### Was in AppData.lua steht

Pro Realm-Fraktion (also nur dort, wo man Chars hat) und pro Region:

| Feld | Bedeutung |
|---|---|
| `minBuyout` | guenstigster Sofortkauf beim letzten Scan |
| `numAuctions` | Anzahl Auktionen beim letzten Scan |
| `marketValue` / `marketValueRecent` | Marktwert des Realms |
| `historical` | Mittelwert ueber die letzten Wochen |
| `regionMarketValue` / `regionHistorical` | dasselbe regionsweit |
| `regionSale`, `regionSoldPerDay`, `regionSalePercent` | tatsaechliche Verkaeufe: Durchschnittspreis, Stueck pro Tag, Anteil der Auktionen, die verkauft werden |

Die Zahlen liegen base-32-kodiert vor (grosse Werte zweigeteilt, `lower + upper * 2^30`), der
Viewer dekodiert sie wie TSM selbst. `regionSoldPerDay` und `regionSalePercent` sind mit 1000
multipliziert gespeichert.

### Ansicht "Deals"

Items, deren guenstigstes Angebot deutlich unter dem Marktwert liegt **und** die sich auch
verkaufen:

```
Marge pro Stueck = Marktwert * 0,95 - guenstigster Sofortkauf
Rabatt           = 1 - guenstigster Sofortkauf / Marktwert
Potenzial        = Marge pro Stueck * Verkaeufe pro Tag (Region)
```

Das Potenzial ist nur eine Rangfolge, kein versprochener Gewinn - es unterstellt, man wuerde
den gesamten Regionsumsatz selbst machen. Nuetzlich ist es trotzdem: 300 % Marge auf etwas,
das zweimal im Monat verkauft wird, ist kein Geschaeft.

Ueber `min. verkauft/Tag` und `min. Rabatt %` laesst sich filtern.

### Grenzen der TSM-Daten

- **Keine einzelnen Auktionen.** `minBuyout` ist eine Zahl pro Item. Man weiss, dass etwas
  guenstig *war* - nicht von wem, in welcher Stackgroesse, wie lange noch.
- **Bis zu eine Stunde alt.** Die Kopfzeile zeigt den Stand des letzten Scans.
- **Nur eigene Realms und Fraktionen.** Wo man keinen Char hat, gibt es keine Daten.
- Verkaufszahlen gibt es nur regionsweit, nicht pro Realm.

### Item-Namen

TSM speichert nur Item-IDs. Der Knopf **Item-Namen laden** holt die Namen fuer die gerade
angezeigten Zeilen von `wowhead.com` (nur die Item-ID geht raus) und legt sie im
`localStorage` ab. Das ist der einzige Netzzugriff der Seite und passiert nur auf Klick -
ohne ihn steht in der Spalte `Item 12359`, der Link zu Wowhead funktioniert trotzdem.
Items, die es nur in Forever gibt, kennt Wowhead nicht.

## Eigener Scan

### Technischer Hintergrund

Forever (`WOW_PROJECT_CAMELOT`, Interface **16001**) nutzt die **moderne** UI-Architektur von
Mainline, nicht die von Classic Era. Das Auktionshaus laeuft also ueber `C_AuctionHouse` und
damit ueber `C_AuctionHouse.ReplicateItems()`, den vollstaendigen AH-Abzug in einem Rutsch.
Addons fuer Classic Era (Interface 11500er) funktionieren hier nicht.

### Addon installieren

1. Ordner `addon/AHDump` nach `<WoW>\_forever_\Interface\AddOns\AHDump` kopieren
2. WoW **neu starten** - ein neu angelegtes Addon wird von `/reload` nicht erkannt
3. In der Addon-Liste aktivieren

### Dump erstellen

```
1. Zum Auktionator gehen, Auktionshaus oeffnen
2. /ahdump          -> Full-Scan, dauert 10-60 Sekunden
3. /reload          -> erst jetzt schreibt WoW die Datei
```

Ergebnis: `<WoW>\_forever_\WTF\Account\<ACCOUNT>\SavedVariables\AHDump.lua` - ebenfalls in den
Viewer ziehen.

Weitere Befehle:

- `/ahdump info` - zeigt Zeitpunkt und Umfang des letzten Dumps
- `/ahdump clear` - leert die Daten, damit die Datei nicht unnoetig waechst

**Rate-Limit:** `ReplicateItems()` ist serverseitig stark gedrosselt, realistisch einmal
alle ca. 15 Minuten. Kommt nach zwei Minuten keine Antwort, meldet das Addon das und man
versucht es spaeter erneut.

### Ansichten

- **Pro Item** - ein Eintrag je Item: Anzahl Auktionen, Gesamtmenge, guenstigster Stueckpreis, Median
- **Flip-Kandidaten** - Items, bei denen das guenstigste Angebot unter dem Median der uebrigen liegt
- **Alle Auktionen** - der rohe Dump, sortier- und durchsuchbar

```
Marktpreis = Median der Stueckpreise ohne das guenstigste Angebot
Marge      = Marktpreis * 0,95 - guenstigster Stueckpreis
```

Das ist bewusst eine einfache Heuristik und sagt nichts darueber, ob sich ein Item auch
verkauft - dafuer sind die TSM-Daten da.

### Datenformat

Eine Zeile je Auktion, Preise in **Kupfer**:

| Spalte | Bedeutung |
|---|---|
| `index` | laufende Nummer im Scan |
| `itemID` | Item-ID |
| `itemString` | `item:...`-String inkl. Suffix/Verzauberung |
| `name` | Item-Name (leer, wenn der Client die Daten nicht rechtzeitig nachgeladen hat) |
| `quality` | 0 = grau ... 5 = orange |
| `count` | Stackgroesse bzw. Menge |
| `minBid` | Mindestgebot |
| `buyout` | Sofortkauf |
| `bidAmount` | aktuelles Gebot, 0 = keins |
| `owner` | Verkaeufer |
| `timeLeft` | 1 = kurz ... 4 = sehr lang |
| `level` | Itemlevel bzw. benoetigtes Level |
| `isCommodity` | 1 = Stapelware, `buyout` ist ein **Stueckpreis**; 0 = normale Auktion, `buyout` gilt fuer den **ganzen Stack**; leer = unbekannt |

`isCommodity` ist wichtiger, als es zuerst aussah. TSMs `AppData.lua` hat einen leeren
Commodity-Datensatz, was nach "Forever kennt keine Stapelware" aussieht - die Battle.net-API
zeigt aber allein in einem Auktionshaus 129.321 Commodity-Auktionen. Der leere Datensatz ist
eine Eigenart von TSM, keine Eigenschaft des Spiels.

### CSV erzeugen (optional)

```powershell
.\tools\Convert-AHDump.ps1
```

Sucht die zuletzt geschriebene `AHDump.lua` selbst und legt die CSV daneben.
Mit `-Path` / `-WowPath` / `-Out` laesst sich alles explizit angeben.

## Entwicklung

Gebraucht wird Python 3.13 (`py -V`). Alles andere steckt in zwei Dateien.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Zugangsdaten holen: auf <https://develop.battle.net/access/clients> einen Client anlegen
(kostenlos, Battle.net-Login, Redirect-URL darf `https://localhost` sein). Dann:

```powershell
Copy-Item .env.example .env
```

Client-ID und Secret dort eintragen. `.env` steht in `.gitignore` und gehoert nie ins Repo.

```powershell
python -m collector config     # zeigt, was geladen wurde, ohne Geheimnisse
python -m collector verify     # fragt die Forever-Endpunkte ab
python -m collector collect    # ein Durchlauf, wie ihn Actions ausfuehrt
python -m pytest               # kein Netz noetig
```

`verify` arbeitet sich vom Token ueber den Ruleset-Index bis zu einer Stichprobe aus drei
Auktionshaeusern vor und schreibt nebenbei einen Bericht nach `data/verify/`: Statuscodes,
Antwortgroessen, Felder einer Beispielauktion, `Last-Modified` je Haus. Der Bericht ist die
Grundlage fuer den eigentlichen Sammler - damit der auf gemessenen Zahlen aufsetzt und nicht
auf Forenposts.

```
collector/
  config.py     Einstellungen aus .env oder Umgebung, Namespaces, Pfade
  blizzard.py   OAuth-Token, Wiederholungen bei 429 und 5xx, Download in Dateien
  verify.py     prueft die Endpunkte und schreibt den Bericht
  collect.py    ein Durchlauf: holen, verdichten, Verkaeufe ableiten
  names.py      Stammdaten der Items: Namen, Haendlerpreise, volle Antwort
  foreverdb.py  Client fuer ForeverDB mit Tempolimit; foreverdb_dump.py zieht Listen lokal ab
  db.py         lokale DuckDB-Datei mit Sichten auf alle Daten; Kommandos db und sql
  publish.py    baut die Dateien fuer die Oberflaeche
  store.py      Pfade und Parquet-Dateien des Warehouse
  __main__.py   py -m collector <kommando>
tests/          gefaelschte Session und gefaelschter Client, echtes DuckDB, kein Netz
.github/workflows/
  tests.yml     pytest sowie Lint, Tests und Build der Oberflaeche bei jedem Push
  collect.yml   der Sammler, dreimal je Stunde
```

In GitHub kommen die Zugangsdaten aus *Settings -> Secrets and variables -> Actions*, als
`BLIZZARD_CLIENT_ID` und `BLIZZARD_CLIENT_SECRET`. Fehlen sie, schlaegt jeder Lauf mit einer
klaren Meldung fehl - still weiterlaufen und nichts sammeln waere schlimmer.

## Bekannte Einschraenkungen

- Items, die beim Scan noch nicht im Client-Cache waren, haben keinen Namen. Das Addon
  fordert sie nach und wiederholt bis zu drei Mal, der Rest landet trotzdem im Dump -
  die `itemID` ist immer gesetzt.
- Der Viewer zeigt maximal 800 Zeilen gleichzeitig; weiter eingrenzen oder anders sortieren.
- Ein voller Dump kann je nach Realm zweistellige MB erreichen. `data/` ist deshalb in
  `.gitignore`.
- Wer nur *im Spiel* Schnaeppchen sucht, ist mit TSM Sniper/Shopping besser bedient. Der Sinn
  hier ist die Auswertung ausserhalb des Spiels.
