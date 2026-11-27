# Forever AH Flip

Auktionshausdaten aus **World of Warcraft: Forever** sammeln und auswerten: stuendlich ueber
die Battle.net-API, ausgewertet lokal im Browser.

Zwei Datenquellen:

| Quelle | Was sie liefert |
|---|---|
| **Battle.net-API** | Jede einzelne Auktion eines Auktionshauses, stuendlich ueber GitHub Actions, ohne dass ein Rechner laufen muss. |
| **ForeverDB** (optional, nur lokal) | Rezepte, Haendler und Stammdaten der Items - daraus entstehen Crafting und Vendor flips. Braucht einen eigenen Schluessel; der Abzug verlaesst den Rechner nicht. |

| Teil | Was es macht |
|---|---|
| `collector/` | Python-Paket: sammelt ueber die Battle.net-API und baut die Dateien fuer die Anzeige. |
| `web/` | Die Oberflaeche: React, TypeScript, Vite, shadcn/ui. Gelegenheiten, Rezepte, Flips, Low Buy, Market Reset und eine Seite je Item. |

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
python -m collector foreverdb spells             # alle Zauber: daran haengen die Abklingzeiten der Rezepte
python -m collector foreverdb items --max-requests 50
python -m collector foreverdb-details            # Details der Items, die Blizzard nicht kennt
python -m collector foreverdb-details --scope market --max-requests 500
python -m collector foreverdb-vendors            # alle Haendler samt Sortiment und Preisen
python -m collector foreverdb-recipes            # alle Berufe mit Rezepten, Zutaten und Lernquellen
python -m collector foreverdb-refresh            # Items, Haendler, Sortimente, Zauber und Rezepte neu abziehen
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
- Rezepte gibt es je Beruf, 100 je Anfrage: was ein Rezept herstellt, die Zutaten mit Menge,
  die Skill-Stufen und wie man es lernt (Lehrer mit Preis, Rezept-Item, Haendler, Beute).
  `foreverdb-recipes` holt alle 2.493 Rezepte der 12 Berufe mit 33 Anfragen nach
  `recipes.jsonl` und schreibt erst, wenn alles da ist.
- Ein Rezept ist ein Zauber, und nur an dem steht, wie oft er sich wirken laesst und wie
  lange er dauert. Die Spell-Liste nennt beides schon in der Uebersicht (`cooldownMs`,
  `castTimeMs`): 32.131 Zauber, 322 Anfragen, eine Viertelstunde - und damit die
  Abklingzeit jedes Rezepts, ohne einen einzigen Zauber einzeln abzurufen.
- Erlaubt sind 30 Anfragen je Minute und 5.000 am Tag.

Nach einem neuen Spielstand aendern sich Items, Sortimente, Zauber und Rezepte.
`foreverdb-refresh` holt Item-Liste, Haendler, Spell-Liste und Sortimente neu - in einen
eigenen Ordner, und tauscht erst aus, wenn alles vollstaendig da ist. Bis dahin, auch nach
einem Abbruch, arbeiten Datenbank und Oberflaeche mit dem bisherigen Stand; ein erneuter
Aufruf setzt fort. Danach folgen die Rezepte. Rund 1.700 Anfragen, gut eine Stunde.

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
verschiedenen Orten. `db` baut daraus eine DuckDB-Datei, in der sich alles mit SQL
verknuepfen laesst:

```powershell
python -m collector db                                   # baut data/local/forever.duckdb
python -m collector sql "SELECT * FROM latest LIMIT 10"  # Abfrage ohne weiteres Werkzeug
python -m collector sql --file abfrage.sql --rows 200
```

Zwei Arten von Daten, zwei Arten, sie zu halten:

- **Stammdaten** aendern sich nur mit einem neuen Spielstand: Items, Haendler und ihr
  Sortiment, Rezepte und ihre Zutaten. Sie stehen als Tabellen mit Schluesseln in der Datei.
  Das Schema steht in `collector/schema.py`.
