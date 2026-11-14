"""Ein Durchlauf: ein Auktionshaus holen, verdichten, Verkaeufe ableiten, ablegen.

Gespeichert wird nicht jede einzelne Auktion - das waeren Gigabyte pro Monat -,
sondern je Stand eine Zeile pro Item, dazu die abgeleiteten Verkaeufe. Die rohe
Momentaufnahme bleibt nur bis zum naechsten Durchlauf liegen, weil der Vergleich
zweier Staende ueber die Auktions-IDs laeuft.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import duckdb

from . import store
from .blizzard import BlizzardClient
from .config import Settings

log = logging.getLogger(__name__)

# Feste Schemata statt Rateschema: `bid` steht nur bei wenigen Auktionen, eine
# Stichprobe wuerde die Spalte sonst uebersehen.
AUCTION_COLUMNS = (
    "{'auctions': 'STRUCT("
    "id BIGINT, item STRUCT(id INTEGER), buyout BIGINT, bid BIGINT, "
    "quantity INTEGER, time_left VARCHAR)[]'}"
)
COMMODITY_COLUMNS = (
    "{'auctions': 'STRUCT("
    "id BIGINT, item STRUCT(id INTEGER), unit_price BIGINT, "
    "quantity INTEGER, time_left VARCHAR)[]'}"
)
MAX_OBJECT = 400_000_000

# Wie lange eine Auktion laut time_left mindestens noch laeuft. Verschwindet sie
# frueher, kann sie nicht abgelaufen sein - dann wurde sie gekauft oder storniert.
MIN_HOURS_LEFT = {"VERY_LONG": 12.0, "LONG": 2.0, "MEDIUM": 0.5}


def _read_json_sql(path: Path, columns: str) -> str:
    return (
        f"SELECT unnest(auctions) AS x FROM read_json('{store.sql_path(path)}', "
        f"columns = {columns}, maximum_object_size = {MAX_OBJECT})"
    )


def load_snapshot(
    con: duckdb.DuckDBPyConnection, auctions: Path, commodities: Path | None = None
) -> int:
    """Baut die Tabelle `snap`: eine Zeile je Auktion, Stueckpreise vereinheitlicht."""
    parts = [
        f"""
        SELECT x.id AS auction_id,
               x.item.id AS item_id,
               'auction' AS kind,
               x.quantity AS quantity,
               x.buyout AS unit_price,
               x.bid AS bid,
               x.time_left AS time_left
        FROM ({_read_json_sql(auctions, AUCTION_COLUMNS)})
        """
    ]
    if commodities is not None and commodities.exists():
        parts.append(
            f"""
            SELECT x.id AS auction_id,
                   x.item.id AS item_id,
                   'commodity' AS kind,
                   x.quantity AS quantity,
                   x.unit_price AS unit_price,
                   NULL::BIGINT AS bid,
                   x.time_left AS time_left
            FROM ({_read_json_sql(commodities, COMMODITY_COLUMNS)})
            """
        )

    con.execute("CREATE OR REPLACE TEMP TABLE snap AS " + " UNION ALL BY NAME ".join(parts))
    return con.execute("SELECT count(*) FROM snap").fetchone()[0]


def aggregate_items(
    con: duckdb.DuckDBPyConnection, snapshot_ts: dt.datetime, house: int
) -> int:
    """Verdichtet `snap` auf eine Zeile je Item und Art."""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE items AS
        SELECT ?::TIMESTAMP           AS snapshot_ts,
               ?::INTEGER             AS house,
               item_id,
               kind,
               count(*)::INTEGER                                   AS n_listings,
               sum(quantity)::BIGINT                               AS quantity,
               min(unit_price) FILTER (WHERE unit_price > 0)       AS min_price,
               round(quantile_cont(unit_price, 0.25)
                     FILTER (WHERE unit_price > 0))::BIGINT        AS p25_price,
               round(median(unit_price)
                     FILTER (WHERE unit_price > 0))::BIGINT        AS median_price,
               sum(unit_price * quantity)::BIGINT                  AS total_value,
               count(*) FILTER (WHERE bid IS NOT NULL)::INTEGER    AS n_bid
        FROM snap
        GROUP BY item_id, kind
        """,
        [snapshot_ts, house],
    )
    return con.execute("SELECT count(*) FROM items").fetchone()[0]


