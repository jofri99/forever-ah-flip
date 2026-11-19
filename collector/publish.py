"""Baut aus dem Warehouse die Dateien, die die Anzeige liest.

Das Warehouse hat eine Datei je Stand - gut zum Sammeln, schlecht zum Anzeigen:
der Verlauf eines Items ueber 14 Tage laege in 336 Dateien. Hier entsteht daraus
eine Form, die ein Browser mit wenigen Teilabrufen lesen kann:

    hourly.parquet   alle Staende des Zeitfensters, nach Item sortiert und in
                     kleine Zeilengruppen geschnitten. Wer ein Item will, liest
                     am Dateiende nach, in welcher Gruppe es liegt, und holt nur die.
    market.parquet   der juengste Stand, eine Zeile je Item, dazu 24-Stunden-Werte.
    meta.json        was drin ist und von wann.

Mit einem lokalen Abzug von ForeverDB kommen dazu:

    vendor_flips.parquet    beim Haendler kaufen, im Auktionshaus verkaufen
    crafts.parquet          je Rezept Kosten, Erloes und Gewinn
    craft_reagents.parquet  die Zutaten dieser Rezepte mit Preis und Bezugsquelle

Diese Dateien sind abgeleitet und jederzeit neu baubar. Sie gehoeren deshalb
nicht ins Warehouse und nicht in Git.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import duckdb

from . import crafting, foreverdb_dump, names, store
from .config import ROOT, Settings

HOURLY = "hourly.parquet"
MARKET = "market.parquet"
META = "meta.json"
NAMES = "names.json"      # optional: {"2589": "Leinenstoff", ...}
VENDOR_FLIPS = "vendor_flips.parquet"   # optional, nur mit lokalem Abzug von ForeverDB
CRAFTS = "crafts.parquet"               # ebenso: braucht den Abzug der Rezepte
CRAFT_REAGENTS = "craft_reagents.parquet"

# Gesammelt wird das Auktionshaus der Horde. Haendler dieser Fraktion sind von dort
# aus nicht erreichbar.
UNREACHABLE_SIDE = "Alliance"

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


def _load_local_details(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    """Haendlerpreise aus dem lokalen Abzug von ForeverDB, wo Blizzard keinen nennt.

    Den Abzug gibt es nur auf diesem Rechner. In Actions bleibt die Tabelle leer.
    """
    con.execute("CREATE OR REPLACE TEMP TABLE fdb_details (item_id INTEGER, sell_price BIGINT)")
    target = foreverdb_dump.dump_dir(settings) / foreverdb_dump.DETAILS_FILE
    if not target.is_file() or target.stat().st_size == 0:
        return
    con.execute(
        f"INSERT INTO fdb_details SELECT id, max(sellPrice) FROM read_json('{store.sql_path(target)}', "
        "format = 'newline_delimited', columns = {'id': 'INTEGER', 'sellPrice': 'BIGINT'}, "
        "ignore_errors = true) WHERE id IS NOT NULL GROUP BY id"
    )


def _load_local_list(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    """Typ und Untertyp aus der lokalen Item-Liste von ForeverDB, fuer Items ohne
    Stammdaten von Blizzard. Beide Quellen benennen die Typen gleich."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fdb_list (item_id INTEGER, item_class VARCHAR, item_subclass VARCHAR)"
    )
    target = foreverdb_dump.dump_dir(settings) / "items.jsonl"
    if not target.is_file() or target.stat().st_size == 0:
        return
    con.execute(
        f"INSERT INTO fdb_list SELECT id, any_value(\"class\"), any_value(subclass) "
        f"FROM read_json('{store.sql_path(target)}', format = 'newline_delimited', "
        "columns = {'id': 'INTEGER', 'class': 'VARCHAR', 'subclass': 'VARCHAR'}, ignore_errors = true) "
        "WHERE id IS NOT NULL GROUP BY id"
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
               -- Typ und Untertyp, z. B. Recipe / Tailoring. Fuer den Filter der Oberflaeche.
               coalesce(k.item_class, fl.item_class)       AS item_class,
               coalesce(k.item_subclass, fl.item_subclass) AS item_subclass,
               -- Was ein Haendler zahlt, und sein Listenpreis je Stueck. Der Listenpreis
               -- steht bei jedem Item, auch wenn es kein Haendler fuehrt.
               coalesce(k.sell_price, fd.sell_price)::DOUBLE AS vendor_sell,
               (k.purchase_price::DOUBLE / greatest(coalesce(k.purchase_quantity, 1), 1))
                   AS vendor_buy
        FROM cur
        LEFT JOIN day ON day.item_id = cur.item_id AND day.kind = cur.kind
        LEFT JOIN known k ON k.item_id = cur.item_id AND k.status = 200
        LEFT JOIN fdb_details fd ON fd.item_id = cur.item_id
        LEFT JOIN fdb_list fl ON fl.item_id = cur.item_id
        """
    )
    return con.execute("SELECT count(*) FROM market").fetchone()[0]


def _load_vendor_offers(con: duckdb.DuckDBPyConnection, settings: Settings) -> bool:
    """Was erreichbare Haendler verkaufen: eine Zeile je Haendler und Item.

    Ohne Abzug der Haendler - in Actions also immer - bleibt die Tabelle leer,
    und es kommt False zurueck.
    """
    from . import db        # hier, um einen Importkreis zu vermeiden

    con.execute(
        "CREATE OR REPLACE TEMP TABLE vendor_offers (vendor VARCHAR, zone VARCHAR, side VARCHAR, "
        "reputation VARCHAR, item_id INTEGER, price_per_item DOUBLE, limited BOOLEAN, "
        "limited_stock INTEGER, seen_in_forever BOOLEAN, vendor_id INTEGER)"
    )
    source = db.vendor_details_source(settings)
    if source is None:
        return False
    con.execute(
        f"""
        INSERT INTO vendor_offers
        SELECT v.name, v.zone, v.side, v.reputationFaction.name,
               s.itemId, s.pricePerItem, coalesce(s.limited, false),
               s.limitedStockCount, s.seenInForever, v.id
        FROM ({source}) v, unnest(v.sells) AS t(s)
        WHERE v.side <> '{UNREACHABLE_SIDE}' AND s.pricePerItem > 0
        """
    )
    return True


def _build_vendor_flips(con: duckdb.DuckDBPyConnection) -> int:
    """Beim Haendler kaufen, im Auktionshaus verkaufen.

    Je Item der guenstigste erreichbare Haendler gegen das guenstigste Angebot im
    Auktionshaus, Gewinn nach 5 % Gebuehr. Setzt die Tabellen `market` und
    `vendor_offers` voraus.
    """
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE vendor_flips AS
        WITH cheapest AS (
            SELECT * FROM vendor_offers
            QUALIFY row_number() OVER (PARTITION BY item_id ORDER BY price_per_item, vendor_id) = 1
        )
        SELECT m.item_id, m.kind, m.item_class, m.item_subclass,
               c.price_per_item::DOUBLE                       AS vendor_price,
               m.min_price                                    AS ah_price,
               round(m.min_price * 0.95 - c.price_per_item)   AS profit,
               round((m.min_price * 0.95 - c.price_per_item) * 100.0 / c.price_per_item)
                                                              AS profit_pct,
               m.n_listings, m.qty_sold_24h, m.sales_hours_24h,
               coalesce(c.limited, false)                     AS limited,
               c.limited_stock::INTEGER                       AS limited_stock,
               c.vendor, c.zone, c.side, c.reputation,
               c.seen_in_forever
        FROM market m JOIN cheapest c USING (item_id)
        WHERE m.min_price * 0.95 > c.price_per_item
        """
    )
    return con.execute("SELECT count(*) FROM vendor_flips").fetchone()[0]