- **Staende, Verkaeufe und Preise** aendern sich stuendlich. Sie bleiben in den
  Parquet-Dateien des Warehouse, und die Datenbank schaut mit Sichten darauf. Nach einem
  `git -C data/warehouse pull` sind sie ohne Neubau aktuell.

```
items ─┬─< vendor_stock >── vendors
       ├─< recipe_reagents >─┐
       ├─< recipe_items >────┼── recipes
       └── recipes.item_id ──┘
```

| Tabelle | Schluessel | Inhalt |
|---|---|---|
| `items` | `item_id` | ein Item aus beiden Quellen: Blizzard gilt zuerst, ForeverDB fuellt auf - auch den Haendlerpreis |
| `vendors` | `vendor_id` | ein Haendler: Fraktion, Zone, Koordinaten |
| `vendor_stock` | `vendor_id`, `item_id` | was ein Haendler verkauft: Preis, Stapel, begrenzter Bestand |
| `vendor_prices` | `item_id` | je Item der guenstigste Haendler, den die Horde erreicht und der unbegrenzt liefert |
| `recipes` | `recipe_id` | ein Rezept: Beruf, Gruppe, Skill, hergestelltes Item und Menge, Lernquelle (`learned`: `trainer`, `recipe`, `automatic`), Preis beim Lehrer, Abklingzeit und Dauer eines Durchgangs |
| `recipe_reagents` | `recipe_id`, `item_id` | die Zutaten mit Menge |
| `recipe_items` | `recipe_id`, `item_id` | die Items, die ein Rezept lehren |

Die Zeilen eines Haendlers und eines Rezepts haengen ueber einen Fremdschluessel an ihrem
Kopf. Verweise auf Items sind bewusst keine Fremdschluessel: ForeverDB nennt Zutaten und
Ergebnisse, die in seiner eigenen Item-Liste fehlen - derzeit 256 hergestellte Items und 21
Zutaten. `db` zaehlt sie, statt daran zu scheitern.

| Sicht | Inhalt |
|---|---|
| `snapshots` | jeder Stand jedes Items: Angebote, Menge, Preise |
| `sales` | Verkaeufe, Ablaeufe und Neuzugaenge zwischen zwei Staenden |
| `runs` | Protokoll der Sammellaeufe |
| `latest` | der juengste Stand mit Namen und Haendlerpreisen |
| `history` | `snapshots` mit Namen und den Verkaeufen seit dem Stand davor |
| `sold_daily` | Verkaeufe je Item und Tag, mit `hours_covered` |
| `vendor_items` | `vendor_stock` mit dem Haendler in jeder Zeile - bequemer abzufragen |
| `vendor_flips` | beim Haendler kaufen, im Auktionshaus verkaufen: Gewinn nach 5 % Gebuehr |
| `ah_prices` | je Item das guenstigste Angebot im Auktionshaus und die Verkaeufe der letzten 24 Stunden |
| `item_prices` | was ein Item kostet, wenn man es kaufen muss: `buy_price` und `buy_source` (`ah` oder `vendor`) |
| `craft_reagents` | die Zutaten mit Preis je Stueck, Bezugsquelle und Summe |
| `crafts` | je Rezept: Kosten der Zutaten, guenstigstes Angebot des Ergebnisses, Gewinn nach 5 % Gebuehr |
| `blizzard_items` | die Stammdaten aus Blizzards API im Original, `raw` als JSON |
| `foreverdb_items`, `foreverdb_item_details`, `foreverdb_vendor_details`, `foreverdb_recipes` | der Abzug von ForeverDB im Original, mit allen Feldern |

Die Tabellen sind eine Kopie und koennten veralten. Die Datei merkt sich deshalb, woraus sie
gebaut wurde. `sql` baut sie neu, sobald sich Stammdaten geaendert haben, und die
Abzugskommandos (`foreverdb-...`) tun es am Ende von selbst. Nur wer die Datei mit einem
anderen Werkzeug oeffnet, ruft nach einem Abzug oder einem `git pull` einmal `db` auf.

