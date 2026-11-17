"""Baut aus dem Warehouse die Dateien, die die Anzeige liest.

Das Warehouse hat eine Datei je Stand - gut zum Sammeln, schlecht zum Anzeigen:
der Verlauf eines Items ueber 14 Tage laege in 336 Dateien. Hier entsteht daraus
eine Form, die ein Browser mit wenigen Teilabrufen lesen kann:

    hourly.parquet   alle Staende des Zeitfensters, nach Item sortiert und in
                     kleine Zeilengruppen geschnitten. Wer ein Item will, liest
                     am Dateiende nach, in welcher Gruppe es liegt, und holt nur die.
    market.parquet   der juengste Stand, eine Zeile je Item, dazu 24-Stunden-Werte.
    meta.json        was drin ist und von wann.

Diese Dateien sind abgeleitet und jederzeit neu baubar. Sie gehoeren deshalb
nicht ins Warehouse und nicht in Git.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import duckdb

from . import names, store
from .config import ROOT, Settings

HOURLY = "hourly.parquet"
MARKET = "market.parquet"
META = "meta.json"
NAMES = "names.json"      # optional: {"2589": "Leinenstoff", ...}

DEFAULT_OUT = ROOT / "web" / "public" / "data"
DEFAULT_DAYS = 14

# Klein genug, dass ein Item nur einen Bruchteil der Datei kostet, gross genug,
# dass das Verzeichnis am Dateiende nicht selbst zur Last wird.
ROW_GROUP_SIZE = 8192

# Die Anzeige liest mit einem schlanken Parquet-Leser, der Snappy ohne
# Zusatzpaket versteht. zstd waere kleiner, braeuchte im Browser aber 75 KB mehr.
COMPRESSION = "snappy"

EMPTY_SALES = """
    CREATE OR REPLACE TEMP TABLE s (
        snapshot_ts TIMESTAMP, item_id INTEGER, kind VARCHAR, gap_hours DOUBLE,
        n_sold INTEGER, qty_sold BIGINT, value_sold BIGINT, n_new INTEGER, qty_new BIGINT
    )
"""


def _load(con: duckdb.DuckDBPyConnection, warehouse: Path, house: int) -> None:
    items = store.dataset_glob(warehouse, store.ITEMS, house)
    if items is None:
        raise RuntimeError(
            f"Im Warehouse {warehouse} liegt noch kein Stand fuer Haus {house}. "
            "Erst `git -C data/warehouse pull` oder `python -m collector collect`."
        )
    # Haus und Tag stehen auch im Pfad; die Spalten in der Datei genuegen.
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE i AS "
        f"SELECT * FROM read_parquet('{items}', hive_partitioning = false)"
    )

    sales = store.dataset_glob(warehouse, store.SALES, house)
    if sales is None:
        con.execute(EMPTY_SALES)
    else:
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE s AS "
            f"SELECT * FROM read_parquet('{sales}', hive_partitioning = false)"
        )


def _build_hourly(con: duckdb.DuckDBPyConnection, since: dt.datetime) -> int:
    """Eine Zeile je Item und Stand. Zeit als Unix-Sekunden, Preise als DOUBLE:
    beides kommt im Browser als gewoehnliche Zahl an, ohne BigInt und ohne Datumsobjekte."""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE hourly AS
        SELECT i.item_id::INTEGER             AS item_id,
               i.kind                         AS kind,
               epoch(i.snapshot_ts)::INTEGER  AS ts,
               i.min_price::DOUBLE            AS min_price,
               i.p25_price::DOUBLE            AS p25_price,
               i.median_price::DOUBLE         AS median_price,
               i.n_listings::INTEGER          AS n_listings,
               i.quantity::DOUBLE             AS quantity,
               s.n_sold::INTEGER              AS n_sold,
               s.qty_sold::DOUBLE             AS qty_sold,
               s.value_sold::DOUBLE           AS value_sold,
               s.qty_new::DOUBLE              AS qty_new,
               s.gap_hours::FLOAT             AS gap_hours
        FROM i
        LEFT JOIN s
               ON s.snapshot_ts = i.snapshot_ts AND s.item_id = i.item_id AND s.kind = i.kind
        WHERE i.snapshot_ts >= ?
        """,
        [since],
    )
    return con.execute("SELECT count(*) FROM hourly").fetchone()[0]