def diff_sales(
    con: duckdb.DuckDBPyConnection,
    snapshot_ts: dt.datetime,
    previous_ts: dt.datetime,
    house: int,
) -> int:
    """Vergleicht `prev` mit `snap` und leitet daraus Verkaeufe und Neuzugaenge ab.

    Verschwundene Auktionen werden nach ihrer letzten Restzeit eingeordnet. Nur
    was gar nicht abgelaufen sein kann, zaehlt als verkauft - und das schliesst
    stornierte Auktionen mit ein, die sind von aussen nicht zu unterscheiden.
    """
    gap_hours = (snapshot_ts - previous_ts).total_seconds() / 3600.0

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE sales AS
        WITH gone AS (
            SELECT p.* FROM prev p
            WHERE NOT EXISTS (SELECT 1 FROM snap s WHERE s.auction_id = p.auction_id)
        ),
        classified AS (
            SELECT item_id, kind, quantity, unit_price,
                   CASE
                       WHEN time_left = 'VERY_LONG' AND ? < 12.0 THEN 'sold'
                       WHEN time_left = 'LONG'      AND ? <  2.0 THEN 'sold'
                       WHEN time_left = 'MEDIUM'    AND ? <  0.5 THEN 'sold'
                       WHEN time_left = 'SHORT'                  THEN 'expired'
                       ELSE 'unclear'
                   END AS fate
            FROM gone
        ),
        agg_gone AS (
            SELECT item_id, kind,
                   count(*) FILTER (WHERE fate = 'sold')::INTEGER                AS n_sold,
                   coalesce(sum(quantity) FILTER (WHERE fate = 'sold'), 0)::BIGINT
                                                                                 AS qty_sold,
                   coalesce(sum(unit_price * quantity)
                            FILTER (WHERE fate = 'sold'), 0)::BIGINT             AS value_sold,
                   count(*) FILTER (WHERE fate = 'expired')::INTEGER             AS n_expired,
                   count(*) FILTER (WHERE fate = 'unclear')::INTEGER             AS n_unclear
            FROM classified GROUP BY item_id, kind
        ),
        agg_new AS (
            SELECT item_id, kind,
                   count(*)::INTEGER     AS n_new,
                   sum(quantity)::BIGINT AS qty_new
            FROM snap s
            WHERE NOT EXISTS (SELECT 1 FROM prev p WHERE p.auction_id = s.auction_id)
            GROUP BY item_id, kind
        )
        SELECT ?::TIMESTAMP AS snapshot_ts,
               ?::TIMESTAMP AS previous_ts,
               ?::DOUBLE    AS gap_hours,
               ?::INTEGER   AS house,
               item_id,
               kind,
               coalesce(n_sold, 0)::INTEGER     AS n_sold,
               coalesce(qty_sold, 0)::BIGINT    AS qty_sold,
               coalesce(value_sold, 0)::BIGINT  AS value_sold,
               coalesce(n_expired, 0)::INTEGER  AS n_expired,
               coalesce(n_unclear, 0)::INTEGER  AS n_unclear,
               coalesce(n_new, 0)::INTEGER      AS n_new,
               coalesce(qty_new, 0)::BIGINT     AS qty_new
        FROM agg_gone FULL OUTER JOIN agg_new USING (item_id, kind)
        """,
        [gap_hours, gap_hours, gap_hours, snapshot_ts, previous_ts, gap_hours, house],
    )
    return con.execute("SELECT count(*) FROM sales").fetchone()[0]


def run(
    settings: Settings,
    house: int | None = None,
    force: bool = False,
    keep_raw: bool = False,
) -> dict[str, Any]:
    house = house or settings.house
    warehouse = settings.warehouse_dir
    raw_dir = settings.raw_dir / "current"
    runs_path = store.dataset_path(warehouse, store.RUNS)
    state_path = store.dataset_path(warehouse, store.SNAPSHOT)

    started = dt.datetime.now(dt.timezone.utc)
    result: dict[str, Any] = {"house": house, "skipped": False}

    con = store.connect()
    # Blizzard beantwortet If-Modified-Since mit 304. Damit kostet ein Durchlauf
    # ohne neue Daten nichts, und der Cron darf oefter laufen als der Stundentakt.
    known = None if force else store.last_seen_modified(con, runs_path)

    with BlizzardClient(settings) as client:
        auctions_file = raw_dir / f"house{house}_auctions.json"
        response = client.auctions(
            settings.ruleset, house, stream_to=auctions_file, if_modified_since=known
        )

        if response.status == 304:
            log.info("Unveraendert seit %s", known)
            result.update(skipped=True, last_modified=known, reason="unveraendert", bytes=0)
            _log_run(con, runs_path, started, result, rows=0, items=0, sales=0)
            return result

        if not response.ok:
            raise RuntimeError(f"Haus {house} antwortete mit {response.status}")

        stamp = response.last_modified
        snapshot_ts = parsedate_to_datetime(stamp).astimezone(dt.timezone.utc).replace(tzinfo=None)
        result["last_modified"] = stamp
        result["snapshot_ts"] = snapshot_ts
        result["bytes"] = response.size

        if not force and snapshot_ts in store.known_snapshots(con, runs_path):
            log.info("Stand %s steckt schon im Warehouse", snapshot_ts)
            result.update(skipped=True, reason="schon verarbeitet")
            if not keep_raw:
                shutil.rmtree(raw_dir, ignore_errors=True)
            _log_run(con, runs_path, started, result, rows=0, items=0, sales=0)
            return result

        commodities_file = raw_dir / f"house{house}_commodities.json"
        commodity_response = client.commodities(settings.ruleset, house, stream_to=commodities_file)
        if commodity_response.ok:
            result["bytes"] += commodity_response.size
        else:
            log.warning("Commodities antworteten mit %s", commodity_response.status)
            commodities_file = None

    rows = load_snapshot(con, auctions_file, commodities_file)
    result["rows"] = rows
    result["auctions"] = con.execute(
        "SELECT count(*) FROM snap WHERE kind = 'auction'"
    ).fetchone()[0]
    result["commodities"] = rows - result["auctions"]

    n_items = aggregate_items(con, snapshot_ts, house)
    store.append_parquet(
        con, "items", store.dataset_path(warehouse, store.ITEMS, snapshot_ts.date()),
        order_by="item_id, kind, snapshot_ts",
    )
    result["items"] = n_items

    # Verkaeufe gibt es nur, wenn ein frueherer Stand vorliegt.
    n_sales = 0
    previous_rows = store.read_parquet(con, state_path, "prev")
    if previous_rows:
        previous_ts = con.execute("SELECT max(snapshot_ts) FROM prev").fetchone()[0]
        if previous_ts and previous_ts < snapshot_ts:
            n_sales = diff_sales(con, snapshot_ts, previous_ts, house)
            store.append_parquet(
                con, "sales", store.dataset_path(warehouse, store.SALES, snapshot_ts.date()),
                order_by="item_id, kind, snapshot_ts",
            )
            totals = con.execute(
                "SELECT sum(n_sold), sum(value_sold), sum(n_expired), sum(n_unclear), sum(n_new) FROM sales"
            ).fetchone()
            result.update(
                sold=totals[0] or 0, value_sold=totals[1] or 0,
                expired=totals[2] or 0, unclear=totals[3] or 0, new=totals[4] or 0,
                previous_ts=previous_ts,
            )
    result["sales_rows"] = n_sales

    # Diese Momentaufnahme ist der Vergleichsstand fuer den naechsten Durchlauf.
    con.execute(
        "CREATE OR REPLACE TEMP TABLE state AS SELECT ?::TIMESTAMP AS snapshot_ts, * FROM snap",
        [snapshot_ts],
    )
    store.write_parquet(con, "state", state_path, order_by="auction_id")

    _log_run(con, runs_path, started, result, rows=rows, items=n_items, sales=n_sales)

    if not keep_raw:
        shutil.rmtree(raw_dir, ignore_errors=True)

    result["seconds"] = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
    return result


def _log_run(
    con: duckdb.DuckDBPyConnection,
    runs_path: Path,
    started: dt.datetime,
    result: dict[str, Any],
    rows: int,
    items: int,
    sales: int,
) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE run_row AS
        SELECT ?::TIMESTAMP AS run_at,
               ?::TIMESTAMP AS snapshot_ts,
               ?::VARCHAR   AS last_modified,
               ?::INTEGER   AS house,
               ?::BOOLEAN   AS skipped,
               ?::BIGINT    AS rows_raw,
               ?::INTEGER   AS items,
               ?::INTEGER   AS sales_rows,
               ?::BIGINT    AS bytes
        """,
        [
            started.replace(tzinfo=None),
            result.get("snapshot_ts"),
            result.get("last_modified"),
            result["house"],
            result["skipped"],
            rows,
            items,
            sales,
            result.get("bytes", 0),
        ],
    )
    store.append_parquet(con, "run_row", runs_path, order_by="run_at")