Die Rechnung fuers Herstellen (`item_prices`, `craft_reagents`, `crafts`) steht in
`collector/crafting.py` und gilt genauso beim Bauen der Anzeige-Dateien - die Oberflaeche und
eine Abfrage rechnen also gleich.

Dazu zwei Helfer: `money(123456)` ergibt `12g 34s 56c`, `gold(123456)` ergibt `12.35`.

```sql
-- Was hat sich heute am meisten verkauft?
SELECT name, qty_sold, money(value_sold) AS umsatz, hours_covered
FROM sold_daily WHERE day = current_date ORDER BY value_sold DESC LIMIT 20;

-- Angebote unter dem, was ein Haendler zahlt
SELECT name, n_listings, money(min_price) AS angebot, money(vendor_sell) AS haendler
FROM latest WHERE vendor_sell > min_price ORDER BY vendor_sell - min_price DESC;

-- Rezepte, die im Auktionshaus mehr bringen, als sie beim Haendler kosten
SELECT name, item_subclass AS beruf, money(vendor_price) AS haendler, money(ah_price) AS ah,
       money(profit) AS gewinn, n_listings, limited, vendor, zone
FROM vendor_flips WHERE item_class = 'Recipe' ORDER BY profit DESC;

-- Was lohnt sich herzustellen? Nur Rezepte, deren Zutaten alle einen Preis haben.
SELECT name, profession, skill, money(cost) AS zutaten, money(ah_price) AS ah,
       money(profit) AS gewinn, profit_pct, qty_sold_24h
FROM crafts WHERE profit > 0 ORDER BY profit DESC LIMIT 30;

-- Die Rechnung eines Rezepts im Einzelnen
SELECT name, count, money(unit_price) AS je_stueck, source, vendor, money(total) AS summe
FROM craft_reagents WHERE recipe_id = 3451;

-- In die vollstaendige Antwort greifen
SELECT name, raw->>'$.preview_item.armor.value' AS armor
FROM blizzard_items WHERE inventory_type = 'CHEST' AND quality = 'RARE';
```

`vendor_flips` nimmt je Item den guenstigsten Haendler, den die Horde erreicht (Haendler der
Allianz bleiben aussen vor), und vergleicht mit dem guenstigsten Angebot im Auktionshaus.
Drei Dinge sagt die Sicht nicht: ob der Haendler einen Ruf verlangt (`reputation` nennt nur
die Fraktion), wie schnell ein begrenzter Bestand nachkommt, und ob sich das Item zu dem
Preis auch verkauft - dafuer steht `sold_recently` daneben.

`crafts` bewertet jede Zutat mit ihrem guenstigsten Preis: dem guenstigsten Angebot im
Auktionshaus oder einem Haendler mit unbegrenztem Bestand, je nachdem, was weniger kostet.
Hat eine Zutat gerade keinen Preis, bleiben `cost` und `profit` leer; `cost_known` nennt
die Summe der uebrigen und `unpriced` ihre Zahl. `profit` gilt fuer einen Durchgang, also
fuer `item_count` Stueck. Nicht eingerechnet sind das einmalige Lernen des Rezepts, die
Einstellgebuehr und die Frage, ob eine Zutat sich guenstiger selbst herstellen liesse. Und
wie bei den Haendler-Flips: gerechnet wird gegen das guenstigste Angebot, nicht gegen einen
Preis, zu dem sicher verkauft wird.

`cooldown_seconds` nennt die Abklingzeit eines Rezepts. Eine Transmutation etwa bringt
ihren Gewinn einmal in 47 Stunden, waehrend sich ein Trank beliebig oft brauen laesst - der
Gewinn je Durchgang ist bei beiden derselbe Wert, vergleichbar ist er nicht. Wer nur
Wiederholbares sehen will, filtert mit `WHERE cooldown_seconds IS NULL`.

