"""Eine lokale DuckDB-Datei, die alle Daten unter einem Dach abfragbar macht.

    data/local/forever.duckdb

Zwei Arten von Daten, zwei Arten, sie zu halten:

- Stammdaten - Items, Haendler und ihr Sortiment, Rezepte und ihre Zutaten -
  aendern sich nur mit einem neuen Spielstand. Sie stehen als Tabellen mit
  Schluesseln in der Datei; das Schema steht in schema.py.
- Staende, Verkaeufe und alles, was am stuendlichen Preis haengt, bleiben Sichten
  auf die Parquet-Dateien des Warehouse. Nach einem `git pull` sind sie ohne
  weiteres Zutun aktuell.

Die Tabellen sind eine Kopie und koennten veralten. Die Datei merkt sich deshalb,
woraus sie gebaut wurde. `sql` baut sie neu, sobald sich eine Quelle geaendert hat,
und die Abzugskommandos tun es am Ende von selbst. Wer die Datei mit einem anderen
Werkzeug oeffnet, ruft nach einem Abzug oder `git pull` einmal `db` auf.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import duckdb

from . import crafting, foreverdb_dump, names, schema, store
from .config import AH_KEEP, UNREACHABLE_SIDE, Settings

DB_NAME = "forever.duckdb"

# Leere Sichten mit den richtigen Spalten, falls ein Datensatz (noch) fehlt.
# So funktionieren die darauf aufbauenden Sichten trotzdem.
EMPTY = {
    "snapshots": (
        "snapshot_ts TIMESTAMP, house INTEGER, item_id INTEGER, kind VARCHAR, n_listings INTEGER, "
        "quantity BIGINT, min_price BIGINT, p25_price BIGINT, median_price BIGINT, "
        "total_value BIGINT, n_bid INTEGER"
    ),
    "sales": (
        "snapshot_ts TIMESTAMP, previous_ts TIMESTAMP, gap_hours DOUBLE, house INTEGER, item_id INTEGER, "
        "kind VARCHAR, n_sold INTEGER, qty_sold BIGINT, value_sold BIGINT, n_expired INTEGER, "
        "n_unclear INTEGER, n_new INTEGER, qty_new BIGINT"
    ),
    "runs": (
        "run_at TIMESTAMP, snapshot_ts TIMESTAMP, house INTEGER, auctions INTEGER, commodities INTEGER, "
        "items INTEGER, previous_ts TIMESTAMP, gap_hours DOUBLE, sold INTEGER, value_sold BIGINT, "
        "expired INTEGER, unclear INTEGER, new_listings INTEGER, bytes BIGINT, seconds DOUBLE"
    ),
}

# Die Felder der Item-Liste von ForeverDB, auf die die Sicht `items` zugreift.
FOREVERDB_ITEM_FIELDS: dict[str, str] = {
    "id": "INTEGER",
    "name": "VARCHAR",
    "quality": "VARCHAR",
    "itemLevel": "INTEGER",
    "requiredLevel": "INTEGER",
    "class": "VARCHAR",
    "subclass": "VARCHAR",
    "inventoryType": "VARCHAR",
    "icon": "VARCHAR",
    "url": "VARCHAR",
}
EMPTY["foreverdb_items"] = ", ".join(f'"{name}" {kind}' for name, kind in FOREVERDB_ITEM_FIELDS.items())

# Aus den einzeln abgezogenen Details braucht `items` diese Felder.
FOREVERDB_DETAIL_FIELDS: dict[str, str] = {
    "id": "INTEGER",
    "sellPrice": "BIGINT",
    "bonding": "VARCHAR",
    "disenchantable": "BOOLEAN",
    "unique": "BOOLEAN",
}
EMPTY["foreverdb_item_details"] = ", ".join(
    f'"{name}" {kind}' for name, kind in FOREVERDB_DETAIL_FIELDS.items()
)

# Ein Haendler mit seinem Sortiment, wie /vendors/{id} ihn liefert.
EMPTY["foreverdb_vendor_details"] = (
    "id INTEGER, name VARCHAR, title VARCHAR, side VARCHAR, zone VARCHAR, x DOUBLE, y DOUBLE, "
    "seenInForever BOOLEAN, reputationFaction STRUCT(id INTEGER, name VARCHAR), "
    "sells STRUCT(itemId INTEGER, name VARCHAR, price BIGINT, stack INTEGER, pricePerItem DOUBLE, "
    "limited BOOLEAN, limitedStockCount INTEGER, classicData BOOLEAN, seenInForever BOOLEAN)[]"
)


def _padded(con: duckdb.DuckDBPyConnection, source: str, required: dict[str, str]) -> str:
    """Ergaenzt fehlende Spalten als NULL.

    Aeltere Dateien kennen juengere Spalten nicht. Die abgeleiteten Sichten
    greifen aber auf feste Namen zu und sollen daran nicht scheitern.
    """
    have = {row[0] for row in con.execute(f"DESCRIBE {source}").fetchall()}
    missing = [f'NULL::{kind} AS "{name}"' for name, kind in required.items() if name not in have]
    if not missing:
        return source
    return f"SELECT *, {', '.join(missing)} FROM ({source})"


def db_path(settings: Settings) -> Path:
    return settings.local_dir / DB_NAME


def _empty_view(con: duckdb.DuckDBPyConnection, name: str, columns: str) -> None:
    con.execute(f"CREATE OR REPLACE TABLE _empty_{name} ({columns})")
    con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM _empty_{name}")


def _warehouse_view(con: duckdb.DuckDBPyConnection, name: str, warehouse: Path, dataset: str) -> bool:
    """Sicht ueber alle Dateien eines Datensatzes, gleich fuer welches Haus."""
    base = warehouse / dataset
    if not base.is_dir() or next(base.glob("house=*/dt=*/*.parquet"), None) is None:
        _empty_view(con, name, EMPTY[name])
        return False
    pattern = store.sql_path(base / "house=*" / "dt=*" / "*.parquet")
    con.execute(
        f"CREATE OR REPLACE VIEW {name} AS "
        f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = false, union_by_name = true)"
    )
    return True


def _blizzard_view(con: duckdb.DuckDBPyConnection, warehouse: Path) -> bool:
    base = names.ref_dir(warehouse)
    if not base.is_dir() or next(base.glob("dt=*.parquet"), None) is None:
        _empty_view(con, "blizzard_items", names.SCHEMA)
        return False
    pattern = store.sql_path(base / "dt=*.parquet")
    # Je Item die juengste Pruefung; nur was die API kennt. `raw` als JSON, damit
    # sich mit raw->>'$.preview_item.armor.value' hineingreifen laesst.
    source = _padded(
        con,
        f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = false, union_by_name = true) "
        "QUALIFY row_number() OVER (PARTITION BY item_id ORDER BY checked_at DESC) = 1",
        names.FIELDS,
    )
    con.execute(
        f"CREATE OR REPLACE VIEW blizzard_items AS "
        f"SELECT * EXCLUDE (raw), raw::JSON AS raw FROM ({source}) WHERE status = 200"
    )
    return True


def _foreverdb_views(con: duckdb.DuckDBPyConnection, settings: Settings) -> list[str]:
    """Eine Sicht je abgezogener Liste: foreverdb_items, foreverdb_vendors, ..."""
    directory = foreverdb_dump.dump_dir(settings)
    created = []
    for name in foreverdb_dump.LISTS:
        target = directory / f"{name}.jsonl"
        view = f"foreverdb_{name}"
        if target.is_file() and target.stat().st_size > 0:
            source = (
                f"SELECT * FROM read_json('{store.sql_path(target)}', format = 'newline_delimited', "
                "union_by_name = true, sample_size = -1)"
            )
            if name == "items":
                source = _padded(con, source, FOREVERDB_ITEM_FIELDS)
            con.execute(f"CREATE OR REPLACE VIEW {view} AS {source}")
            created.append(view)
        elif name == "items":
            _empty_view(con, view, EMPTY[view])

    # Die Details kommen einzeln und liegen in einer eigenen Datei.
    details = directory / foreverdb_dump.DETAILS_FILE
    if details.is_file() and details.stat().st_size > 0:
        source = _padded(
            con,
            f"SELECT * FROM read_json('{store.sql_path(details)}', format = 'newline_delimited', "
            "union_by_name = true, sample_size = -1, ignore_errors = true)",
            FOREVERDB_DETAIL_FIELDS,
        )
        # Eine nach einem Abbruch abgerissene letzte Zeile ergibt eine Zeile ohne id.
        con.execute(
            f"CREATE OR REPLACE VIEW foreverdb_item_details AS SELECT * FROM ({source}) WHERE id IS NOT NULL"
        )
        created.append("foreverdb_item_details")
    else:
        _empty_view(con, "foreverdb_item_details", EMPTY["foreverdb_item_details"])

    # Die Haendler mit Sortiment. Feste Spalten, damit die Sicht vendor_items auch dann
    # traegt, wenn ein Feld in den bisher abgezogenen Zeilen noch nie vorkam.
    source = vendor_details_source(settings)
    if source is not None:
        con.execute(f"CREATE OR REPLACE VIEW foreverdb_vendor_details AS {source}")
        created.append("foreverdb_vendor_details")
    else:
        _empty_view(con, "foreverdb_vendor_details", EMPTY["foreverdb_vendor_details"])

    # Die Rezepte der Berufe, ebenfalls mit festen Spalten. Darauf baut das Modell
    # fuers Herstellen auf (siehe crafting.py).
    source = crafting.recipes_source(settings)
    if source is not None:
        con.execute(f"CREATE OR REPLACE VIEW foreverdb_recipes AS {source}")
        created.append("foreverdb_recipes")
    else:
        _empty_view(con, "foreverdb_recipes", crafting.RECIPE_COLUMNS)
    # Abklingzeit und Zauberzeit aus der Spell-Liste - leer, solange es die nicht gibt.
    con.execute(f"CREATE OR REPLACE VIEW spell_timing AS {crafting.spell_timing_source(settings)}")
    return created


def vendor_details_source(settings: Settings) -> str | None:
    """Die abgezogenen Haendler als Abfrage, oder None, wenn es den Abzug nicht gibt."""
    vendors = foreverdb_dump.dump_dir(settings) / foreverdb_dump.VENDOR_DETAILS_FILE
    if not vendors.is_file() or vendors.stat().st_size == 0:
        return None
    columns = store.json_columns(EMPTY["foreverdb_vendor_details"])
    return (
        f"SELECT * FROM read_json('{store.sql_path(vendors)}', format = 'newline_delimited', "
        f"columns = {columns}, ignore_errors = true) WHERE id IS NOT NULL"
    )


MACROS = """
-- Geldbetraege lesbar machen: money(123456) -> '12g 34s 56c', money(-250) -> '-2s 50c'
CREATE OR REPLACE MACRO money(copper) AS
    CASE WHEN copper IS NULL THEN NULL ELSE
        CASE WHEN copper < 0 THEN '-' ELSE '' END ||
        CASE WHEN abs(copper) >= 10000 THEN (abs(copper)::BIGINT // 10000)::VARCHAR || 'g ' ELSE '' END ||
        CASE WHEN abs(copper) >= 100 THEN ((abs(copper)::BIGINT % 10000) // 100)::VARCHAR || 's ' ELSE '' END ||
        (abs(copper)::BIGINT % 100)::VARCHAR || 'c'
    END;

CREATE OR REPLACE MACRO gold(copper) AS round(copper / 10000.0, 2);
"""

# --- Stammdaten: womit die festen Tabellen gefuellt werden ---------------------------
# Jede Abfrage liefert je Schluessel genau eine Zeile, auch wenn eine Quelle einen
# Eintrag doppelt nennt. Sonst scheiterte der Bau an einem Primaerschluessel.

# Ein Item, wie beide Quellen zusammen es beschreiben. Blizzard gilt zuerst,
# ForeverDB fuellt auf, was Blizzard nicht kennt.
ITEMS_SELECT = """
SELECT coalesce(b.item_id, f.id)                       AS item_id,
       coalesce(b.name, f.name)                        AS name,
       upper(coalesce(b.quality, f.quality))           AS quality,
       coalesce(b.item_class, f."class")               AS item_class,
       coalesce(b.item_subclass, f.subclass)           AS item_subclass,
       coalesce(b.inventory_type, upper(replace(f.inventoryType, '-', '_')))
                                                       AS inventory_type,
       coalesce(b.level, f.itemLevel)                  AS item_level,
       coalesce(b.required_level, f.requiredLevel)     AS required_level,
       b.is_stackable,
       -- Was ein Haendler zahlt: von Blizzard, sonst aus den Details von ForeverDB.
       coalesce(b.sell_price, d.sellPrice)             AS vendor_sell,
       CASE WHEN b.purchase_price IS NOT NULL
            THEN b.purchase_price / greatest(coalesce(b.purchase_quantity, 1), 1)
       END                                             AS vendor_buy,
       coalesce(b.icon, f.icon)                        AS icon,
       f.url                                           AS foreverdb_url,
       d.bonding,
       d.disenchantable,
       b.item_id IS NOT NULL                           AS in_blizzard,
       f.id IS NOT NULL                                AS in_foreverdb,
       d.id IS NOT NULL                                AS has_details
FROM blizzard_items b
FULL OUTER JOIN (
    SELECT * FROM foreverdb_items WHERE id IS NOT NULL
    QUALIFY row_number() OVER (PARTITION BY id ORDER BY name) = 1
) f ON f.id = b.item_id
LEFT JOIN (
    SELECT * FROM foreverdb_item_details
    QUALIFY row_number() OVER (PARTITION BY id ORDER BY sellPrice DESC NULLS LAST) = 1
) d ON d.id = coalesce(b.item_id, f.id)"""

VENDORS_SELECT = """
SELECT v.id AS vendor_id, v.name, v.title, v.side, v.zone, v.x, v.y,
       v.reputationFaction.name AS reputation,
       v.seenInForever          AS seen_in_forever
FROM foreverdb_vendor_details v
QUALIFY row_number() OVER (PARTITION BY v.id ORDER BY len(v.sells) DESC NULLS LAST) = 1"""

# Fuehrt ein Haendler ein Item zweimal, gilt das guenstigere Angebot.
STOCK_SELECT = """
SELECT v.id            AS vendor_id,
       s.itemId        AS item_id,
       s.name          AS item_name,
       s.price,
       s.stack,
       s.pricePerItem  AS price_per_item,
       s.limited,
       s.limitedStockCount AS limited_stock,
       s.classicData   AS classic_data,
       s.seenInForever AS seen_in_forever
FROM foreverdb_vendor_details v, unnest(v.sells) AS t(s)
WHERE s.itemId IS NOT NULL
QUALIFY row_number() OVER (
    PARTITION BY v.id, s.itemId ORDER BY s.pricePerItem NULLS LAST, s.price NULLS LAST
) = 1"""

# Zum Herstellen taugt ein Haendler, den die Horde erreicht und der unbegrenzt liefert.
CRAFT_VENDORS = (
    "SELECT * FROM vendor_items "
    f"WHERE side <> '{UNREACHABLE_SIDE}' AND price_per_item > 0 AND NOT coalesce(limited, false)"
)


def _static_selects() -> dict[str, str]:
    """Tabelle -> Abfrage, die sie fuellt. Die Namen sind die aus schema.TABLES."""
    return {
        "items": ITEMS_SELECT,
        "vendors": VENDORS_SELECT,
        "vendor_stock": STOCK_SELECT,
        "vendor_prices": crafting.vendor_prices_select(CRAFT_VENDORS),
        **crafting.MODEL,
    }


# Was welcher Haendler verkauft, mit dem Haendler in jeder Zeile - bequemer abzufragen
# als vendor_stock und vendors einzeln. Braucht nur die Tabellen, nicht ihren Inhalt.
VENDOR_ITEMS_VIEW = """
CREATE OR REPLACE VIEW vendor_items AS
SELECT s.vendor_id, v.name AS vendor, v.title, v.side, v.zone, v.x, v.y, v.reputation,
       s.item_id, s.item_name, s.price, s.stack, s.price_per_item,
       s.limited, s.limited_stock, s.classic_data, s.seen_in_forever
FROM vendor_stock s
JOIN vendors v USING (vendor_id);
"""

# --- Sichten: alles, was am stuendlichen Stand haengt -------------------------------
VIEWS = f"""
-- Der juengste Stand, mit Namen und Haendlerpreisen.
CREATE OR REPLACE VIEW latest AS
SELECT s.snapshot_ts, s.house, s.item_id, i.name, i.quality, s.kind,
       s.n_listings, s.quantity, s.min_price, s.p25_price, s.median_price, s.total_value, s.n_bid,
       i.item_class, i.item_subclass, i.vendor_sell, i.vendor_buy
FROM snapshots s
LEFT JOIN items i USING (item_id)
WHERE s.snapshot_ts = (SELECT max(snapshot_ts) FROM snapshots);

-- Jeder Stand jedes Items, mit dem, was seit dem Stand davor verkauft wurde.
-- Wo es keinen Vergleich gab, sind die Verkaufsspalten NULL, nicht 0.
CREATE OR REPLACE VIEW history AS
SELECT s.snapshot_ts, s.house, s.item_id, i.name, s.kind,
       s.n_listings, s.quantity, s.min_price, s.median_price,
       v.gap_hours, v.n_sold, v.qty_sold, v.value_sold, v.n_expired, v.n_unclear, v.n_new, v.qty_new
FROM snapshots s
LEFT JOIN sales v
       ON v.snapshot_ts = s.snapshot_ts AND v.house = s.house AND v.item_id = s.item_id AND v.kind = s.kind
LEFT JOIN items i ON i.item_id = s.item_id;

-- Verkaeufe je Item und Tag. `hours_covered` sagt, wie viele Stunden des Tages
-- ueberhaupt durch Vergleiche gedeckt sind.
CREATE OR REPLACE VIEW sold_daily AS
SELECT v.snapshot_ts::DATE AS day, v.house, v.item_id, i.name, v.kind,
       sum(v.n_sold)::BIGINT     AS n_sold,
       sum(v.qty_sold)::BIGINT   AS qty_sold,
       sum(v.value_sold)::BIGINT AS value_sold,
       round(sum(v.gap_hours), 1) AS hours_covered
FROM sales v
LEFT JOIN items i ON i.item_id = v.item_id
GROUP BY ALL;

-- Beim Haendler kaufen, im Auktionshaus verkaufen: je Item der guenstigste Haendler,
-- den die Horde erreicht, gegen das guenstigste Angebot im Auktionshaus.
-- `profit` rechnet die Gebuehr des Auktionshauses schon ab.
CREATE OR REPLACE VIEW vendor_flips AS
WITH cheapest AS (
    SELECT * FROM vendor_items
    WHERE side <> '{UNREACHABLE_SIDE}' AND price_per_item > 0
    QUALIFY row_number() OVER (PARTITION BY item_id ORDER BY price_per_item, vendor_id) = 1
),
sold AS (
    SELECT item_id, sum(qty_sold) AS qty_sold, sum(hours_covered) AS hours
    FROM sold_daily WHERE day >= current_date - 1 GROUP BY item_id
)
SELECT l.item_id, l.name, i.item_class, i.item_subclass,
       c.price_per_item                                  AS vendor_price,
       l.min_price                                       AS ah_price,
       round(l.min_price * {AH_KEEP} - c.price_per_item)::BIGINT AS profit,
       round((l.min_price * {AH_KEEP} - c.price_per_item) * 100.0 / c.price_per_item)::INTEGER
                                                         AS profit_pct,
       l.n_listings,
       s.qty_sold                                        AS sold_recently,
       c.limited, c.limited_stock,
       c.vendor, c.zone, c.side, c.reputation,
       c.seen_in_forever
FROM latest l
JOIN cheapest c USING (item_id)
JOIN items i USING (item_id)
LEFT JOIN sold s USING (item_id)
WHERE l.min_price * {AH_KEEP} > c.price_per_item;

-- Je Item das guenstigste Angebot im Auktionshaus, mit den Verkaeufen der letzten
-- 24 Stunden vor dem juengsten Stand.
CREATE OR REPLACE VIEW ah_prices AS
WITH sold AS (
    SELECT item_id, kind, sum(qty_sold) AS qty_sold_24h, sum(gap_hours) AS sales_hours_24h
    FROM sales
    WHERE snapshot_ts > (SELECT max(snapshot_ts) FROM snapshots) - INTERVAL 24 HOUR
    GROUP BY item_id, kind
)
SELECT l.item_id, l.kind, l.min_price AS ah_price, l.n_listings,
       s.qty_sold_24h, s.sales_hours_24h, l.item_class, l.item_subclass
FROM latest l
LEFT JOIN sold s ON s.item_id = l.item_id AND s.kind = l.kind
WHERE l.min_price > 0
QUALIFY row_number() OVER (PARTITION BY l.item_id ORDER BY l.min_price, l.kind) = 1;
"""


def _schema_version() -> str:
    """Aendert sich, sobald sich eine Tabelle, eine Abfrage oder eine Sicht aendert."""
    parts = [
        *schema.TABLES.values(), schema.BUILD_INFO, MACROS, *_static_selects().values(),
        VENDOR_ITEMS_VIEW, VIEWS, crafting.costs_sql("VIEW"), crafting.RECIPE_COLUMNS,
        json.dumps(EMPTY, sort_keys=True),
    ]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def fingerprint(settings: Settings) -> str:
    """Woraus die Datei gebaut wird: Schema, Ordner und die Dateien der Stammdaten.

    Stimmt der Wert nicht mehr mit dem ueberein, der in der Datei steht, sind ihre
    Tabellen veraltet. Die Staende zaehlen nicht mit - auf die schauen Sichten.
    """
    entries: list[list[Any]] = [["schema", _schema_version()], ["data", settings.data_dir.as_posix()]]
    sources = [
        ("foreverdb", foreverdb_dump.dump_dir(settings), "*.jsonl"),
        ("ref", names.ref_dir(settings.warehouse_dir), "dt=*.parquet"),
    ]
    for label, directory, pattern in sources:
        for file in sorted(directory.glob(pattern)) if directory.is_dir() else []:
            stat = file.stat()
            entries.append([f"{label}/{file.name}", stat.st_size, stat.st_mtime_ns])
    # Fehlt ein Datensatz beim Bau, steht an seiner Stelle eine leere Sicht.
    for dataset in (store.ITEMS, store.SALES, store.RUNS):
        base = settings.warehouse_dir / dataset
        entries.append([dataset, base.is_dir() and next(base.glob("house=*/dt=*/*.parquet"), None) is not None])
    return json.dumps(entries, separators=(",", ":"))


def is_stale(settings: Settings) -> bool:
    """Fehlt die Datei, oder haben sich die Stammdaten seit dem Bau geaendert?"""
    path = db_path(settings)
    if not path.is_file():
        return True
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error:
        return False        # gerade woanders geoeffnet: neu bauen ginge ohnehin nicht
    try:
        row = con.execute("SELECT sources FROM build_info").fetchone()
    except duckdb.Error:
        return True         # eine Datei aus der Zeit vor den Tabellen
    finally:
        con.close()
    return row is None or row[0] != fingerprint(settings)


def build(settings: Settings) -> dict[str, Any]:
    """Baut die Datei neu. Erst daneben, dann umbenennen - eine geoeffnete alte bleibt heil."""
    path = db_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    sources = fingerprint(settings)

    con = duckdb.connect(str(temporary))
    try:
        # 1. Sichten auf die Dateien, wie sie sind.
        warehouse = settings.warehouse_dir
        present = {
            "snapshots": _warehouse_view(con, "snapshots", warehouse, store.ITEMS),
            "sales": _warehouse_view(con, "sales", warehouse, store.SALES),
            "runs": _warehouse_view(con, "runs", warehouse, store.RUNS),
            "blizzard_items": _blizzard_view(con, warehouse),
        }
        for view in _foreverdb_views(con, settings):
            present[view] = True
        present.setdefault("foreverdb_items", False)
        present.setdefault("foreverdb_item_details", False)
        present.setdefault("foreverdb_vendor_details", False)
        present.setdefault("foreverdb_recipes", False)
        con.execute(MACROS)

        # 2. Die Stammdaten in feste Tabellen. Erst alle anlegen, dann in derselben
        #    Reihenfolge fuellen: so steht der Kopf vor den Zeilen, die auf ihn verweisen.
        for ddl in schema.TABLES.values():
            con.execute(ddl)
        con.execute(schema.BUILD_INFO)
        con.execute(VENDOR_ITEMS_VIEW)
        selects = _static_selects()
        for name in schema.TABLES:
            con.execute(f"INSERT INTO {name} BY NAME {selects[name]}")
        con.execute(
            "INSERT INTO build_info VALUES (?, ?)",
            [dt.datetime.now(dt.timezone.utc).replace(tzinfo=None), sources],
        )

        # 3. Was am stuendlichen Stand haengt, als Sichten darueber - mit denselben
        #    Definitionen, mit denen auch die Anzeige-Dateien gebaut werden.
        con.execute(VIEWS)
        con.execute(crafting.costs_sql("CREATE OR REPLACE VIEW"))

        tables = list(schema.TABLES)
        views = [
            row[0]
            for row in con.execute(
                "SELECT view_name FROM duckdb_views() WHERE NOT internal ORDER BY view_name"
            ).fetchall()
        ]
        counts = {
            name: con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            for name in sorted(tables + views)
        }
        # Verweise auf Items, die die Item-Tabelle nicht kennt (siehe schema.py).
        dangling = {
            f"{table}.{column}": con.execute(
                f"SELECT count(DISTINCT {column}) FROM {table} "
                f"WHERE {column} IS NOT NULL AND {column} NOT IN (SELECT item_id FROM items)"
            ).fetchone()[0]
            for table, column in schema.ITEM_REFERENCES
        }
    finally:
        con.close()

    try:
        os.replace(temporary, path)
    except PermissionError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"{path} ist gerade in einem anderen Programm geoeffnet. Dort schliessen und erneut bauen."
        ) from exc
    return {"path": path, "counts": counts, "present": present, "tables": tables, "dangling": dangling}


def refresh(settings: Settings) -> str | None:
    """Baut die Datei neu, wenn es sie gibt und ihre Stammdaten veraltet sind.

    Gibt einen Satz dazu zurueck, oder None, wenn nichts zu tun war. Wer die
    Datenbank nie gebaut hat, bekommt hier auch keine.
    """
    if not db_path(settings).is_file() or not is_stale(settings):
        return None
    try:
        build(settings)
    except RuntimeError as exc:
        return f"Die Datenbank ist veraltet, liess sich aber nicht neu bauen: {exc}"
    return "Die Stammdaten haben sich geaendert - Datenbank neu gebaut."


def query(settings: Settings, sql: str, max_rows: int = 50) -> None:
    """Fuehrt eine Abfrage aus und gibt das Ergebnis als Tabelle aus."""
    path = db_path(settings)
    if not path.is_file():
        raise RuntimeError(f"{path} gibt es noch nicht. Erst `python -m collector db` ausfuehren.")
    note = refresh(settings)
    if note:
        print(note, file=sys.stderr)
    # Die Tabellenlinien sind keine ASCII-Zeichen; die Windows-Konsole braucht UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    con = duckdb.connect(str(path), read_only=True)
    try:
        con.sql(sql).show(max_rows=max_rows, max_width=200)
    finally:
        con.close()


def main(settings: Settings) -> int:
    try:
        result = build(settings)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{result['path']}")
    tables = set(result["tables"])
    for title, wanted in (("Tabellen (Stammdaten)", True), ("Sichten", False)):
        print(title)
        for name, count in result["counts"].items():
            if (name in tables) is not wanted:
                continue
            note = "" if result["present"].get(name, True) else "  (Quelle fehlt noch)"
            print(f"  {name:<24} {count:>10,} Zeilen{note}")
    dangling = {reference: count for reference, count in result["dangling"].items() if count}
    if dangling:
        print("Verweise auf Items, die die Item-Tabelle nicht kennt:")
        for reference, count in dangling.items():
            print(f"  {reference:<24} {count:>10,}")
    return 0
