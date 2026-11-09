# Forever AH Flip

Auktionshaus-Daten aus **World of Warcraft: Forever** in eine Datei schreiben, ansehen und
nach Flip-Gelegenheiten durchsuchen.

Drei Teile, die unabhaengig voneinander funktionieren:

| Teil | Was es macht |
|---|---|
| `addon/AHDump` | In-Game-Addon. `/ahdump` macht einen Full-Scan des Auktionshauses und legt ihn in den SavedVariables ab. |
| `viewer/index.html` | Einzelne HTML-Datei. Zeigt den Dump als sortierbare Tabelle und rechnet Flip-Kandidaten aus. Laeuft offline im Browser. |
| `tools/Convert-AHDump.ps1` | Optional: macht aus `AHDump.lua` eine CSV fuer Excel, Pandas & Co. |

## Technischer Hintergrund

Forever (`WOW_PROJECT_CAMELOT`, Interface **16001**) nutzt die **moderne** UI-Architektur von
Mainline, nicht die von Classic Era. Das Auktionshaus laeuft also ueber `C_AuctionHouse` inklusive
Commodities - und damit ueber `C_AuctionHouse.ReplicateItems()`, den vollstaendigen AH-Abzug in
einem Rutsch. Addons fuer Classic Era (Interface 11500er) funktionieren hier nicht.

## Addon installieren

1. Ordner `addon/AHDump` nach `<WoW>\_forever_\Interface\AddOns\AHDump` kopieren
2. WoW **neu starten** - ein neu angelegtes Addon wird von `/reload` nicht erkannt
3. In der Addon-Liste aktivieren

## Dump erstellen

```
1. Zum Auktionator gehen, Auktionshaus oeffnen
2. /ahdump          -> Full-Scan, dauert 10-60 Sekunden
3. /reload          -> erst jetzt schreibt WoW die Datei
```

Ergebnis: `<WoW>\_forever_\WTF\Account\<ACCOUNT>\SavedVariables\AHDump.lua`

Weitere Befehle:

- `/ahdump info` - zeigt Zeitpunkt und Umfang des letzten Dumps
- `/ahdump clear` - leert die Daten, damit die Datei nicht unnoetig waechst

**Rate-Limit:** `ReplicateItems()` ist serverseitig stark gedrosselt, realistisch einmal
alle ca. 15 Minuten. Kommt nach zwei Minuten keine Antwort, meldet das Addon das und man
versucht es spaeter erneut.

## Daten ansehen

`viewer/index.html` im Browser oeffnen und die `AHDump.lua` hineinziehen - die CSV geht
genauso. Es wird nichts hochgeladen, die Datei wird lokal im Browser gelesen.

Drei Ansichten:

- **Pro Item** - ein Eintrag je Item: Anzahl Auktionen, Gesamtmenge, guenstigster Stueckpreis, Median
- **Flip-Kandidaten** - Items, bei denen das guenstigste Angebot deutlich unter dem Marktpreis liegt
- **Alle Auktionen** - der rohe Dump, sortier- und durchsuchbar

### Wie die Flip-Marge gerechnet wird

Pro Item werden alle Stueckpreise sortiert. Der **Marktpreis** ist der Median *ohne* das
guenstigste Angebot - das ist ja genau das, was man selbst kaufen will. Davon gehen 5 %
Auktionshaus-Gebuehr ab:

```
Marge pro Stueck = Marktpreis * 0,95 - guenstigster Stueckpreis
Gewinn           = Marge pro Stueck * Menge im guenstigsten Angebot
```

Ueber `min. Auktionen` und `min. Marge %` laesst sich filtern. Sinnvoll sind mindestens
3-5 Auktionen pro Item, sonst ist der "Markt" nur ein einzelner Mitspieler.

Das ist bewusst eine einfache Heuristik. Sie sagt nichts darueber, ob sich ein Item auch
tatsaechlich verkauft, und ein Dump ist immer nur eine Momentaufnahme.

## Datenformat

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

`isCommodity` ist wichtig: ohne diese Unterscheidung ist jeder Preisvergleich bei
Stapelware falsch. Der Viewer rechnet entsprechend `buyout` bzw. `buyout / count`.

## CSV erzeugen (optional)

```powershell
.\tools\Convert-AHDump.ps1
```

Sucht die zuletzt geschriebene `AHDump.lua` selbst und legt die CSV daneben.
Mit `-Path` / `-WowPath` / `-Out` laesst sich alles explizit angeben.

## Bekannte Einschraenkungen

- Items, die beim Scan noch nicht im Client-Cache waren, haben keinen Namen. Das Addon
  fordert sie nach und wiederholt bis zu drei Mal, der Rest landet trotzdem im Dump -
  die `itemID` ist immer gesetzt.
- Der Viewer zeigt maximal 800 Zeilen gleichzeitig; weiter eingrenzen oder anders sortieren.
- Ein voller Dump kann je nach Realm zweistellige MB erreichen. `data/` ist deshalb in
  `.gitignore`.
