# Die Forever-Auktionshaus-API, gemessen

Blizzard dokumentiert diese Endpunkte nicht. Was hier steht, ist am **14.11.2026** gegen
`dynamic-forever-eu` gemessen worden, nicht aus Forenposts uebernommen. Nachmessen mit
`python -m collector verify`, der Bericht landet in `data/verify/`.

## Zugang

OAuth client_credentials gegen `https://oauth.battle.net/token`, Client von
<https://develop.battle.net/access/clients>. Der Token gilt 24 Stunden
(`blizzard-token-expires`).

**Ohne gueltigen Token antwortet die API auf jeden Pfad mit 404**, auch auf
`/data/wow/realm/index`, das es sicher gibt. Mit kaputtem Token kommt 401. Ein 404 sagt
also nur dann etwas ueber einen Endpunkt aus, wenn der Token steht.

## Rulesets statt Realms

`/data/wow/ruleset/index` liefert in der EU vier Rulesets:

| ID | Name |
|---|---|
| 1 | PvP |
| 2 | Normal |
| 3 | Rollenspiel |
| 15 | Rollenspiel (PvP) |

## Auktionshaeuser

`/data/wow/ruleset/{id}/auctions/` - **der Schraegstrich am Ende ist noetig**. Jedes Ruleset
meldet dieselben 15 Haeuser; die ID 122 fehlt. Die Haeuser sind nach Fraktion benannt, nicht
nach Ruleset:

| Haus | Name | Auktionen | Commodities | Ruleset |
|---|---|---|---|---|
| 110 | Auktionshaus der Allianz | 140.329 | 129.321 | PvP (aus der Position) |
| 111 | Auktionshaus der Allianz | 150.618 | 130.989 | Normal (aus der Position) |
| 112 | Auktionshaus der Allianz | 0 | 0 | ungenutzt |
| 113 | Auktionshaus der Horde | 158.450 | 146.501 | **PvP (gemessen)** |
| 114 | Auktionshaus der Horde | 140.780 | 123.430 | **Normal (gemessen)** |
| 115 | Auktionshaus der Horde | 0 | 0 | ungenutzt |
| 116 | Auktionshaus der Schwarzmeerraeuber | 12.074 | 28.990 | PvP (aus der Position) |
| 117 | Auktionshaus der Schwarzmeerraeuber | 12.162 | 26.690 | Normal (aus der Position) |
| 118 | Auktionshaus der Schwarzmeerraeuber | 0 | 0 | ungenutzt |
| 119 | Auktionshaus der Allianz | 21.526 | 24.279 | eines der Rollenspiel-Rulesets |
| 120 | Auktionshaus der Horde | 12.694 | 12.826 | eines der Rollenspiel-Rulesets |
| 121 | Auktionshaus der Schwarzmeerraeuber | 302 | 1.139 | eines der Rollenspiel-Rulesets |
| 123 | Auktionshaus der Allianz | 15.954 | 17.983 | das andere Rollenspiel-Ruleset |
| 124 | Auktionshaus der Horde | 15.603 | 17.363 | das andere Rollenspiel-Ruleset |
| 125 | Auktionshaus der Schwarzmeerraeuber | 308 | 904 | das andere Rollenspiel-Ruleset |

### Wie 113 und 114 bestimmt wurden

Nicht geraten, sondern gegen die TSM-Daten gerechnet: fuer jedes Horde-Haus der guenstigste
Sofortkauf je Item, verglichen mit `minBuyout` aus `AUCTIONDB_NON_COMMODITY_DATA` je Scope.

```
Haus Scope          gemeinsam  Jaccard   Median   +-25%   exakt
 113 PvP-Horde           5118     0.80     1.00    100%    100%
 113 Normal-Horde        4690     0.71     0.99     54%      6%
 114 Normal-Horde        4941     0.80     1.00    100%    100%
 114 PvP-Horde           4690     0.70     1.01     54%      6%
```

