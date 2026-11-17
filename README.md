# Daten

Dieser Branch enthaelt nur Daten, keinen Code. Er wird stuendlich von GitHub Actions
beschrieben (Workflow `collect` im Branch `main`) und hat mit `main` keine gemeinsame
Historie.

Gesammelt wird **Haus 114**: das Auktionshaus der Horde im Ruleset Normal von
World of Warcraft: Forever, Region EU.

## Aufbau

Eine Datei je Stand, einmal geschrieben und nie wieder angefasst. Zeiten sind UTC.

```
items/house=114/dt=2026-11-17/081855.parquet   je Item eine Zeile
sales/house=114/dt=2026-11-17/081855.parquet   Vergleich mit dem Stand davor
runs/house=114/dt=2026-11-17/081855.parquet    eine Zeile Protokoll
```

### items

| Spalte | Bedeutung |
|---|---|
| `snapshot_ts` | Stand der Daten laut Blizzard |
| `house` | Auktionshaus |
| `item_id` | Item |
| `kind` | `auction` (Einzelstuecke) oder `commodity` (Stapelware) |
| `n_listings` | Anzahl Angebote |
| `quantity` | angebotene Stueckzahl insgesamt |
| `min_price`, `p25_price`, `median_price` | Stueckpreise in Kupfer |
| `total_value` | Summe aus Stueckpreis mal Menge |
| `n_bid` | Angebote, auf die geboten wurde |

### sales

Auktionen haben IDs. Was zwischen zwei Staenden verschwindet, wird nach seiner letzten
Restzeit eingeordnet: `n_sold` nur, wenn die Auktion in der Zwischenzeit gar nicht ablaufen
konnte. Stornierte Auktionen sind von gekauften nicht zu unterscheiden und zaehlen mit.

| Spalte | Bedeutung |
|---|---|
| `snapshot_ts`, `previous_ts`, `gap_hours` | die beiden verglichenen Staende und ihr Abstand |
| `n_sold`, `qty_sold`, `value_sold` | sicher vor Ablauf verschwunden |
| `n_expired` | zuletzt mit unter 30 Minuten Restzeit gesehen |
| `n_unclear` | verschwunden, haette aber auch ablaufen koennen |
| `n_new`, `qty_new` | neu eingestellt |

Fehlt eine `sales`-Datei zu einem Stand, lag kein Vergleichsstand vor.

## Lesen

Mit DuckDB direkt, Haus und Tag kommen aus dem Pfad:

```sql
SELECT snapshot_ts, min_price, n_listings
FROM read_parquet('items/*/*/*.parquet', hive_partitioning = true)
WHERE item_id = 12359
ORDER BY snapshot_ts;
```