def main(settings: Settings, house: int | None = None, force: bool = False, keep_raw: bool = False) -> int:
    result = run(settings, house=house, force=force, keep_raw=keep_raw)

    if result["skipped"]:
        stand = result.get("snapshot_ts") or result.get("last_modified")
        print(f"Nichts zu tun ({result.get('reason', 'unveraendert')}), Stand {stand}.")
        return 0

    print(f"Haus {result['house']}, Stand {result['snapshot_ts']} UTC")
    print(
        f"  {result['auctions']:>7} Auktionen, {result['commodities']:>7} Commodity-Zeilen, "
        f"{result['bytes'] / 1048576:.1f} MB"
    )
    print(f"  {result['items']:>7} Items verdichtet")
    if result.get("previous_ts"):
        print(
            f"  Vergleich mit {result['previous_ts']}: {result.get('sold', 0)} verkauft, "
            f"{result.get('expired', 0)} abgelaufen, {result.get('unclear', 0)} unklar, "
            f"{result.get('new', 0)} neu"
        )
        print(f"  Umsatz daraus: {(result.get('value_sold', 0) or 0) / 10000:.0f} Gold")
    else:
        print("  Kein frueherer Stand - Verkaeufe gibt es ab dem naechsten Durchlauf.")
    print(f"  {result.get('seconds', 0):.1f}s")
    return 0