100 % exakt gleiche Preise sind kein Zufall und auch kein blosser Treffer: TSM bezieht seine
Forever-Daten offensichtlich aus genau dieser API. Was wir selbst sammeln, ist also
mindestens das, was TSM hat - plus Stapelware, plus jede einzelne Auktion, plus die
Fraktionen und Rulesets, auf denen man keinen Charakter hat.

Die Zuordnung der uebrigen Haeuser folgt der Position im Dreierblock je Fraktion
(PvP, Normal, ungenutzt) und ist **nicht** gemessen. Die beiden Rollenspiel-Rulesets lassen
sich ohne Charakter dort nicht auseinanderhalten.

## Felder

Normale Auktionen, `/data/wow/ruleset/{id}/auctions/{haus}`:

```json
{"id": 81175958, "item": {"id": 4409}, "buyout": 200, "quantity": 1, "time_left": "SHORT"}
```

- `quantity` ist bei **allen** 140.329 Auktionen in Haus 110 gleich 1. Stapelware laeuft
  ueber den Commodity-Endpunkt. Damit ist `buyout` immer ein Stueckpreis - die Frage, ob
  der Preis fuer den ganzen Stack gilt, stellt sich hier nicht.
- `bid` steht nur bei 262 von 140.329 Auktionen, also nur dort, wo wirklich geboten wurde.
- `item` traegt neben `id` manchmal `context`, `modifiers` und `bonus_lists`.
- `time_left`: SHORT 5 %, MEDIUM 16 %, LONG 63 %, VERY_LONG 16 %.
- Einen Verkaeufernamen gibt es nicht. Wer den braucht, kommt um den eigenen Scan nicht herum.

Stapelware, `/data/wow/ruleset/{id}/auctions/{haus}/commodities`:

```json
{"id": 81421197, "item": {"id": 765}, "quantity": 20, "unit_price": 95, "time_left": "MEDIUM"}
```

Im Hausdokument steht unter `commodities` nur ein Link, keine Daten.

**Korrektur zu einer frueheren Annahme:** Dass Forever praktisch keine Stapelware habe,
stimmt nicht. Allein Haus 110 hat 129.321 Commodity-Auktionen. Der leere Commodity-Datensatz
in TSMs `AppData.lua` ist eine Eigenart von TSM, keine Eigenschaft des Spiels.

## Rulesets liefern dieselben Daten

Haus 110 ueber alle vier Rulesets abgefragt:

```
Ruleset  1:  140329 Auktionen, Summe buyout 2474734443
Ruleset  2:  140329 Auktionen, Summe buyout 2474734443
Ruleset  3:  140330 Auktionen, Summe buyout 2474738250
Ruleset 15:  140330 Auktionen, Summe buyout 2474738250
```

Der Unterschied ist genau **eine** Auktion, die zwischen den Abrufen dazukam. Die Ruleset-ID
im Pfad filtert nichts. Fuer den Sammler heisst das: **15 Haeuser einmal abrufen, nicht
60 mal.**

## Groesse und Takt

- Ein grosses Haus: rund 13 MB gzip, in 0,4 s geladen.
- Alle 15 Haeuser, nur Auktionen: rund 62 MB. Mit Stapelware etwa das Doppelte.
- `last-modified` ist der Stand, den Blizzard gebaut hat - bei der Messung
  `Sat, 14 Nov 2026 18:19:11 GMT`, rund 50 Minuten alt. Die grossen Haeuser tragen jeweils
  eigene Sekunden, die leeren einen aelteren Stand.
- `cache-control: public, max-age=86400` steht im Widerspruch dazu. **Noch offen:** in
  welchem Takt sich `last-modified` wirklich bewegt. Der Sammler soll den Wert bei jedem
  Lauf mitschreiben, dann weiss man es nach einem Tag.
- `battlenet-schema: auctions`, Revision 1.

## Offene Punkte

- Takt der Aktualisierung (siehe oben).
- Ob `If-Modified-Since` respektiert wird und damit unveraenderte Haeuser ohne Download
  erkannt werden koennen.
- Welches der beiden Rollenspiel-Rulesets zu den Haeusern 119-121 und 123-125 gehoert.