def _build_crafts(con: duckdb.DuckDBPyConnection, settings: Settings) -> int | None:
    """Herstellen und im Auktionshaus verkaufen: je Rezept Kosten, Erloes, Gewinn.

    Die Rechnung selbst steht in crafting.py und gilt genauso in der lokalen
    Datenbank. Hier kommen nur die Preise aus `market` und `vendor_offers` dazu.
    Gibt None zurueck, wenn es keinen Abzug der Rezepte gibt.
    """
    source = crafting.recipes_source(settings)
    if source is None:
        return None
    table = "CREATE OR REPLACE TEMP TABLE"
    con.execute(f"{table} foreverdb_recipes AS {source}")
    con.execute(
        f"""
        {table} ah_prices AS
        SELECT item_id, kind, min_price AS ah_price, n_listings, qty_sold_24h, sales_hours_24h,
               item_class, item_subclass
        FROM market
        WHERE min_price > 0
        QUALIFY row_number() OVER (PARTITION BY item_id ORDER BY min_price, kind) = 1;
        """
    )
    # Zum Herstellen taugt nur, wer unbegrenzt liefert.
    con.execute(crafting.model_sql(table, "SELECT * FROM vendor_offers WHERE NOT limited"))
    con.execute(crafting.costs_sql(table))

    # Fuer die Anzeige nur, was sich im Auktionshaus verkaufen laesst. Zahlen als
    # DOUBLE oder INTEGER, damit im Browser nichts als BigInt ankommt.
    con.execute(
        f"""
        {table} crafts_out AS
        SELECT recipe_id::INTEGER AS recipe_id, name, profession, category, skill::INTEGER AS skill,
               item_id::INTEGER AS item_id, kind, item_count::DOUBLE AS item_count,
               reagents::INTEGER AS reagents, unpriced::INTEGER AS unpriced,
               cost_known::DOUBLE AS cost_known, cost::DOUBLE AS cost, ah_price::DOUBLE AS ah_price,
               profit::DOUBLE AS profit, profit_pct::DOUBLE AS profit_pct,
               n_listings::INTEGER AS n_listings, qty_sold_24h::DOUBLE AS qty_sold_24h,
               sales_hours_24h::FLOAT AS sales_hours_24h,
               learned, trainer_cost::DOUBLE AS trainer_cost, recipe_item_id::INTEGER AS recipe_item_id,
               recipe_price::DOUBLE AS recipe_price, recipe_source,
               item_class, item_subclass, new_in_forever
        FROM crafts
        WHERE ah_price IS NOT NULL;

        {table} craft_reagents_out AS
        SELECT recipe_id::INTEGER AS recipe_id, item_id::INTEGER AS item_id, name,
               count::INTEGER AS count, unit_price::DOUBLE AS unit_price, source, vendor, zone,
               n_vendors::INTEGER AS n_vendors
        FROM craft_reagents
        WHERE recipe_id IN (SELECT recipe_id FROM crafts_out);
        """
    )
    return con.execute("SELECT count(*) FROM crafts_out").fetchone()[0]


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
        names.load_known(con, settings.warehouse_dir, settings.locale)
        _load_local_details(con, settings)
        _load_local_list(con, settings)
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

        # Haendler-Flips gibt es nur mit dem lokalen Abzug. Eine alte Datei darf nicht
        # liegen bleiben, wenn der Abzug fehlt - sie wuerde veraltete Zahlen zeigen.
        flip_rows = _build_vendor_flips(con) if _load_vendor_offers(con, settings) else None
        if flip_rows is None:
            (out_dir / VENDOR_FLIPS).unlink(missing_ok=True)
        else:
            store.write_parquet(
                con, "vendor_flips", out_dir / VENDOR_FLIPS,
                order_by="profit DESC, item_id", compression=COMPRESSION,
            )

        # Dasselbe fuer das Herstellen: nur mit dem Abzug der Rezepte.
        craft_rows = _build_crafts(con, settings)
        if craft_rows is None:
            (out_dir / CRAFTS).unlink(missing_ok=True)
            (out_dir / CRAFT_REAGENTS).unlink(missing_ok=True)
        else:
            store.write_parquet(
                con, "crafts_out", out_dir / CRAFTS,
                order_by="profit DESC NULLS LAST, recipe_id", compression=COMPRESSION,
            )
            store.write_parquet(
                con, "craft_reagents_out", out_dir / CRAFT_REAGENTS,
                order_by="recipe_id, item_id", compression=COMPRESSION,
            )

        # Ohne Namen zeigt die Seite "Item 2589". Zuerst gilt Blizzards Name. Wo Blizzard
        # ein Item nicht kennt, fuellt ein lokaler Abzug von ForeverDB auf - den gibt es
        # nur auf diesem Rechner, in Actions also nie.
        official = names.names_from_known(con)
        fallback = foreverdb_dump.english_names(con, settings)
        item_names = {**fallback, **official}
        # Nur Items, die im Zeitfenster vorkommen. ForeverDB kennt 23.770 Items, die
        # Seite zeigt gut 6.000 - der Rest waere bei jedem Laden mitgeschleppter Ballast.
        shown = {str(row[0]) for row in con.execute("SELECT DISTINCT item_id FROM hourly").fetchall()}
        item_names = {item_id: name for item_id, name in item_names.items() if item_id in shown}
        names_file = out_dir / NAMES
        if item_names:
            names_file.write_text(
                json.dumps(item_names, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
        market_ids = [str(row[0]) for row in con.execute("SELECT DISTINCT item_id FROM market").fetchall()]
        named_in_market = sum(1 for item_id in market_ids if item_id in item_names)
        named_official = sum(1 for item_id in market_ids if item_id in official)

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
        # Die Seite zeigt die Ansicht nur, wenn hier eine Zahl steht.
        "vendor_flips": flip_rows,
        "crafts": craft_rows,
        "name_sources": {"blizzard": named_official, "foreverdb": named_in_market - named_official},
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
    if meta["vendor_flips"] is not None:
        print(f"  {VENDOR_FLIPS:<15} {meta['vendor_flips']:>9,} Zeilen")
    if meta["crafts"] is not None:
        print(f"  {CRAFTS:<15} {meta['crafts']:>9,} Zeilen")
    sources = meta["name_sources"]
    print(
        f"  Namen fuer {meta['items_with_name']:,} von {meta['items']:,} Items "
        f"({sources['blizzard']:,} von Blizzard, {sources['foreverdb']:,} von ForeverDB)"
    )
    print(f"  nach {target}")
    return 0