Die Datei laesst sich auch mit DBeaver, der DuckDB-Kommandozeile oder einer
DuckDB-Erweiterung fuer VS Code oeffnen. DuckDB erlaubt dabei nur ein Programm, das schreibt:
solange ein anderes die Datei offen hat, schlaegt `db` fehl und sagt das.

### Dateien fuer die Anzeige

Eine Datei je Stand ist gut zum Sammeln und schlecht zum Anzeigen: der Verlauf eines Items
ueber 14 Tage laege in 336 Dateien. `publish` baut daraus eine Form, die ein Browser mit
wenigen Teilabrufen lesen kann:

```powershell
python -m collector publish            # 14 Tage nach web/public/data, dazu der aktuelle Stand
python -m collector publish --days 30
python -m collector publish --no-live  # ohne den aktuellen Stand von Blizzard
```

Stehen Zugangsdaten in der `.env`, holt `publish` ausserdem den aktuellen Stand direkt von
Blizzard - zwei Anfragen, etwa zehn Sekunden - mit jedem einzelnen Angebot. Er wird zum
juengsten Stand des Markts, und aus ihm entsteht die **Preisleiter**: je Item und Preis die
angebotene Menge. Ohne sie laesst sich nicht rechnen, was ein Aufkauf kostet. Die
gespeicherten Kennzahlen (guenstigstes Angebot, unteres Viertel, Median) taugen dafuer
nicht: an einem echten Stand gemessen lagen die daraus geschaetzten Kosten im Median um
56 % daneben. Im Warehouse wird die Leiter bewusst nicht gespeichert - sie ist so gross wie
der Stand selbst und wuerde den Branch `data` verdreifachen. Gebraucht wird immer nur die
aktuelle.

| Datei | Inhalt |
|---|---|
| `hourly.parquet` | alle Staende des Zeitfensters mit Preisen, Mengen und Verkaeufen, nach Item sortiert und in Zeilengruppen von 8192 geschnitten |
| `market.parquet` | der juengste Stand, eine Zeile je Item, dazu Tief, Hoch, Veraenderung, Verkaeufe und Neueinstellungen der letzten 24 Stunden, der uebliche Preis, der Trend und - mit Preisleiter - der Marktwert |
| `ladder.parquet` | nur mit aktuellem Stand: die Preisleiter, je Item und Preis die Menge, von unten nach oben |
| `meta.json` | Zeitraum, Anzahl Staende, Dateigroessen, von wann der aktuelle Stand ist |
| `names.json` | Item-ID zu Name, fuer Items im Zeitfenster und im Markt |
| `vendor_flips.parquet` | nur mit lokalem Abzug der Haendler: Items, die im Auktionshaus mehr bringen, als sie beim Haendler kosten |
| `item_vendors.parquet` | ebenso: je Item die drei guenstigsten erreichbaren Haendler und wie viele es insgesamt fuehren |
| `crafts.parquet` | nur mit lokalem Abzug der Rezepte: je Rezept, dessen Ergebnis im Auktionshaus steht, Kosten, Erloes und Gewinn |
| `craft_reagents.parquet` | die Zutaten dieser Rezepte mit Preis und Bezugsquelle |

Wer ein Item will, liest am Ende von `hourly.parquet` nach, in welcher Zeilengruppe es
liegt, und holt nur die. Zeit steht als Unix-Sekunden drin, Preise als `DOUBLE` - beides
kommt im Browser als gewoehnliche Zahl an. Komprimiert wird mit Snappy, weil schlanke
Parquet-Leser das ohne Zusatzpaket verstehen.

Zwei Preise und ein Trend neben dem guenstigsten Angebot:

