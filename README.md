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
| `collector/` | Python-Paket, das die Battle.net-API abfragt. Bisher nur `verify`. |
| `viewer/index.html` | Einzelne HTML-Datei. Liest TSM-Daten und eigene Dumps, zeigt Tabellen und Deal-Listen. |
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
sagt also nur mit Token etwas aus. Genau dafuer gibt es `verify`, siehe unten.

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

In Forever scheint es praktisch keine Commodities zu geben: Leinenstoff, Kupfererz, Heiltraenke
und der ganze Rest liegen bei TSM unter `NON_COMMODITY`, der Commodity-Datensatz ist leer.
`isCommodity` duerfte also durchgehend 0 sein - die Spalte bleibt trotzdem drin, falls sich das
noch aendert.

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
python -m pytest               # 17 Tests, kein Netz noetig
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
  __main__.py   py -m collector <kommando>
tests/          Tests gegen eine gefaelschte Session, ohne Netz
.github/workflows/
  tests.yml     pytest bei jedem Push
  collect.yml   verify von Hand; der stuendliche Cron ist auskommentiert,
                bis die Secrets gesetzt sind
```

In GitHub kommen die Zugangsdaten aus *Settings -> Secrets and variables -> Actions*, als
`BLIZZARD_CLIENT_ID` und `BLIZZARD_CLIENT_SECRET`. Danach laesst sich `collect` unter *Actions*
von Hand starten; erst wenn das durchlaeuft, wird der `schedule`-Block aktiviert.

## Bekannte Einschraenkungen

- Items, die beim Scan noch nicht im Client-Cache waren, haben keinen Namen. Das Addon
  fordert sie nach und wiederholt bis zu drei Mal, der Rest landet trotzdem im Dump -
  die `itemID` ist immer gesetzt.
- Der Viewer zeigt maximal 800 Zeilen gleichzeitig; weiter eingrenzen oder anders sortieren.
- Ein voller Dump kann je nach Realm zweistellige MB erreichen. `data/` ist deshalb in
  `.gitignore`.
- Wer nur *im Spiel* Schnaeppchen sucht, ist mit TSM Sniper/Shopping besser bedient. Der Sinn
  hier ist die Auswertung ausserhalb des Spiels.
