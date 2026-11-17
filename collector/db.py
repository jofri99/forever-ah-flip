"""Eine lokale DuckDB-Datei, die alle Daten unter einem Dach abfragbar macht.

    data/local/forever.duckdb

Die Datei enthaelt keine Daten, nur Sichten. Jede Sicht schaut auf die Dateien,
die ohnehin da sind - die Staende im Warehouse, die Stammdaten, den Abzug von
ForeverDB. Nach einem `git pull` oder einem neuen Abzug ist die Datenbank
deshalb ohne weiteres Zutun aktuell, und es gibt keine zweite Kopie, die
veralten koennte.

Neu gebaut werden muss sie nur, wenn sich die Sichten selbst aendern oder das
Projekt in einen anderen Ordner zieht - die Pfade stehen in den Sichten.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import duckdb

from . import foreverdb_dump, names, store
from .config import Settings

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
    return created


DERIVED = """
-- Geldbetraege lesbar machen: money(123456) -> '12g 34s 56c'
CREATE OR REPLACE MACRO money(copper) AS
    CASE WHEN copper IS NULL THEN NULL ELSE
        CASE WHEN copper >= 10000 THEN (copper::BIGINT // 10000)::VARCHAR || 'g ' ELSE '' END ||
        CASE WHEN copper >= 100 THEN ((copper::BIGINT % 10000) // 100)::VARCHAR || 's ' ELSE '' END ||
        (copper::BIGINT % 100)::VARCHAR || 'c'
    END;

CREATE OR REPLACE MACRO gold(copper) AS round(copper / 10000.0, 2);

-- Ein Item, wie es beide Quellen zusammen beschreiben. Blizzard gilt zuerst,
-- ForeverDB fuellt auf, was Blizzard nicht kennt.
CREATE OR REPLACE VIEW items AS
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
       b.sell_price                                    AS vendor_sell,
       CASE WHEN b.purchase_price IS NOT NULL
            THEN b.purchase_price / greatest(coalesce(b.purchase_quantity, 1), 1)
       END                                             AS vendor_buy,
       coalesce(b.icon, f.icon)                        AS icon,
       f.url                                           AS foreverdb_url,
       b.item_id IS NOT NULL                           AS in_blizzard,
       f.id IS NOT NULL                                AS in_foreverdb
FROM blizzard_items b
FULL OUTER JOIN foreverdb_items f ON f.id = b.item_id;

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
"""


def build(settings: Settings) -> dict[str, Any]:
    """Baut die Datei neu. Erst daneben, dann umbenennen - eine geoeffnete alte bleibt heil."""
    path = db_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)

    con = duckdb.connect(str(temporary))
    try:
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
        con.execute(DERIVED)

        views = [
            row[0]
            for row in con.execute(
                "SELECT view_name FROM duckdb_views() WHERE NOT internal ORDER BY view_name"
            ).fetchall()
        ]
        counts = {view: con.execute(f"SELECT count(*) FROM {view}").fetchone()[0] for view in views}
    finally:
        con.close()

    try:
        os.replace(temporary, path)
    except PermissionError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"{path} ist gerade in einem anderen Programm geoeffnet. Dort schliessen und erneut bauen."
        ) from exc
    return {"path": path, "counts": counts, "present": present}


def query(settings: Settings, sql: str, max_rows: int = 50) -> None:
    """Fuehrt eine Abfrage aus und gibt das Ergebnis als Tabelle aus."""
    path = db_path(settings)
    if not path.is_file():
        raise RuntimeError(f"{path} gibt es noch nicht. Erst `python -m collector db` ausfuehren.")
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
    for view, count in result["counts"].items():
        note = "" if result["present"].get(view, True) else "  (Quelle fehlt noch)"
        print(f"  {view:<17} {count:>10,} Zeilen{note}")
    return 0