- Der **uebliche Preis** (`usual_price`) ist der Median des guenstigsten Angebots ueber die
  Staende der letzten sieben Tage. Aelteres zaehlt nicht: der Preissturz nach dem Erscheinen
  eines Items oder eine alte Preislage sagt nichts darueber, wo der Preis heute steht. Er
  steht erst da, wenn ein Item in diesen Tagen in mindestens 24 Staenden vorkam. An ihm misst
  sich, ob ein Angebot guenstig ist und wohin ein Reset zielen darf.
- Der **Marktwert** (`market_value`) wird aus der Preisleiter nach dem Verfahren von TSMs
  AuctionDB gerechnet: die guenstigsten 30 % der Stuecke, nach den ersten 15 % Schluss bei
  einem Preissprung von 20 %, Ausreisser jenseits von 1,5 Standardabweichungen weg, der Rest
  gemittelt. So zaehlt weder ein einzelnes Schnaeppchen noch eine Wand ueberteuerter Angebote.
- Der **Trend** ist eine Gerade durch den Logarithmus des guenstigsten Angebots ueber das
  ganze Zeitfenster. `trend_pct_day` ist ihre Steigung als Aenderung in Prozent je Tag,
  `trend_fit` (r2, 0 bis 1) sagt, wie genau der Verlauf ihr folgt. Beides steht erst ab 48
  Staenden ueber drei Tage da. Ein Preis, der seit Tagen gleichmaessig faellt, hat eine
  steile Gerade, die gut passt; ein ploetzlicher Einbruch hat eine, die schlecht passt.

`sales_hours_24h` in `market.parquet` sagt, wie viele der letzten 24 Stunden durch
Vergleiche gedeckt sind. Steht dort 6, sind die Verkaufszahlen ein Viertel der Wahrheit.

Die Dateien sind abgeleitet und jederzeit neu baubar, `web/public/data/` steht deshalb in
`.gitignore`.

### Die Oberflaeche

`web/` ist eine React-App: TypeScript, Vite, Tailwind und shadcn/ui. Gebraucht wird Node.js.

```powershell
git -C data/warehouse pull          # frische Daten holen
python -m collector publish         # Dateien fuer die Anzeige bauen
cd web
npm install                         # einmalig
npm run dev                         # http://localhost:5173
```

Links die Navigation, oben die Annahmen, in der Mitte die Seite, rechts das gewaehlte Item.

| Seite | Zeigt |
|---|---|
| **Opportunities** | die besten Treffer jeder Art nebeneinander, sortiert nach dem, was am Tag realistisch drin ist |
| **Crafting** | jedes Rezept, dessen Ergebnis im Auktionshaus steht: Zutaten, Erloes, Gewinn, Verkaeufe |
| **Vendor flips** | was ein Haendler guenstiger verkauft als das Auktionshaus |
| **Buy low** | Angebote deutlich unter dem ueblichen Preis: kaufen, zum ueblichen Preis wieder einstellen |
| **Market reset** | alles bis zu einer Luecke aufkaufen und knapp unter dem naechsten Angebot wieder einstellen |
| **Market** | der juengste Stand, eine Zeile je Item |
| **Watchlist**, **Shopping list** | gemerkte Items; geplante Rezepte mit einer Liste, was wo zu kaufen ist |

Crafting, Vendor flips und die Haendler gibt es nur mit lokalem Abzug von ForeverDB, Buy low
und Market reset nur mit der Preisleiter. Fehlt etwas, fehlt der Eintrag in der Navigation.

**Die Annahmen** stehen in der Leiste oben und gelten ueberall:

- *Sell at*: zu welchem Preis verkauft wird - zum guenstigsten Angebot von jetzt oder,
  vorsichtiger, zum Tief der letzten 24 Stunden. Ein frischer Preissprung taeuscht dann nicht.
- *My share of sales*: welchen Anteil der Tagesverkaeufe man sich zutraut. Daraus wird
  `Est./day`: Gewinn je Stueck mal diesem Anteil, bei Rezepten gedeckelt durch die Abklingzeit.