def _build_market(con: duckdb.DuckDBPyConnection) -> int:
    """Der juengste Stand mit dem, was eine Uebersichtstabelle braucht."""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE market AS
        WITH latest AS (SELECT max(ts) AS ts FROM hourly),
        cur AS (SELECT h.* FROM hourly h, latest WHERE h.ts = latest.ts),
        day AS (
            SELECT h.item_id, h.kind,
                   count(*)::INTEGER             AS snapshots_24h,
                   sum(h.qty_sold)               AS qty_sold_24h,
                   sum(h.value_sold)             AS value_sold_24h,
                   -- Wie viele der 24 Stunden ueberhaupt durch Vergleiche gedeckt sind.
                   -- Steht hier 6, sind die Verkaufszahlen ein Viertel der Wahrheit.
                   sum(h.gap_hours) FILTER (WHERE h.n_sold IS NOT NULL)::FLOAT
                                                 AS sales_hours_24h,
                   min(h.min_price)              AS low_24h,
                   max(h.min_price)              AS high_24h,
                   arg_min(h.min_price, h.ts)    AS open_24h
            FROM hourly h, latest
            WHERE h.ts > latest.ts - 86400
            GROUP BY h.item_id, h.kind
        )
        SELECT cur.item_id, cur.kind, cur.ts,
               cur.min_price, cur.p25_price, cur.median_price, cur.n_listings, cur.quantity,
               day.snapshots_24h, day.qty_sold_24h, day.value_sold_24h, day.sales_hours_24h,
               day.low_24h, day.high_24h, day.open_24h,
               CASE WHEN day.open_24h > 0
                    THEN round((cur.min_price - day.open_24h) * 100.0 / day.open_24h, 1)
               END AS change_24h_pct,
               -- Was ein Haendler zahlt, und sein Listenpreis je Stueck. Der Listenpreis
               -- steht bei jedem Item, auch wenn es kein Haendler fuehrt.
               k.sell_price::DOUBLE AS vendor_sell,
               (k.purchase_price::DOUBLE / greatest(coalesce(k.purchase_quantity, 1), 1))
                   AS vendor_buy
        FROM cur
        LEFT JOIN day ON day.item_id = cur.item_id AND day.kind = cur.kind
        LEFT JOIN known k ON k.item_id = cur.item_id AND k.status = 200
        """
    )
    return con.execute("SELECT count(*) FROM market").fetchone()[0]


def _iso(epoch_seconds: int | None) -> str | None:
    if epoch_seconds is None:
        return None
    return dt.datetime.fromtimestamp(epoch_seconds, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(
    settings: Settings,
    out_dir: Path = DEFAULT_OUT,
    house: int | None = None,
    days: int = DEFAULT_DAYS,
) -> dict[str, Any]:
    house = house or settings.house
    out_dir = Path(out_dir)

    con = store.connect()
    try:
        _load(con, settings.warehouse_dir, house)
        last = con.execute("SELECT max(snapshot_ts) FROM i").fetchone()[0]
        since = last - dt.timedelta(days=days)

        hourly_rows = _build_hourly(con, since)
        # Stammdaten (Namen, Haendlerpreise) stehen im Warehouse unter ref/items.
        names.load_known(con, settings.warehouse_dir)
        market_rows = _build_market(con)

        store.write_parquet(
            con, "hourly", out_dir / HOURLY,
            order_by="item_id, kind, ts",
            compression=COMPRESSION, row_group_size=ROW_GROUP_SIZE,
        )
        store.write_parquet(
            con, "market", out_dir / MARKET,
            order_by="item_id, kind", compression=COMPRESSION,
        )

        # Ohne Namen zeigt die Seite "Item 2589".
        item_names = names.names_from_known(con)
        names_file = out_dir / NAMES
        if item_names:
            names_file.write_text(
                json.dumps(item_names, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
        named_in_market = con.execute(
            "SELECT count(DISTINCT item_id) FROM market WHERE item_id IN "
            "(SELECT item_id FROM known WHERE status = 200 AND name IS NOT NULL)"
        ).fetchone()[0] if item_names else 0

        first_ts, last_ts, snapshots, with_sales = con.execute(
            "SELECT min(ts), max(ts), count(DISTINCT ts), "
            "count(DISTINCT ts) FILTER (WHERE n_sold IS NOT NULL) FROM hourly"
        ).fetchone()
        row_groups = con.execute(
            f"SELECT count(DISTINCT row_group_id) FROM parquet_metadata('{store.sql_path(out_dir / HOURLY)}')"
        ).fetchone()[0]
    finally:
        con.close()

    meta = {
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "house": house,
        "window_days": days,
        "first_snapshot": _iso(first_ts),
        "last_snapshot": _iso(last_ts),
        "snapshots": snapshots,
        "snapshots_with_sales": with_sales,
        "items": market_rows,
        # Die Seite fragt names.json nur ab, wenn hier true steht.
        "names": (out_dir / NAMES).is_file(),
        "items_with_name": named_in_market,
        "files": {
            HOURLY: {
                "rows": hourly_rows,
                "bytes": (out_dir / HOURLY).stat().st_size,
                "row_groups": row_groups,
                "sorted_by": ["item_id", "kind", "ts"],
            },
            MARKET: {"rows": market_rows, "bytes": (out_dir / MARKET).stat().st_size},
        },
    }
    (out_dir / META).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main(settings: Settings, out_dir: Path | None = None, house: int | None = None, days: int = DEFAULT_DAYS) -> int:
    try:
        meta = build(settings, out_dir=out_dir or DEFAULT_OUT, house=house, days=days)
    except RuntimeError as exc:
        print(exc)
        return 1

    target = Path(out_dir or DEFAULT_OUT)
    hourly = meta["files"][HOURLY]
    market = meta["files"][MARKET]
    print(f"Haus {meta['house']}, {meta['snapshots']} Staende von {meta['first_snapshot']} bis {meta['last_snapshot']}")
    print(f"  davon mit Verkaufsdaten: {meta['snapshots_with_sales']}")
    print(
        f"  {HOURLY:<15} {hourly['rows']:>9,} Zeilen, {hourly['bytes'] / 1024:>8,.0f} KB, "
        f"{hourly['row_groups']} Zeilengruppen"
    )
    print(f"  {MARKET:<15} {market['rows']:>9,} Zeilen, {market['bytes'] / 1024:>8,.0f} KB")
    print(f"  Namen fuer {meta['items_with_name']:,} von {meta['items']:,} Items")
    print(f"  nach {target}")
    return 0