**Buy low und Market reset** rechnen auf der Preisleiter. Fuer den Reset traegt man ein, wie
viel Gold man hat und wie viel davon hoechstens in einen einzelnen Reset fliessen darf. Je
Item steht der lohnendste Reset, der bezahlbar ist, sich im gewaehlten Zeitraum absetzen
laesst und mindestens 20 % Rendite bringt; das Ziel liegt knapp unter dem naechsten Angebot,
nie mehr als 10 % ueber dem ueblichen Preis. Drei Kacheln sagen, wie viele Resets zusammen
ins Gold passen. Drei Marken warnen:

- **Refills fast**: das Item gehoert zum Viertel des Markts, in dem je verkauftem Stueck am
  meisten neu eingestellt wird. Gemessen wird am Markt selbst, weil ueberall mehr eingestellt
  als verkauft wird - jedes erneute Einstellen zaehlt mit.
- **Fallender Pfeil**: der Preis ist in 24 Stunden um 30 % oder mehr gefallen. Der uebliche
  Preis gilt dann vielleicht nicht mehr, und ein Reset waere eine Wette auf seine Rueckkehr.
- **Downtrend**: der Preis faellt ueber das ganze Zeitfenster um 3 % am Tag oder mehr, und
  zwar stetig (`trend_fit` ab 0,5). Dann ist ein Angebot weit unter dem ueblichen Preis kein
  Ausreisser nach unten, sondern der naechste Schritt abwaerts - der uebliche Preis ist nur
  die Mitte einer fallenden Linie. Buy low laesst solche Items weg, solange *Hide downtrends*
  an ist; die Startseite und die Zahl in der Navigation zaehlen sie nie mit.

**Der Kauf-Score** sagt in einer Zahl von 0 bis 100, wie sehr es sich lohnt, ein Item jetzt zu
kaufen und zum ueblichen Preis wieder einzustellen. Er steht in Buy low (dort wird nach ihm
sortiert), im Markt, in der Seitenleiste und aufgeschluesselt auf der Seite des Items:

```
Score = Wurzel(Marge x Gewinn) x Absatz x Frische x Abzuege
```

Bewertet wird der Kauf, der am besten abschneidet: die guenstigsten Angebote bis zu der Stufe,
ab der mehr zu kaufen die Marge staerker duennt, als es Gewinn bringt. Nie mehr, als der eigene
Anteil an den Verkaeufen im Zeitraum absetzt, und nie mehr, als das Gold hergibt.

| Teil | Volle Punktzahl | Null |
|---|---|---|
| **Marge** | 100 % Rendite, also gekauft fuer weniger als die Haelfte des ueblichen Preises | kein Gewinn |
| **Gewinn** | 20 % des eigenen Golds, mindestens 10 Gold; dazwischen logarithmisch | 50 Silber |
| **Absatz** | der eigene Anteil setzt die Stueckzahl im Zeitraum ab | keine Verkaeufe |
| **Frische** | das guenstigste Angebot stand in 24 Stunden noch bei 90 % des ueblichen Preises | es kam nicht ueber 60 % |

Marge und Gewinn zaehlen gemeinsam: viel Rendite auf ein paar Kupfer ist so wenig wert wie ein
grosser Betrag mit hauchduenner Marge. Absatz und Frische sind Bedingungen - fehlt eine, hilft
der Rest nicht. Die Frische trennt den frischen Ausreisser vom Markt, der schon laenger tief
steht: ein Schnaeppchen, das seit einem Tag niemand will, ist keines. Abzuege gibt es fuer
einen Abwaertstrend (mal 0,25) und fuer schnellen Nachschub (mal 0,8). Ab 70 heisst der Score
*Strong*, ab 40 *Decent*, ab 15 *Thin*, darunter *Skip*. Er haengt an den Annahmen und am
eingetragenen Gold und aendert sich mit ihnen.

**Das Item.** Ein Klick auf eine Zeile oeffnet es in der Seitenleiste, die Pfeiltasten
blaettern, Doppelklick oder Enter oeffnet die Vollseite. Dort steht alles:

- Kennzahlen: Kauf-Score, guenstigstes Angebot, ueblicher Preis, Marktwert, Median, Veraenderung,
  Trend, Verkaeufe und Neueinstellungen am Tag, Angebote, Haendlerpreis.
- Der Verlauf: guenstigster Preis, Median und darunter die verkaufte Menge je Stand. Liegt
  zwischen tiefstem und hoechstem Preis mehr als das Achtfache, wird die Achse logarithmisch -
  sonst drueckt ein einzelner Ausschlag alles andere an den unteren Rand.
- Die Heatmap: Wochentag mal Stunde in Ortszeit, umschaltbar zwischen Preis gegenueber dem
  ueblichen Preis und verkaufter Menge. Sie rechnet aus dem Verlauf des Zeitfensters; mit 14
  Tagen hat jede Stunde zwei Stichproben, mit `publish --days 28` vier.
- *Is it worth buying?*: der Kauf-Score mit seinen vier Teilen, den Abzuegen und dem Kauf,
  auf dem er beruht.
- Die Preisleiter mit Rechner: ein Schieber waehlt, bis zu welcher Stufe gekauft wird.
  Darunter die ganze Rechnung - Stueckzahl, Kosten, Zielpreis mit Begruendung, Erloes,
  Gebuehr, Gewinn, Rendite, ab wann das Gold zurueck ist, Dauer des Abverkaufs, Nachschub,
  der Verlust beim Rueckfall auf das alte Tief, die geschaetzte Einstellgebuehr - und ein
  Urteil in einem Satz.
- *Where to relist*: zu welchem Preis das Item am besten wieder eingestellt wird. Zur Wahl
  stehen 1c unter dem guenstigsten Angebot (verkauft sich zuerst), 1c unter jeder hoeheren
  Stufe der Preisleiter und der uebliche Preis. Entschieden wird im Rueckblick: jede Stunde
  des Verlaufs, in der das guenstigste Angebot hoechstens 10 % vom heutigen entfernt lag,
  ist ein Startpunkt. Ein Preis gilt als erreicht, wenn das guenstigste Angebot in der
  Frist (*Sell within*) bis dorthin stieg und dabei verkauft wurde - alles Guenstigere war
  dann weg. Wurde er nicht erreicht, zaehlt der Preis am Ende der Frist. Empfohlen wird,
  was so im Schnitt am meisten brachte, wenn es mindestens jedes zweite Mal erreicht wurde,
  3 % mehr brachte als sofort zu verkaufen und nicht mehr als 10 % ueber dem ueblichen Preis
  liegt. Stand der Preis im Zeitfenster noch nie da, wo er heute steht, sagt der Abschnitt
  das und nennt nur, was sicher ist. Die Stunden ueberlappen sich: die Prozentzahlen sind
  ein Anhalt, keine Vorhersage.
- Herstellung (jede Zutat mit Preis und Bezugsquelle), Verwendung (welche Rezepte das Item
  verbrauchen) und Haendler.

Dazu: `Strg+K` sucht ueber alle Items, `/` springt ins Filterfeld, `Esc` schliesst. Unter
*My professions* traegt man Berufe und Skill ein; Rezepte darueber erscheinen blass, und die
Startseite laesst sich darauf beschraenken. Annahmen, Berufe, Merkliste und Einkaufsliste
bleiben im Browser gespeichert. Seite und Item stehen in der Adresse (`#reset/3826`,
`#item/3826`) - jede Ansicht laesst sich verlinken, und Zurueck fuehrt zurueck. Zeiten stehen
in Ortszeit, hell und dunkel folgen dem System oder dem Knopf oben rechts.

```
web/src/
  lib/trade.ts       die Rechnung: Rezepte, Flips, Low Buy, Reset, Nachschub, Trend, Urteil
  lib/score.ts       der Kauf-Score und seine Teile
  lib/relist.ts      der Preis zum Wiedereinstellen: Rueckblick ueber den Verlauf
  lib/app.tsx        geladene Daten, Annahmen, Berufe, Merk- und Einkaufsliste als ein Kontext
  lib/route.ts       Seite und Item in der Adresse
  lib/data.ts        liest die Parquet-Dateien, hourly.parquet gezielt je Item
  lib/heat.ts        der Verlauf als Wochentag mal Stunde
  lib/rows.ts        Suchen, Sortieren, Buendeln als reine Funktionen
  lib/format.ts      Gold/Silber/Kupfer, Prozente, Dauer, Ortszeit fuer das Diagramm
  pages/             eine Datei je Seite oder Gruppe von Seiten
  components/        Tabelle, Seitenleiste, Heatmap, Preisleiter, Einstellpreis, Diagramm; ui/ kommt von shadcn
```

Die Rechnung steht in `lib/trade.ts`, `lib/score.ts` und `lib/relist.ts` als reine Funktionen
und ist getestet; die Oberflaeche zeigt nur an, was dort herauskommt. Das Diagramm zeichnet
TradingViews `lightweight-charts`,
die Parquet-Dateien liest `hyparquet`. Die Diagramm-Bibliothek wird erst geladen, wenn
jemand ein Item oeffnet. Sie steht unter Apache-2.0 und verlangt die Namensnennung samt Link,
die im Diagramm und in der Fusszeile steht.

Der Entwicklungsserver von Vite beantwortet Teilabrufe - ohne die muesste die Seite fuer
jedes Diagramm die ganze `hourly.parquet` laden. `python -m http.server` kann das nicht.

Die Oberflaeche ist englisch beschriftet. Namen kommen aus `names.json`; wo weder Blizzard
noch ein lokaler Abzug von ForeverDB einen kennt, steht `Item 2589` da.

Was die Zahlen nicht wissen: Verkaeufe sind eine Obergrenze, weil auch zurueckgezogene
Angebote als verkauft zaehlen. Gerechnet wird gegen Angebote, nicht gegen Preise, zu denen
sicher verkauft wird. Die Einstellgebuehr folgt der Formel aus Classic und ist fuer Forever
nicht bestaetigt. Und die Preisleiter ist so alt wie der letzte Lauf von `publish` - vor
einem Kauf im Spiel nachsehen, ob die guenstigen Angebote noch da sind.

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

Warum nicht die Daten von TSM: sie sind Aggregate je Item, nur fuer die eigenen
Realm-Fraktionen und bis zu eine Stunde alt. Die API liefert jede Auktion mit ihrer ID - und
weil Auktions-IDs ueber zwei Abrufe hinweg vergleichbar sind, laesst sich daraus selbst
ausrechnen, was verkauft wurde statt nur abgelaufen ist.

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
  schema.py     das Schema der Stammdaten: die festen Tabellen der lokalen Datenbank
  crafting.py   Rezepte, Zutaten und die Rechnung, was sich herzustellen lohnt
  db.py         lokale DuckDB-Datei: Stammdaten als Tabellen, Staende als Sichten; Kommandos db und sql
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

- Gesammelt wird ein Auktionshaus. Was die Zahlen der Oberflaeche nicht wissen, steht am Ende
  des Abschnitts *Die Oberflaeche*.
- `data/` steht in `.gitignore`: die Staende liegen im Branch `data`, alles andere dort ist
  abgeleitet oder darf den Rechner nicht verlassen.
- Wer nur *im Spiel* Schnaeppchen sucht, ist mit TSM Sniper/Shopping besser bedient. Der Sinn
  hier ist die Auswertung ausserhalb des Spiels.
